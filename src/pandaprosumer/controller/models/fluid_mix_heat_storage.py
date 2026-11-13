"""
Module containing the FluidMixHeatStorageController class.

The FluidMix coupling shared by the hot-water storages (stratified, uniform): what the tank asks its sources
for, how it splits what it receives between its demand (bypass) and itself (charge), when it discharges, the
external charge / discharge setpoints, and the reapply loop that keeps the return temperature promised to the
sources. A storage model only provides the physics of its tank (see the hooks below).
"""

import logging

import numpy as np

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.controller.return_temperature import ReturnTemperatureSolver
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C, MAX_RERUN
from pandaprosumer.controller.models.shs_ports import plug_order

logger = logging.getLogger(__name__)

#: The tank is charged AT min_useful_temp_c, so a full tank sits on that threshold and the first wall
#: loss leaves its top a few mK below it. The residual-discharge gate accepts a top layer down to this
#: margin under the threshold, otherwise a full tank refuses to serve exactly when its source falls short.
MIN_USEFUL_MARGIN_K = 0.5
#: Below this charge ΔT (target − bottom layer) the tank is full: it asks its source for no charge.
MIN_CHARGE_DELTA_T_K = 0.5
#: Lowest return the tank takes from its responders [°C]: a network not yet settled within a step can report
#: liquid water below the freezing point (a cooled DHN, -7 °C), which the tank then takes at the freezing point.
WATER_FREEZING_POINT_C = 0.


class FluidMixHeatStorageController(BasicProsumerController):
    """
    Base controller of a hot-water storage mapped with :class:`FluidMixMapping`.

    The tank is described as layers of uniform temperature, bottom first (a single layer for a uniform tank),
    with four connections placed on them (``self._ports``: charge inlet, charge outlet, discharge outlet,
    discharge inlet). The base class handles the coupling with the sources (initiators) and the demands
    (responders); a subclass provides the tank's physics:

    - in its constructor, after calling this one: ``self._layer_temps_c`` (list, bottom first), ``self.N_l``
      (number of layers), ``self._ports`` and ``self.init_layer_temps_c`` (the reference of ``e_stored_kwh``);
    - ``_layer_masses_kg``: the mass of each layer;
    - ``_outlet_c``, ``_discharge_mass_for_heat_kg``, ``_charge_mass_for_heat_kg``: what leaves the tank over
      a step for a given mass, and its inverse on each side (sizing the request and the split);
    - ``_charge_mdot_to_fill``: the charge flow that fills the tank within a step;
    - ``_exchange``: move the tank over the step with the charge and discharge flows the split decided.

    Optional hooks: ``_resolve_ports`` (connections that move with the temperatures), ``_short_circuits``
    (charge and discharge through the same connections), ``_extra_result_values`` (result columns after the
    common ones) and ``_record_step`` (debug history).

    The element must have the parameters ``min_useful_temp_c``, ``max_remaining_capacity_kwh``,
    ``t_discharge_out_tol_c``, ``max_charge_mdot_kg_per_s`` and ``t_charge_target_c``, and its data model the
    optional inputs ``mdot_charge_setpoint_kg_per_s`` and ``mdot_discharge_setpoint_kg_per_s``.
    """

    def __init__(self, prosumer, storage_object, order, level, bypass=True, in_service=True, index=None,
                 name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, storage_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.fluid = prosumer.fluid
        self.bypass = bypass

        self.t_previous_out_charge_c = np.nan
        self.t_previous_in_charge_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan
        # Return temperature the source was promised (``t_keep_return_c``) on
        # the pass being reapplied -- together with ``mdot_previous_in_kg_per_s``
        # and ``t_previous_in_charge_c`` it gives the energy the source actually
        # delivered, which anchors the reapply request (see _reapply_request).
        self.t_previous_keep_return_c = np.nan
        # Demand mass flow the split saw on that pass: a source serving the demand in parallel has served it
        # by then, so the reapply must not reserve a bypass for it (see _reapply_request).
        self.mdot_previous_demand_kg_per_s = np.nan

        # Stagnation guard for the reapply loop: if the storage's computed return
        # temperature stays within STAGNATION_TOL_C of its previous value for
        # MAX_REAPPLY_STAGNATION_COUNT consecutive iterations within the same
        # timestep, we've hit a fixed point that the upstream initiator cannot
        # reconcile (the storage's outlet temp is incompatible with the
        # initiator's expected t_keep_return_c). Accept and proceed rather
        # than reapplying forever and timing out the outer max_iter budget.
        self._reapply_last_t_received_out_c = np.nan
        self._reapply_stagnation_count = 0
        self._reapply_last_time = None

    # ------------------------------------------------------------------------------------------------------
    # Tank physics: implemented by the storage models
    # ------------------------------------------------------------------------------------------------------

    def _layer_masses_kg(self):
        """Mass of each layer (kg), bottom first."""
        raise NotImplementedError

    def _outlet_c(self, mass_kg, from_top, t_inflow_c):
        """
        Mean temperature (°C) of ``mass_kg`` of water leaving the tank over a step: through the charge outlet
        (``from_top=False``, the return to the source) or the discharge outlet (``from_top=True``, the feed
        of the demand), while the same mass enters at ``t_inflow_c``.
        """
        raise NotImplementedError

    def _discharge_mass_for_heat_kg(self, heat_kgk, t_return_c):
        """
        Mass (kg) a discharge must draw over a step to deliver ``heat_kgk`` (kg·K, i.e. energy / cp) above
        ``t_return_c``: the inverse of ``_outlet_c`` on the discharge side. A tank holding less delivers what
        it holds.
        """
        raise NotImplementedError

    def _charge_mass_for_heat_kg(self, heat_kgk, t_charge_in_c):
        """
        Mass (kg) a charge at ``t_charge_in_c`` pushes out of its outlet over a step to store ``heat_kgk``
        (kg·K, i.e. energy / cp): the inverse of ``_outlet_c`` on the charge side.
        """
        raise NotImplementedError

    def _charge_mdot_to_fill(self, t_charge_in_c):
        """Charge mass flow (kg/s) that fills the tank at ``t_charge_in_c`` within one step."""
        raise NotImplementedError

    def _exchange(self, prosumer, mdot_charge_kg_per_s, t_charge_in_c, mdot_discharge_kg_per_s,
                  t_discharge_out_c, t_return_c):
        """
        Move the tank over the step (updates ``self._layer_temps_c``) with the charge and the discharge the
        split decided. The discharge was sized on the discharge outlet's temperature at the start of the step
        (``t_discharge_out_c``): keep the heat it carries, ``mdot_discharge · (t_discharge_out − t_return)``,
        drawing the mass that really carries it.

        :return: ``(mdot_discharge_kg_per_s, t_charge_out_c, t_discharge_out_c)``: the discharge flow and the
            mean temperatures of the water that left through the charge outlet (back to the source) and the
            discharge outlet (to the demand) over the step
        """
        raise NotImplementedError

    def _resolve_ports(self, prosumer, t_charge_c, t_return_c, t_feed_c):
        """
        The layers of the four connections for this step, ``(charge_in, charge_out, discharge_out,
        discharge_in)``. Fixed by default.
        """
        return self._ports

    def _short_circuits(self, t_charge_in_c):
        """
        Whether a charge and a discharge running at once short-circuit the tank (the charge water reaches the
        discharge outlet straight). No by default.
        """
        return False

    def _extra_result_values(self, prosumer):
        """Values of the result columns that follow the common ones, in the data model's order."""
        return []

    def _record_step(self, t_received_in_c, t_demand_in_c, mdot_charge_kg_per_s, mdot_discharge_kg_per_s):
        """Called once per finalized step, for a model that keeps a debug history."""

    # ------------------------------------------------------------------------------------------------------
    # Coupling
    # ------------------------------------------------------------------------------------------------------

    @property
    def _t_received_in_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        else:
            return np.nan

    @property
    def _mdot_received_kg_per_s(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        else:
            return np.nan

    def _get_setpoint(self, prosumer, input_name):
        """
        Return the external mass-flow setpoint carried by the input ``input_name``, or NaN when none applies.

        NaN (input not mapped) or a negative value means "no setpoint" — the storage's own dispatch logic
        applies. ``0.0`` IS a setpoint (force no charge / no discharge). A negative value is the way for a
        time-series driver (which cannot emit NaN, see ``finalize``) to opt out on a given timestep.

        :param prosumer: The prosumer object
        :param input_name: ``mdot_charge_setpoint_kg_per_s`` or ``mdot_discharge_setpoint_kg_per_s``
        :return: The setpoint in kg/s (>= 0) or NaN
        """
        if input_name not in self.input_columns:
            # Controller built with a custom data model that does not declare the setpoints.
            return np.nan
        value = self._get_input(input_name, prosumer)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return np.nan
        if np.isnan(value) or value < 0:
            return np.nan
        return value

    def _is_tank_full(self, prosumer, t_charge_c, mdot_demand_kg_per_s):
        """
        Energy-budget test shared by the request side (``_t_m_to_receive_init``) and the split side
        (``_calculate_heat_storage``): the two MUST agree, otherwise the request asks the source for a
        charge that the split then bypasses onto the demand.

        :param prosumer: The prosumer object
        :param t_charge_c: Temperature at which the tank would be charged (°C)
        :param mdot_demand_kg_per_s: Downstream demand mass flow (kg/s); with no demand the tank is never
            "full" because a surplus would have nowhere to be diverted to
        :return: True if the remaining capacity is below ``max_remaining_capacity_kwh``
        """
        t_ref_c = self._get_element_param(prosumer, 'min_useful_temp_c')
        remaining_capacity_kwh = self._get_remaining_capacity_kwh(t_ref_c, t_charge_c)
        return bool(mdot_demand_kg_per_s > 0
                    and remaining_capacity_kwh < self._get_element_param(prosumer, "max_remaining_capacity_kwh"))

    def _responders_served_in_parallel(self, prosumer):
        """
        For each FluidMix responder (in ``t_m_to_deliver`` order), whether one of this storage's own initiators
        also feeds it directly, i.e. the storage sits in parallel with that source on that responder.
        """
        directly_fed = [responder for initiator in self._get_mapped_initiators(prosumer)
                        for responder in initiator._get_mapped_responders(prosumer) if responder is not self]
        return np.array([any(responder is fed for fed in directly_fed)
                         for responder in self._get_mapped_responders(prosumer)], dtype=bool)

    def _residual_discharge_mdot(self, prosumer, e_residual_kgk, t_discharge_out_c, t_demand_in_c):
        """
        Discharge mass flow that carries the residual demand energy ``e_residual_kgk`` (in kg/s·K, i.e.
        mdot·ΔT) at the discharge outlet's temperature, or 0 when the tank is spent.

        Gate on min_useful_temp_c: once the outlet layer has fallen below the minimum usable temperature
        (minus ``MIN_USEFUL_MARGIN_K``) the tank is SPENT — the demand goes (honestly) uncovered. Without this gate the divisor
        (t_discharge_out − t_demand_in) → 0 as the tank drains toward the return temperature and the mass
        flow explodes, blowing up the tank solver ("SHS model has diverged" with a negative layer).
        The flow never carries more over the step than the energy stored above ``t_demand_in_c``.
        """
        t_min_useful_c = self._get_element_param(prosumer, 'min_useful_temp_c')
        if t_min_useful_c is None or np.isnan(t_min_useful_c):
            t_min_useful_c = t_demand_in_c + 1.0  # ≥1 K usable ΔT floor
        if t_discharge_out_c >= t_min_useful_c - MIN_USEFUL_MARGIN_K and t_discharge_out_c - t_demand_in_c > 0.5:
            mdot_kg_per_s = max(0.0, e_residual_kgk / (t_discharge_out_c - t_demand_in_c))
            # The flow is sized on the outlet layer's temperature for the whole step: a nearly spent tank (a
            # thin hot top over cold water) would deliver more than it stores. Cap it at the energy stored
            # above the demand return, spread over the step.
            order = self._discharge_order()
            stored_kgk = float(np.sum(self._layer_masses_kg()[order]
                                      * np.maximum(0.0, np.asarray(self._layer_temps_c, dtype=float)[order] - t_demand_in_c)))
            return min(mdot_kg_per_s, stored_kgk / (self.resol * (t_discharge_out_c - t_demand_in_c)))
        return 0.0

    def _usable_discharge_kgk(self, prosumer, t_demand_in_c):
        """
        Heat (kg·K, i.e. energy / cp) a discharge can draw from the tank above ``t_demand_in_c``: the layers
        from the discharge outlet down to the first one under ``min_useful_temp_c`` (``MIN_USEFUL_MARGIN_K``
        margin) or not warmer than the return. Below them the water is too cold to serve the demand.
        """
        t_min_useful_c = self._get_element_param(prosumer, 'min_useful_temp_c')
        if t_min_useful_c is None or np.isnan(t_min_useful_c):
            t_min_useful_c = t_demand_in_c + 1.0
        order = self._discharge_order()
        temps_c = np.asarray(self._layer_temps_c, dtype=float)[order]
        usable = (temps_c >= t_min_useful_c - MIN_USEFUL_MARGIN_K) & (temps_c > t_demand_in_c)
        n_usable = len(usable) if usable.all() else int(np.argmin(usable))
        return float(np.sum(self._layer_masses_kg()[order][:n_usable] * (temps_c[:n_usable] - t_demand_in_c)))

    def _forced_discharge_mdot(self, prosumer, mdot_discharge_setpoint_kg_per_s, t_discharge_out_c, t_demand_in_c):
        """
        Discharge flow a forced discharge really gets, expressed as the split sizes discharges (on the outlet
        layer, ``t_discharge_out_c``): the heat the setpoint's MASS carries out of the tank over the step
        (``_outlet_c``), capped at the heat the tank holds above ``min_useful_temp_c``
        (``_usable_discharge_kgk``); 0 when the outlet layer is not warmer than the return.

        A schedule can ask a discharge from a tank it already drained (the schedule is planned outside the
        simulation). Taking the setpoint at the outlet layer's temperature over-promised that heat: the source
        was asked only for the rest of the demand, and the tank then pushed out several times the setpoint of
        lukewarm water to deliver it -- the supply fell far under the demand's feed temperature and the
        network, whose flow the substations set, could not take the extra mass. Here the tank gives what the
        scheduled mass of its real layers holds and the source is asked for the rest. The request side
        (``_t_m_to_receive_init``) and the split (``_apply_setpoints``) MUST use this same flow.
        """
        delta_t_discharge_c = t_discharge_out_c - t_demand_in_c
        if not delta_t_discharge_c > 0.5:
            return 0.0
        mass_kg = mdot_discharge_setpoint_kg_per_s * self.resol
        heat_kgk = mass_kg * max(0.0, self._outlet_c(mass_kg, True, t_demand_in_c) - t_demand_in_c)
        heat_kgk = min(heat_kgk, self._usable_discharge_kgk(prosumer, t_demand_in_c))
        return heat_kgk / (self.resol * delta_t_discharge_c)

    def _apply_setpoints(self, prosumer, mdot_charge_setpoint_kg_per_s, mdot_discharge_setpoint_kg_per_s,
                         mdot_charge_kg_per_s, mdot_bypass_kg_per_s, mdot_discharge_kg_per_s,
                         mdot_received_kg_per_s, mdot_demand_kg_per_s,
                         t_received_in_c, t_demand_out_c, t_demand_in_c, t_discharge_out_c):
        """
        Override the free charge / bypass / discharge split with the external setpoints, closing the
        mass balance ``charge + bypass == received`` and sizing the remaining free flow so the demand
        energy is met when possible.

        - charge setpoint: clamped to ``[0, received]`` (the tank cannot be charged with mass it never
          received) and ignored when the tank is full; the bypass is the rest of the received stream;
          a free discharge covers the demand energy the bypass does not carry.
        - discharge setpoint: capped at the heat the tank holds above ``min_useful_temp_c`` (zero when the
          outlet layer is not warmer than the return, see ``_forced_discharge_mdot``); a free
          bypass covers the demand energy the discharge does not carry, and the received surplus charges
          the tank (unless it is full, in which case the whole stream is bypassed, as in the free path).

        Returns ``(mdot_charge, mdot_bypass, mdot_discharge)`` in kg/s.
        """
        charge_forced = not np.isnan(mdot_charge_setpoint_kg_per_s)
        discharge_forced = not np.isnan(mdot_discharge_setpoint_kg_per_s)
        if not charge_forced and not discharge_forced:
            return mdot_charge_kg_per_s, mdot_bypass_kg_per_s, mdot_discharge_kg_per_s

        e_demand_kgk = mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c)
        delta_t_bypass_c = t_received_in_c - t_demand_in_c
        delta_t_discharge_c = t_discharge_out_c - t_demand_in_c
        tank_full = self._is_tank_full(prosumer, t_received_in_c, mdot_demand_kg_per_s)

        if discharge_forced:
            mdot_discharge_kg_per_s = self._forced_discharge_mdot(prosumer, mdot_discharge_setpoint_kg_per_s,
                                                                  t_discharge_out_c, t_demand_in_c)

        if charge_forced:
            mdot_charge_kg_per_s = 0.0 if tank_full else min(mdot_charge_setpoint_kg_per_s, mdot_received_kg_per_s)
            mdot_bypass_kg_per_s = mdot_received_kg_per_s - mdot_charge_kg_per_s
            if not discharge_forced:
                e_residual_kgk = e_demand_kgk - mdot_bypass_kg_per_s * delta_t_bypass_c
                mdot_discharge_kg_per_s = self._residual_discharge_mdot(prosumer, e_residual_kgk,
                                                                        t_discharge_out_c, t_demand_in_c)
        else:
            # Only the discharge is forced: the bypass covers the demand energy left over, the surplus charges.
            e_residual_kgk = max(0.0, e_demand_kgk - mdot_discharge_kg_per_s * delta_t_discharge_c)
            if delta_t_bypass_c > 1e-9:
                mdot_bypass_needed_kg_per_s = e_residual_kgk / delta_t_bypass_c
            else:
                mdot_bypass_needed_kg_per_s = mdot_demand_kg_per_s if e_residual_kgk > 0 else 0.0
            mdot_bypass_kg_per_s = min(mdot_received_kg_per_s, mdot_bypass_needed_kg_per_s)
            mdot_charge_kg_per_s = mdot_received_kg_per_s - mdot_bypass_kg_per_s
            if tank_full and mdot_charge_kg_per_s > 0:
                mdot_charge_kg_per_s = 0.0
                mdot_bypass_kg_per_s = mdot_received_kg_per_s

        return mdot_charge_kg_per_s, mdot_bypass_kg_per_s, mdot_discharge_kg_per_s

    def _charge_order(self):
        """Layers in the order a charge pushes them out (from its outlet towards its inlet)."""
        charge_in, charge_out, _, _ = self._ports
        return plug_order(self.N_l, charge_out, charge_in)

    def _discharge_order(self):
        """Layers in the order a discharge draws them (from its outlet towards the return inlet)."""
        _, _, discharge_out, discharge_in = self._ports
        return plug_order(self.N_l, discharge_out, discharge_in)

    def _t_m_demand(self, prosumer):
        """
        ``t_m_to_deliver`` with the responders' return bounded by ``WATER_FREEZING_POINT_C``: a network not yet
        settled within a step can report water colder than that, which would otherwise be stored in the tank
        as liquid water below 0 °C.

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature, mass flows)
        """
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_kg_per_s = self.t_m_to_deliver(prosumer)
        if t_demand_in_c < WATER_FREEZING_POINT_C:
            t_demand_in_c = WATER_FREEZING_POINT_C
            t_demand_out_c = max(t_demand_out_c, t_demand_in_c)
        return t_demand_out_c, t_demand_in_c, mdot_demand_tab_kg_per_s

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_required_kg_per_s = self._t_m_demand(prosumer)
        has_downstream_demand = np.sum(mdot_demand_tab_required_kg_per_s) >= 1e-6
        # The tank promises against the downstream demand it will actually serve: a responder its own source
        # also feeds directly (heat pump -> demand and heat pump -> tank -> demand) is served by that source, so
        # requesting its flow again would make the source deliver it twice -- a full tank then hands the second
        # share back unused at the feed temperature, on a return the source booked as delivered. What the
        # source leaves uncovered is served by the discharge, sized on the demand's residual in control_step.
        mdot_demand_tab_required_kg_per_s = np.asarray(mdot_demand_tab_required_kg_per_s, dtype=float)
        served_in_parallel = self._responders_served_in_parallel(prosumer)
        if served_in_parallel.shape != mdot_demand_tab_required_kg_per_s.shape:
            served_in_parallel = np.zeros(mdot_demand_tab_required_kg_per_s.shape, dtype=bool)
        mdot_demand_kg_per_s = float(np.sum(mdot_demand_tab_required_kg_per_s[~served_in_parallel]))
        t_charge_in_c = self._get_element_param(prosumer, 'min_useful_temp_c')

        # External dispatch setpoints (NaN = none). They must shape the REQUEST
        # exactly as they shape the split in _calculate_heat_storage, otherwise
        # the source is asked for a flow the storage then dispatches differently
        # and the reapply loop can only stagnate on an inconsistent state.
        mdot_charge_setpoint_kg_per_s = self._get_setpoint(prosumer, 'mdot_charge_setpoint_kg_per_s')
        mdot_discharge_setpoint_kg_per_s = self._get_setpoint(prosumer, 'mdot_discharge_setpoint_kg_per_s')
        self._resolve_ports(prosumer, t_charge_in_c, t_demand_in_c, t_demand_out_c)

        # Share of the demand the bypass has to serve: all of it, unless a forced
        # discharge already carries part of the demand energy from the outlet layer.
        mdot_bypass_demand_kg_per_s = mdot_demand_kg_per_s
        if not np.isnan(mdot_discharge_setpoint_kg_per_s):
            t_discharge_out_c = self._layer_temps_c[self._ports[2]]
            delta_t_discharge_c = t_discharge_out_c - t_demand_in_c
            e_demand_kgk = mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c)
            mdot_discharge_kg_per_s = self._forced_discharge_mdot(prosumer, mdot_discharge_setpoint_kg_per_s,
                                                                  t_discharge_out_c, t_demand_in_c)
            if delta_t_discharge_c > 0.5 and e_demand_kgk > 0:
                e_residual_kgk = max(0.0, e_demand_kgk - mdot_discharge_kg_per_s * delta_t_discharge_c)
                mdot_bypass_demand_kg_per_s = mdot_demand_kg_per_s * e_residual_kgk / e_demand_kgk
        # If the required feed downstream temperature is null, it means that there is no downstream mapped controller
        # so ask treturn_required_c charge the storage at the min_useful_temp_c
        # (a demand served in parallel still sets the charge temperature: the tank is charged for it)
        if t_demand_out_c < 1e-6 or not has_downstream_demand:
            t_required_in_c = t_charge_in_c
        else:
            t_required_in_c = t_demand_out_c

        # Optional explicit charging target. Without it the charge request
        # follows the downstream demand's feed temperature: when that demand
        # asks for the minimum usable feed (e.g. TminECS), the tank is charged
        # AT the usability threshold and stores zero margin — it drains on the
        # first source-off hour and the demand goes uncovered while the
        # upstream producer idles. Setting t_charge_target_c to the producer's
        # design outlet (e.g. an optimiser's constant condenser setpoint,
        # TcstCondOut) makes the tank charge toward its design top temperature.
        t_charge_target_c = self._get_element_param(prosumer, 't_charge_target_c')
        if t_charge_target_c is not None and not np.isnan(t_charge_target_c):
            t_required_in_c = max(t_required_in_c, float(t_charge_target_c))

        self._resolve_ports(prosumer, t_required_in_c, t_demand_in_c, t_demand_out_c)
        # TODO: Is the return temp the bottom layer temp or the responders' t_return ?
        t_charge_out_c = self._t_charge_out

        # If the storage is full -> do not required heat from upstream for charging
        if self._is_tank_full(prosumer, t_required_in_c, mdot_demand_kg_per_s):
            # FixMe: Go here if min_useful_temp_c = t_charge_in_c > t_required_in_c = t_demand_out_c
            forward_request = (t_demand_out_c, t_demand_in_c, mdot_bypass_demand_kg_per_s)
            if np.isnan(self.t_previous_out_charge_c) or not np.isnan(mdot_charge_setpoint_kg_per_s):
                return forward_request
            # A source that delivered more than this bypass (held at its minimum) is re-asked, like a charging
            # tank's source, for what it delivered at the return its surplus gives back (_reapply_request):
            # returning the forward request here promised the demanded return whatever it delivered
            return self._reapply_request(prosumer, t_demand_out_c, t_demand_in_c, mdot_bypass_demand_kg_per_s,
                                         t_charge_out_c, forward_request)

        if not np.isnan(mdot_charge_setpoint_kg_per_s):
            # Forced charge: ask upstream for exactly that (the cap below still applies).
            mdot_charge_kg_per_s = mdot_charge_setpoint_kg_per_s
        else:
            mdot_charge_kg_per_s = self._charge_mdot_to_fill(t_required_in_c)

        # Optional cap so the storage doesn't ask the upstream producer for more
        # mass flow than it can supply. Without this, oversized cold-layer
        # counts trigger an unbounded reapply loop and ControllerNotConverged.
        max_charge_mdot = self._get_element_param(prosumer, 'max_charge_mdot_kg_per_s')
        if max_charge_mdot is not None and not np.isnan(max_charge_mdot):
            mdot_charge_kg_per_s = min(mdot_charge_kg_per_s, float(max_charge_mdot))

        # Iso-energy bypass flow to REQUEST from the producer — must match the
        # split applied in _calculate_heat_storage. The producer will deliver at
        # t_required_in_c; the bypass serving the demand carries the demand
        # energy with mdot_demand·(t_demand_out−t_demand_in)/(t_required_in−t_demand_in).
        # Requesting the full mdot_demand instead (the old behaviour) over-sizes
        # the producer when t_required_in > t_demand_out: the producer's q_cond
        # is then computed against a promised return that the storage never
        # actually delivers, so HP.q_cond and SHS.q_received disagree by the
        # bypass surplus (can reach ~95 kW per near-full-tank step in a DHW loop).
        delta_t_demand_c = t_demand_out_c - t_demand_in_c
        if t_required_in_c - t_demand_in_c > 1e-9 and t_required_in_c > t_demand_out_c:
            mdot_bypass_kg_per_s = mdot_bypass_demand_kg_per_s * delta_t_demand_c / (t_required_in_c - t_demand_in_c)
        else:
            mdot_bypass_kg_per_s = mdot_bypass_demand_kg_per_s

        t_charge_out_c = self._outlet_c(mdot_charge_kg_per_s * self.resol, False, t_required_in_c)
        if t_charge_out_c >= t_required_in_c - 1e-6:
            # The water the charge would push out is no colder than the charge (a tank heated above the
            # source's feed by another source): this source cannot charge it.
            mdot_charge_kg_per_s = 0.0
            t_charge_out_c = t_required_in_c
        mdot_required_kg_per_s = mdot_bypass_kg_per_s + mdot_charge_kg_per_s
        if mdot_required_kg_per_s == 0:
            t_required_out_c = t_required_in_c
        else:
            t_required_out_c = (mdot_bypass_kg_per_s * t_demand_in_c + mdot_charge_kg_per_s * t_charge_out_c) / mdot_required_kg_per_s

        if not np.isnan(self.t_previous_out_charge_c):
            if not np.isnan(mdot_charge_setpoint_kg_per_s):
                # A forced charge is not renegotiated from the fed-back return temperature
                # (feat/shs-forced-setpoints): keep the forward request built around the setpoint -- unless
                # the source delivered less (it is capped): the return then comes from the mass it delivered,
                # anchored on its energy, and never more than the setpoint asked.
                if not self.mdot_previous_in_kg_per_s < mdot_required_kg_per_s - 1e-9:
                    return t_required_in_c, t_required_out_c, mdot_required_kg_per_s
                return self._forced_charge_reapply_request(mdot_charge_kg_per_s,
                                                           (t_required_in_c, t_required_out_c, mdot_required_kg_per_s),
                                                           mdot_bypass_demand_kg_per_s * delta_t_demand_c,
                                                           t_demand_in_c)
            # The bypass share of the demand (all of it unless a forced discharge carries part of it).
            return self._reapply_request(prosumer, t_demand_out_c, t_demand_in_c, mdot_bypass_demand_kg_per_s,
                                         t_charge_out_c,
                                         (t_required_in_c, t_required_out_c, mdot_required_kg_per_s))

        return t_required_in_c, t_required_out_c, mdot_required_kg_per_s

    def _forced_charge_reapply_request(self, mdot_charge_setpoint_kg_per_s, forward_request,
                                       e_demand_kgk_per_s=0.0, t_demand_in_c=np.nan):
        """
        Reapply request of a forced charge the source could not deliver in full: ``_apply_setpoints`` puts
        what arrives into the tank first (up to the setpoint), so all the energy the source delivered charges
        it. Request the mass that energy pushes out of the charge outlet, at its mean temperature.

        The demand ``e_demand_kgk_per_s`` (kg·K/s) is then served by the discharge, and when the tank
        short-circuits (see ``_short_circuits``) the charge water goes to it first: that share comes back at
        the demand's return ``t_demand_in_c``, only the rest pushes water out of the charge outlet.
        """
        t_in_c = self.t_previous_in_charge_c
        t_keep_prev_c = self.t_previous_keep_return_c
        mdot_prev_kg_per_s = self.mdot_previous_in_kg_per_s
        if np.isnan(t_in_c) or np.isnan(t_keep_prev_c) or not mdot_prev_kg_per_s > 0 or t_in_c - t_keep_prev_c <= 1e-9:
            return forward_request
        heat_kgk = mdot_prev_kg_per_s * (t_in_c - t_keep_prev_c) * self.resol
        short_kg = 0.0
        delta_t_short_c = t_in_c - t_demand_in_c
        if self._short_circuits(t_in_c) and e_demand_kgk_per_s > 0 and delta_t_short_c > 1e-9:
            short_kg = min(heat_kgk, e_demand_kgk_per_s * self.resol) / delta_t_short_c
            short_kg = min(short_kg, mdot_charge_setpoint_kg_per_s * self.resol)
            heat_kgk -= short_kg * delta_t_short_c
        net_kg = min(self._charge_mass_for_heat_kg(heat_kgk, t_in_c),
                     mdot_charge_setpoint_kg_per_s * self.resol - short_kg) if heat_kgk > 0 else 0.0
        mass_kg = short_kg + net_kg
        if mass_kg <= 0:
            return forward_request
        t_out_c = self._outlet_c(net_kg, False, t_in_c) if net_kg > 0 else t_in_c
        if short_kg > 0:
            t_out_c = (short_kg * t_demand_in_c + net_kg * t_out_c) / mass_kg
        return t_in_c, t_out_c, mass_kg / self.resol

    def _reapply_request(self, prosumer, t_demand_out_c, t_demand_in_c, mdot_demand_kg_per_s,
                         t_charge_out_c, forward_request):
        """
        Request to send upstream on a REAPPLY pass of the convergence loop.

        The source (HP condenser, HX, ...) delivered ``mdot_previous_in_kg_per_s``
        at ``t_previous_in_charge_c`` on the previous pass, heating it from the
        return it was promised (``t_previous_keep_return_c``); the storage then split
        that stream (demand bypass first, remainder to charge) and found the
        actual mixed return ``t_previous_out_charge_c`` differed from the promise.

        A source that under-delivered was LIMITED (power / mass-flow cap) and keeps
        its feed temperature while shrinking the mass flow when the return it is
        promised gets colder. Re-requesting the forward charge mass flow at the
        colder actual return (the historical behaviour) therefore makes it deliver
        even less mass, the storage -- which gives the bypass priority -- loses charge
        share, the mass-weighted return drops again, and so on: a fixed-point
        iteration whose contraction factor tends to 1 as the charge outlet approaches
        the feed temperature (the charge stream then carries almost no energy but
        dominates the mass-weighted return). Observed: -0.22 K per pass from 60.5 to
        46.9 °C, neither the convergence band nor the stagnation guard could ever
        fire, ``ControllerNotConverged`` after ``max_iter`` passes.

        Anchor the request on the ENERGY the source actually delivered instead:
        split ``q_prev`` exactly as ``_calculate_heat_storage`` will (iso-energy
        demand bypass first, the remainder to charge, nothing to charge when the
        tank is full or the source cannot even cover the bypass), request the
        resulting total mass flow at the resulting mixed return. The source can
        deliver that energy (it just did), so it delivers exactly the request, the
        split reproduces the promised return, and the pair converges in one pass
        (a second one at most, for the small cp differences between the two sides).

        No ``max_charge_mdot_kg_per_s`` cap here, on purpose: that cap bounds the
        FORWARD request ("don't ask upstream for more than it can supply"). A
        source that honours requests never delivers more energy than the (already
        capped) forward request, so the anchored charge is within the cap anyway;
        a source pinned at a minimum power (HP at ``min_p_comp_kw``) delivers its
        pinned energy whatever is asked, and capping the request would only promise
        a return it cannot honour (observed 1.2 K promised/actual gap while a
        pinned HP filled a tank capped at 10 kg/s). The request must mirror what
        the source will actually deliver for the boundary to conserve energy.

        :return: (feed temperature, return temperature, mass flow) to request
        """
        t_in_c = self.t_previous_in_charge_c
        mdot_prev_kg_per_s = self.mdot_previous_in_kg_per_s
        t_keep_prev_c = self.t_previous_keep_return_c
        if (np.isnan(t_in_c) or np.isnan(mdot_prev_kg_per_s) or np.isnan(t_keep_prev_c)
                or mdot_prev_kg_per_s <= 0 or t_in_c - t_keep_prev_c <= 1e-9):
            # No usable delivery to anchor on -- keep the forward request.
            return forward_request
        self._resolve_ports(prosumer, t_in_c, t_demand_in_c, t_demand_out_c)
        # What each demand asks for: the split dispatches the bypass over them in merit order
        mdot_demand_tab_kg_per_s = np.asarray(self._t_m_demand(prosumer)[2], dtype=float)

        if not np.isnan(self.mdot_previous_demand_kg_per_s):
            # Split as the previous pass's split did: a demand already served in parallel takes no bypass.
            mdot_demand_kg_per_s = min(mdot_demand_kg_per_s, self.mdot_previous_demand_kg_per_s)

        cp_src_j_per_kgk = float(self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_in_c + t_keep_prev_c) / 2))
        q_prev_w = mdot_prev_kg_per_s * cp_src_j_per_kgk * (t_in_c - t_keep_prev_c)

        # Iso-energy demand bypass at the ACTUAL delivered feed temperature
        # (same formula as _calculate_heat_storage).
        delta_t_bypass_c = t_in_c - t_demand_in_c
        if delta_t_bypass_c > 1e-9:
            mdot_bypass_full_kg_per_s = mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c) / delta_t_bypass_c
            cp_bypass_j_per_kgk = float(self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_in_c + t_demand_in_c) / 2))
            q_bypass_full_w = mdot_bypass_full_kg_per_s * cp_bypass_j_per_kgk * delta_t_bypass_c
        else:
            mdot_bypass_full_kg_per_s = 0.0
            cp_bypass_j_per_kgk = np.nan
            q_bypass_full_w = 0.0

        # Same "tank full" energy-budget test as _calculate_heat_storage, at the
        # delivered feed temperature: a full tank bypasses the whole stream.
        t_charge_ref_in_c = self._get_element_param(prosumer, 'min_useful_temp_c')
        remaining_capacity_kwh = self._get_remaining_capacity_kwh(t_charge_ref_in_c, t_in_c)
        tank_full = remaining_capacity_kwh < self._get_element_param(prosumer, "max_remaining_capacity_kwh")

        if q_prev_w >= q_bypass_full_w and not (tank_full and mdot_demand_kg_per_s > 0):
            # Source covers the demand bypass; the surplus energy charges the tank. The charge mass and its
            # return come from the same outflow the split will book (the return depends on the mass).
            mdot_bypass_kg_per_s = mdot_bypass_full_kg_per_s
            cp_charge_j_per_kgk = float(self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_in_c + t_charge_out_c) / 2))
            heat_kgk = max(0.0, q_prev_w - q_bypass_full_w) * self.resol / cp_charge_j_per_kgk
            mass_kg = self._charge_mass_for_heat_kg(heat_kgk, t_in_c)
            if mdot_demand_kg_per_s > 0:
                # The split sends what the tank cannot take within the step to the demand
                mass_kg = min(mass_kg, self._charge_mdot_to_fill(t_in_c) * self.resol)
            mdot_charge_kg_per_s = mass_kg / self.resol
            t_charge_out_c = self._outlet_c(mass_kg, False, t_in_c)
            stored_kgk = mass_kg * (t_in_c - t_charge_out_c)
            if mdot_demand_kg_per_s > 0 and heat_kgk - stored_kgk > 1e-9 and delta_t_bypass_c > 1e-9:
                mdot_bypass_kg_per_s += (heat_kgk - stored_kgk) / self.resol / delta_t_bypass_c
            t_bypass_return_c, _ = self._bypass_return_c(prosumer, mdot_bypass_kg_per_s, mdot_demand_tab_kg_per_s,
                                                         t_demand_in_c)
        else:
            # Source cannot even cover the bypass (the storage will discharge the
            # rest), or the tank is full (whole stream bypassed): no charge, the
            # delivered energy goes to the demand.
            mdot_charge_kg_per_s = 0.0
            mdot_bypass_kg_per_s = 0.0
            t_bypass_return_c = t_demand_in_c
            if delta_t_bypass_c > 1e-9:
                # A source held at its minimum delivers more than the demands ask for: the split dumps the
                # surplus on the last demand, so the return is their mix for those flows, and that return sets
                # the mass the delivered energy carries, hence the surplus: the same fixed point a capped
                # producer solves for its return. Promised at the demanded mix (46.9 °C for 53.5 °C given
                # back), the source booked 10 kW of a 50 kW bypass that its demands never saw.
                return_solver = ReturnTemperatureSolver()
                for _ in range(MAX_RERUN):
                    cp_bypass_j_per_kgk = float(self.fluid.get_heat_capacity(
                        CELSIUS_TO_K + (t_in_c + t_bypass_return_c) / 2))
                    mdot_bypass_kg_per_s = q_prev_w / (cp_bypass_j_per_kgk * (t_in_c - t_bypass_return_c))
                    t_mixed_c, t_returns_c = self._bypass_return_c(prosumer, mdot_bypass_kg_per_s,
                                                                   mdot_demand_tab_kg_per_s, t_demand_in_c)
                    t_next_c = return_solver.next_guess(t_bypass_return_c, t_mixed_c, t_returns_c)
                    if t_next_c is None or t_in_c - t_next_c <= 1e-9:
                        break
                    t_bypass_return_c = t_next_c

        mdot_required_kg_per_s = mdot_bypass_kg_per_s + mdot_charge_kg_per_s
        if mdot_required_kg_per_s > 1e-12:
            t_required_out_c = (mdot_charge_kg_per_s * t_charge_out_c
                                + mdot_bypass_kg_per_s * t_bypass_return_c) / mdot_required_kg_per_s
        else:
            t_required_out_c = t_in_c
        return t_in_c, t_required_out_c, mdot_required_kg_per_s

    def _bypass_return_c(self, prosumer, mdot_bypass_kg_per_s, mdot_demand_tab_kg_per_s, t_demand_in_c):
        """
        Return (°C) of a bypass of ``mdot_bypass_kg_per_s`` to the demands: the demanded mix ``t_demand_in_c``
        up to what they ask for; beyond it, their mix for the flows the split dispatches, the surplus going to
        the last one (``dump_on_last``, as in :meth:`control_step`).

        :return: A Tuple (return (float), the demands' returns (np.array[float]))
        """
        if mdot_bypass_kg_per_s <= np.sum(mdot_demand_tab_kg_per_s) + 1e-9:
            return t_demand_in_c, self.get_treturn_tab_c(prosumer)
        result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer, mdot_bypass_kg_per_s,
                                                               mdot_demand_tab_kg_per_s,
                                                               overflow_strategy="dump_on_last")
        return self._mixed_return_temperature_c(prosumer, result_mdot_tab_kg_per_s, t_demand_in_c)

    @property
    def _t_charge_out(self):
        """
        Temperature of the fluid returned to the initiator in °C (the charge outlet's layer)
        """
        return self._layer_temps_c[self._ports[1]]

    def _get_remaining_capacity_kwh(self, extraction_temp_c, t_charge_c):
        """
        Heat (kWh) a charge at ``t_charge_c`` can still put into the tank: every layer colder than the charge
        brought up to it. Zero when the charge is not warmer than the useful extraction temperature (it would
        store nothing usable).

        Measured on the current layers, not against the initial state: a tank that starts full (initial
        layers at the charge temperature, e.g. behind a CHP) and is drained below its useful temperature
        would read 0 kWh left: "full" for good, it never asked for a charge again.

        :param extraction_temp_c: Useful extraction temperature (°C)
        :param t_charge_c: Charge temperature (°C)
        :return: Remaining capacity (kWh)
        """
        if t_charge_c < extraction_temp_c - .1:
            return 0.
        temps_c = np.asarray(self._layer_temps_c, dtype=float)
        per_layer_j = (self._layer_masses_kg() * np.asarray(self.fluid.get_heat_capacity(CELSIUS_TO_K + temps_c))
                       * np.maximum(0., t_charge_c - temps_c))
        return float(np.sum(per_layer_j)) / 3.6e6

    def _get_stored_energy_kwh(self, t_extraction_c):
        """
        Stored energy E(t) at any time, compared to the initial state (``init_layer_temps_c``)

        :param t_extraction_c: Useful Extraction temperature (only the layers above this level are counted) (°C)
        :type t_extraction_c: float
        :return: Stored energy E(t) compared to initial state (kWh)
        """
        temps_c = np.asarray(self._layer_temps_c, dtype=float)
        per_layer_j = (self._layer_masses_kg() * np.asarray(self.fluid.get_heat_capacity(CELSIUS_TO_K + temps_c))
                       * (temps_c - np.asarray(self.init_layer_temps_c, dtype=float)))
        return float(np.sum(per_layer_j[temps_c >= t_extraction_c - .1])) / 3.6e6

    def _calculate_heat_storage(self, prosumer, mdot_demand_kg_per_s, t_received_in_c, t_demand_out_c, t_demand_in_c,
                                t_discharge_out_c, mdot_received_kg_per_s, t_charge_out_c):

        # NaN-to-zero guard at the contract boundary. ``_t_received_in_c`` and
        # ``_mdot_received_kg_per_s`` are NaN whenever the upstream FluidMix
        # initiator is off (e.g. HP_ON=0 from the optimiser). A NaN here
        # signals "no flow contract", not "unknown value": physically the
        # side carries no enthalpy and the temperature is irrelevant. Treat
        # as zero so the bypass branch and the tank solver downstream see
        # clean values. The ``0 * NaN == NaN`` propagation in IEEE 754 would
        # otherwise corrupt every layer of ``_layer_temps_c`` within a single
        # sub-step. See ``tests/integrations/test_shs_nan_propagation.py``.
        if np.isnan(mdot_received_kg_per_s):
            mdot_received_kg_per_s = 0.0
        if np.isnan(t_received_in_c):
            assert mdot_received_kg_per_s == 0, (
                f"Storage {self.name}: t_received_in_c is NaN but "
                f"mdot_received_kg_per_s is non-zero ({mdot_received_kg_per_s}) "
                f"-- upstream initiator contract violation at timestep {self.time}."
            )
            t_received_in_c = float(self._layer_temps_c[-1])
        if np.isnan(t_demand_in_c):
            assert mdot_demand_kg_per_s == 0, (
                f"Storage {self.name}: t_demand_in_c is NaN but "
                f"mdot_demand_kg_per_s is non-zero ({mdot_demand_kg_per_s}) "
                f"-- downstream demand contract violation at timestep {self.time}."
            )
            t_demand_in_c = float(self._layer_temps_c[0])
        self._resolve_ports(prosumer, t_received_in_c, t_demand_in_c, t_demand_out_c)

        if not self.bypass:
            mdot_charge_kg_per_s = mdot_received_kg_per_s
            mdot_discharge_kg_per_s = mdot_demand_kg_per_s
            mdot_bypass_kg_per_s = 0
            t_bypass_in_c = t_received_in_c
        else:
            # Bypass mass flow that carries the demand energy when the received
            # stream is delivered straight to the demand at t_received_in_c.
            #
            # ISO-ENERGY: the bypass enters the demand at t_received_in_c and
            # returns at t_demand_in_c, so the energy it carries per unit mass is
            # cp·(t_received_in_c − t_demand_in_c). To deliver exactly the demand
            # energy mdot_demand·cp·(t_demand_out_c − t_demand_in_c), the bypass
            # flow must be
            #     mdot = mdot_demand · (t_demand_out − t_demand_in)
            #                        / (t_received_in − t_demand_in).
            # The denominator MUST be the actual bypass ΔT (t_received_in −
            # t_demand_in), NOT (t_received_in − t_demand_out): the latter sizes
            # the flow as if the bypass were delivered at t_demand_out, so when
            # the received water is hotter (e.g. HP at t_cond_out=65 serving a
            # 58/51 °C demand) the bypass carries ~2× the demand energy and the
            # HeatDemand books q_received ≈ 2·q_demand — i.e. negative
            # q_uncovered / over-serve (can reach ~−30 kW avg in a DHW loop, with
            # ~20 % wasted HP electricity). Equivalent to a mixing-valve model
            # (hot bypass blended with return to hit t_demand_out at mdot_demand)
            # — both give the same mdot.
            delta_t_demand_c = t_demand_out_c - t_demand_in_c
            if t_received_in_c - t_demand_in_c > 1e-9:
                mdot_toprovide_kg_per_s = mdot_demand_kg_per_s * delta_t_demand_c / (t_received_in_c - t_demand_in_c)
            else:
                mdot_toprovide_kg_per_s = mdot_demand_kg_per_s
            if mdot_toprovide_kg_per_s > mdot_received_kg_per_s:
                # If this energy cannot be provided, no charging but discharge
                mdot_bypass_kg_per_s = mdot_received_kg_per_s
                t_bypass_in_c = t_received_in_c
                mdot_charge_kg_per_s = 0
                # If the required output temperature is between the feed and outlet layer temperature, calculate
                # the discharge mass flow to get this required temperature
                if abs(t_demand_out_c - t_discharge_out_c) > self._get_element_param(prosumer, "t_discharge_out_tol_c"):
                    mdot_discharge_kg_per_s = mdot_bypass_kg_per_s * (t_received_in_c - t_demand_out_c) / (
                            t_demand_out_c - t_discharge_out_c)
                    if mdot_discharge_kg_per_s > 0:
                        # The mixing valve never draws more than the demand energy the bypass leaves (iso-energy):
                        # with the outlet layer just under the demand's feed and the bypass hot, the formula above
                        # draws an unbounded flow of lukewarm water. A source at its maximum power falling
                        # 1e-5 kg/s short of the demand made a uniform tank at 58 degC serve a 60/35 degC demand of
                        # 80 kW with 211 kW.
                        e_residual_kgk = max(0.0, mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c)
                                             - mdot_bypass_kg_per_s * (t_received_in_c - t_demand_in_c))
                        delta_t_discharge_c = t_discharge_out_c - t_demand_in_c
                        mdot_discharge_kg_per_s = (min(mdot_discharge_kg_per_s, e_residual_kgk / delta_t_discharge_c)
                                                   if delta_t_discharge_c > 1e-9 else 0.0)
                else:
                    mdot_discharge_kg_per_s = mdot_demand_kg_per_s - mdot_bypass_kg_per_s
                if mdot_discharge_kg_per_s <= 0 and mdot_demand_kg_per_s > 0:
                    # The mixing formula above is degenerate when there is no
                    # incoming (bypass) flow at all — e.g. the upstream producer
                    # is OFF and the storage alone serves the demand: it yields
                    # mdot_discharge = 0 × (...) = 0 and the tank never
                    # discharges, even with the top layers hot and usable
                    # (observed: 83 % of a day's DHW demand unmet while
                    # ~270 kWh sat in the tank above the demanded feed temp).
                    # Fall through to the energy-based calculation: discharge at
                    # the outlet layer's temperature with the mass flow that carries
                    # the demanded energy (considering that the return
                    # temperature would be the same).
                    #
                    # Gate on min_useful_temp_c: once the outlet layer has fallen
                    # below the minimum usable temperature the tank is SPENT —
                    # the demand goes (honestly) uncovered (see _residual_discharge_mdot).
                    e_demand = mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c)
                    e_bypass = mdot_bypass_kg_per_s * (t_received_in_c - t_demand_in_c)  # iso-energy, as in _apply_setpoints
                    mdot_discharge_kg_per_s = self._residual_discharge_mdot(prosumer, e_demand - e_bypass,
                                                                            t_discharge_out_c, t_demand_in_c)
            else:
                # Enough (or more than enough) received to serve the demand by
                # bypass; the surplus (mdot_received − mdot_toprovide) would
                # charge the tank. But if the tank is FULL it cannot store that
                # surplus: charging it anyway drives the storage's recomputed return
                # up toward the outlet temperature while the source was
                # handed (and delivered against) the demand-return contract
                # ``t_keep_return_c``. The two returns then diverge, the reapply
                # loop can only stagnate, the source's return contract creeps
                # toward the feed so a power-limited source (HP at min_p_comp)
                # explodes its mass flow at the vanishing ΔT, and hundreds of kW
                # silently vanish (source books its full duty, storage books only what
                # its inflated return implies).
                #
                # When full, charge nothing and BYPASS the whole received stream
                # to the demand — over-serving it (``q_uncovered`` goes negative)
                # rather than losing the energy. The return then collapses to the
                # demand return (the mass-flow-weighted mean with zero charge
                # share), coherent with the contract, and the boundary energy is
                # conserved.
                # "Full" by the SAME energy-budget test _t_m_to_receive_init uses
                # to stop requesting charge — the two MUST agree, otherwise the
                # request asks the source for a large charge while the calc
                # bypasses it, dumping the whole stream onto the demand.
                if self._is_tank_full(prosumer, t_received_in_c, mdot_demand_kg_per_s):
                    # Surplus can only be diverted if there IS a demand to
                    # over-serve. With no demand (mdot_demand == 0) the surplus
                    # has nowhere to go: fall through to the charge path, which
                    # with feed ≈ outlet stores ≈0 energy and returns q ≈ 0
                    # (rather than fabricating a bypass to a nonexistent demand
                    # at t_demand_in = 0).
                    mdot_charge_kg_per_s = 0.0
                    mdot_bypass_kg_per_s = mdot_received_kg_per_s
                else:
                    mdot_bypass_kg_per_s = mdot_toprovide_kg_per_s
                    mdot_charge_kg_per_s = mdot_received_kg_per_s - mdot_bypass_kg_per_s
                mdot_discharge_kg_per_s = 0
                t_bypass_in_c = t_received_in_c

        # External dispatch setpoints (MILP supervisor, replayed optimiser schedule, ...)
        # override the free split above while keeping charge + bypass == received.
        # See _apply_setpoints; the request in _t_m_to_receive_init uses the same
        # setpoints so upstream was asked for a consistent flow.
        mdot_charge_kg_per_s, mdot_bypass_kg_per_s, mdot_discharge_kg_per_s = self._apply_setpoints(
            prosumer,
            self._get_setpoint(prosumer, 'mdot_charge_setpoint_kg_per_s'),
            self._get_setpoint(prosumer, 'mdot_discharge_setpoint_kg_per_s'),
            mdot_charge_kg_per_s, mdot_bypass_kg_per_s, mdot_discharge_kg_per_s,
            mdot_received_kg_per_s, mdot_demand_kg_per_s,
            t_received_in_c, t_demand_out_c, t_demand_in_c, t_discharge_out_c)

        # Secondary NaN guard: ``mdot_charge_kg_per_s`` / ``mdot_discharge_kg_per_s``
        # are derived above from the (now NaN-cleaned) received/demand values, so
        # they should already be finite. Defend against a future refactor of the
        # bypass arithmetic introducing a fresh NaN path -- a NaN mdot reaching
        # the tank solver would corrupt every layer silently.
        if np.isnan(mdot_charge_kg_per_s):
            mdot_charge_kg_per_s = 0.0
        if np.isnan(mdot_discharge_kg_per_s):
            mdot_discharge_kg_per_s = 0.0

        # A charge larger than what fills the tank within the step would pass through and return hot: with a
        # demand downstream, the excess goes to it instead (over-serving it, like the full-tank bypass)
        if mdot_demand_kg_per_s > 0 and np.isnan(self._get_setpoint(prosumer, 'mdot_charge_setpoint_kg_per_s')):
            mdot_fill_kg_per_s = self._charge_mdot_to_fill(t_received_in_c)
            if mdot_charge_kg_per_s > mdot_fill_kg_per_s:
                mdot_bypass_kg_per_s += mdot_charge_kg_per_s - mdot_fill_kg_per_s
                mdot_charge_kg_per_s = mdot_fill_kg_per_s
                t_bypass_in_c = t_received_in_c

        mdot_discharge_kg_per_s, t_charge_out_c, t_discharge_out_c = self._exchange(
            prosumer, mdot_charge_kg_per_s, t_received_in_c, mdot_discharge_kg_per_s, t_discharge_out_c,
            t_demand_in_c)

        cp_discharge_j_per_kgk = float(self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_discharge_out_c + t_demand_in_c) / 2))
        q_discharge_kw = mdot_discharge_kg_per_s * cp_discharge_j_per_kgk * (t_discharge_out_c - t_demand_in_c) / 1e3

        # Stored: every layer against the initial state (it used to count only the layers above
        # min_useful_temp_c, so a tank a few mK under that threshold reported 0 kWh while holding hundreds).
        # Usable: the layers the demand can still draw (see _residual_discharge_mdot), above its return.
        e_stored_kwh = self._get_stored_energy_kwh(-np.inf)
        min_useful_temp_c = self._get_element_param(prosumer, 'min_useful_temp_c')
        if min_useful_temp_c is None or np.isnan(min_useful_temp_c):
            min_useful_temp_c = t_demand_in_c + 1.0
        temps_c = np.asarray(self._layer_temps_c, dtype=float)
        usable = (temps_c >= min_useful_temp_c - MIN_USEFUL_MARGIN_K) & (temps_c > t_demand_in_c)
        e_usable_kwh = float(np.sum((self._layer_masses_kg() * np.asarray(self.fluid.get_heat_capacity(CELSIUS_TO_K + temps_c))
                                     * (temps_c - t_demand_in_c))[usable])) / 3.6e6

        cp_bypass_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_bypass_in_c + t_demand_in_c) / 2)
        q_bypass_kw = mdot_bypass_kg_per_s * cp_bypass_j_per_kgk * (t_bypass_in_c - t_demand_in_c) / 1e3
        q_delivered_kw = q_discharge_kw + q_bypass_kw

        mdot_delivered_kg_per_s = mdot_bypass_kg_per_s + mdot_discharge_kg_per_s

        if mdot_delivered_kg_per_s > 0:
            t_delivered_out_c = (t_bypass_in_c * mdot_bypass_kg_per_s + t_discharge_out_c * mdot_discharge_kg_per_s) / mdot_delivered_kg_per_s
        else:
            t_delivered_out_c = t_discharge_out_c

        if abs(mdot_charge_kg_per_s + mdot_bypass_kg_per_s) < 1e-3:
            # Idle storage (no charge / no bypass): return ``t_received_in_c``
            # as a pass-through so downstream q_received_kw resolves to zero.
            # Note we use the NaN-cleaned ``t_received_in_c`` from above, not
            # the raw ``self._t_received_in_c`` property which still reports
            # NaN whenever upstream is off and would re-poison the result tuple.
            t_received_out_c = t_received_in_c
        else:
            t_received_out_c = (mdot_charge_kg_per_s * t_charge_out_c + mdot_bypass_kg_per_s * t_demand_in_c) / (mdot_charge_kg_per_s + mdot_bypass_kg_per_s)

        cp_received_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_received_in_c + t_received_out_c) / 2)
        q_received_kw = mdot_received_kg_per_s * cp_received_j_per_kgk * (t_received_in_c - t_received_out_c) / 1e3

        cp_charge_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_received_in_c + t_charge_out_c) / 2)
        q_charge_kw = mdot_charge_kg_per_s * cp_charge_j_per_kgk * (t_received_in_c - t_charge_out_c) / 1e3

        return (q_delivered_kw, q_bypass_kw, q_discharge_kw, q_received_kw, q_charge_kw, e_stored_kwh, e_usable_kwh,
                mdot_received_kg_per_s, t_received_in_c, t_received_out_c,
                mdot_delivered_kg_per_s, t_demand_in_c, t_delivered_out_c,
                mdot_charge_kg_per_s, t_charge_out_c,
                mdot_discharge_kg_per_s, t_discharge_out_c)

    def _save_state(self):
        """Backup states before Run"""
        self._backup_state = {
            "layer_temps_c": list(self._layer_temps_c),
        }

    def _restore_state(self):
        """Restore states before Rerun"""
        if hasattr(self, "_backup_state"):
            self._layer_temps_c = self._backup_state["layer_temps_c"]

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """

        if not prosumer.rerun:
            self._save_state()
        else:
            self._restore_state()

        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[self.obj.element_index[0]].in_service):
            self.applied = True
            return

        super().control_step(prosumer)

        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        # When discharging, the temperature of the fluid that will be added at the discharge inlet of the storage
        # is the temperature returned by the downstream elements.
        # Simple average of the temperatures but will have to be weighted by the mass flows in the future
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_kg_per_s = self._t_m_demand(prosumer)
        mdot_demand_kg_per_s = sum(mdot_demand_tab_kg_per_s)
        # The discharge temperature is the one of the discharge outlet's layer (the top by default)
        self._resolve_ports(prosumer, self._t_received_in_c, t_demand_in_c, t_demand_out_c)
        t_discharge_out_c = self._layer_temps_c[self._ports[2]]

        assert mdot_demand_kg_per_s >= 0, f"Storage {self.name} mdot_demand_kg_per_s is negative ({mdot_demand_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_demand_out_c >= t_demand_in_c, f"Storage {self.name} t_demand_out_c < t_demand_in_c is negative ({t_demand_out_c} < {t_demand_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_demand_in_c >= 0, f"Storage {self.name} t_demand_in_c is negative ({t_demand_in_c}) for timestep {self.time} in prosumer {prosumer.name}"

        layer_temp_init_c = self._layer_temps_c.copy()
        # Every pass starts from the tank as it is, not from the previous pass's outcome: the discharge is
        # sized on the outlet layer's temperature, and handing a pass the plug-flow outlet temperature the
        # previous one delivered (colder than the top layer when the tank drains over the step) switched the
        # sizing between its mixing and its energy formula every pass (0.01 kg/s then 0.5 kg/s for a 0.05 K
        # change of the return: no fixed point for the return, 9 kW off the balance with the demands)
        t_discharge_out_init_c = t_discharge_out_c

        return_solver = ReturnTemperatureSolver()
        rerun = True
        nb_runs = 0
        while rerun:
            nb_runs += 1
            self._layer_temps_c = layer_temp_init_c.copy()

            (q_delivered_kw, q_bypass_kw, q_discharge_kw, q_received_kw, q_charge_kw, e_stored_kwh, e_usable_kwh,
             mdot_received_kg_per_s, t_received_in_c, t_received_out_c,
             mdot_delivered_kg_per_s, t_demand_in_c, t_delivered_out_c,
             mdot_charge_kg_per_s, t_charge_out_c,
             mdot_discharge_kg_per_s, t_discharge_out_c) = self._calculate_heat_storage(prosumer,
                                                                                        mdot_demand_kg_per_s,
                                                                                        self._t_received_in_c,
                                                                                        t_demand_out_c,
                                                                                        t_demand_in_c,
                                                                                        t_discharge_out_init_c,
                                                                                        self._mdot_received_kg_per_s,
                                                                                        self._t_charge_out)

            # ``dump_on_last`` so a surplus the full tank could not store (see the
            # capacity-capped charge in _calculate_heat_storage) is actually
            # pushed onto the downstream demand, over-serving it (its
            # ``q_uncovered`` goes negative) rather than being silently dropped
            # by the default ``cap`` — which would just move the vanished energy
            # from the source⇄storage boundary to the storage⇄demand boundary. In normal
            # operation ``mdot_delivered ≈ mdot_demand`` so this is a no-op.
            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_delivered_kg_per_s,
                                                                   mdot_demand_tab_kg_per_s,
                                                                   overflow_strategy="dump_on_last")

            rerun = False
            if (len(self._get_mapped_responders(prosumer)) > 1
                    and (abs(mdot_delivered_kg_per_s - mdot_demand_kg_per_s) > 1e-9 or return_solver.started)):
                # If the storage does not deliver the required mass flow (short of it, or dumping a surplus on
                # the last demand), the return of its demands is the mix of what they give back for the flows
                # it delivers, each one returning the same temperature whatever flow it gets: rerun until the
                # return it is calculated with is that mix
                t_return_mixed_c, t_returns_c = self._mixed_return_temperature_c(prosumer, result_mdot_tab_kg_per_s,
                                                                                 t_demand_in_c)
                t_return_next_c = return_solver.next_guess(t_demand_in_c, t_return_mixed_c, t_returns_c)
                if t_return_next_c is not None:
                    if nb_runs >= MAX_RERUN:
                        logger.warning(
                            f"Storage {self.name}: return of its demands not converged after {MAX_RERUN} iterations "
                            f"({t_demand_in_c:.3f} °C calculated, {t_return_mixed_c:.3f} °C given back) at "
                            f"timestep {self.time} in prosumer {prosumer.name}")
                    else:
                        t_demand_in_c = t_return_next_c
                        rerun = True

        self.last_result = {
            "mdot_received_kg_per_s": mdot_received_kg_per_s,
            "t_received_in_c": t_received_in_c,
            "t_received_out_c": t_received_out_c,
            "q_received_kw": q_received_kw,
            "mdot_charge_kg_per_s": mdot_charge_kg_per_s,
            "t_charge_in_c": t_received_in_c,
            "t_charge_out_c": t_charge_out_c,
            "q_charge_kw": q_charge_kw,
            "mdot_discharge_kg_per_s": mdot_discharge_kg_per_s,
            "t_discharge_in_c": t_demand_in_c,
            "t_discharge_out_c": t_discharge_out_c,
            "q_discharge_kw": q_discharge_kw,
            "mdot_delivered_kg_per_s": mdot_delivered_kg_per_s,
            "t_delivered_in_c": t_demand_in_c,
            "t_delivered_out_c": t_delivered_out_c,
            "q_delivered_kw": q_delivered_kw,
            "e_stored_kwh": e_stored_kwh,
            "e_usable_kwh": e_usable_kwh,
        }
        extra_values = self._extra_result_values(prosumer)
        for column, value in zip(self.result_columns[len(self.last_result):], extra_values):
            self.last_result[column] = value
        result = np.array([[mdot_received_kg_per_s, t_received_in_c, t_received_out_c, q_received_kw,
                            mdot_charge_kg_per_s, t_received_in_c, t_charge_out_c, q_charge_kw,
                            mdot_discharge_kg_per_s, t_demand_in_c, t_discharge_out_c, q_discharge_kw,
                            mdot_delivered_kg_per_s, t_demand_in_c, t_delivered_out_c, q_delivered_kw,
                            e_stored_kwh, e_usable_kwh, *extra_values]])

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_delivered_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        self._record_step(t_received_in_c, t_demand_in_c, mdot_charge_kg_per_s, mdot_discharge_kg_per_s)

        # Stagnation detection across reapply iterations within the same
        # timestep: if t_received_out_c has not changed meaningfully across
        # consecutive reapplies, the upstream/storage pair is at an irreconcilable
        # fixed point (e.g. HP wants t_return=58 but the charge outlet is at 64);
        # accepting and proceeding is strictly better than exhausting the
        # outer max_iter budget and raising ControllerNotConverged.
        STAGNATION_TOL_C = 1e-2
        MAX_REAPPLY_STAGNATION_COUNT = 3
        if self._reapply_last_time != self.time:
            # New timestep -- reset stagnation tracking.
            self._reapply_last_time = self.time
            self._reapply_last_t_received_out_c = np.nan
            self._reapply_stagnation_count = 0
        if (not np.isnan(self._reapply_last_t_received_out_c)
                and not np.isnan(t_received_out_c)
                and abs(t_received_out_c - self._reapply_last_t_received_out_c) < STAGNATION_TOL_C):
            self._reapply_stagnation_count += 1
        else:
            self._reapply_stagnation_count = 0
        self._reapply_last_t_received_out_c = t_received_out_c
        stagnated = self._reapply_stagnation_count >= MAX_REAPPLY_STAGNATION_COUNT

        if np.isnan(self.t_keep_return_c) or mdot_received_kg_per_s == 0 or abs(t_received_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0 or stagnated:
            # If the actual output temperature is the same as the promised one, the storage is correctly applied.
            # Also break out when the reapply loop has stagnated -- see comment above. Then the return differs from
            # the promise the sources booked against: say so (EnergyLeakWarning) rather than lose it silently.
            self._check_return_contract(prosumer, t_received_out_c, mdot_received_kg_per_s,
                                        float(self.fluid.get_heat_capacity(
                                            CELSIUS_TO_K + (t_received_out_c + self.t_keep_return_c) / 2)) / 1e3)
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_out_charge_c = np.nan
            self.t_previous_in_charge_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
            self.t_previous_keep_return_c = np.nan
            self.mdot_previous_demand_kg_per_s = np.nan
            self._reapply_last_t_received_out_c = np.nan
            self._reapply_stagnation_count = 0
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            self._layer_temps_c = layer_temp_init_c
            self._unapply_initiators(prosumer)
            self.t_previous_out_charge_c = t_received_out_c
            self.t_previous_in_charge_c = t_received_in_c
            # What the source actually delivered on this pass, and the return
            # it was promised -- anchors the next request (_reapply_request).
            self.mdot_previous_in_kg_per_s = mdot_received_kg_per_s
            self.t_previous_keep_return_c = self.t_keep_return_c
            self.mdot_previous_demand_kg_per_s = mdot_demand_kg_per_s
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
