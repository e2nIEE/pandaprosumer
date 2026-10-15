"""
Module containing the StratifiedHeatStorageController class.
"""

import numpy as np

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.controller.models.shs_ports import (
    HEIGHT_PARAMS, PORTS, auto_discharge_layer, auto_inlet_layer, layer_at_height, mix_inverted_layers,
    parse_auto_ports, plug_order, ports_resolution_in_time,
)

#: The tank is charged AT min_useful_temp_c, so a full tank sits on that threshold and the first wall
#: loss leaves its top a few mK below it. The residual-discharge gate accepts a top layer down to this
#: margin under the threshold, otherwise a full tank refuses to serve exactly when its source falls short.
MIN_USEFUL_MARGIN_K = 0.5
#: Below this charge ΔT (target − bottom layer) the tank is full: it asks its source for no charge.
MIN_CHARGE_DELTA_T_K = 0.5


class StratifiedHeatStorageController(BasicProsumerController):
    """
    Controller for stratified heat storage systems.

    The stratified heat storage is implemented from *Untrau et al., A fast and accurate 1-dimensional model for dynamic
    simulation and optimization of a stratified thermal energy storage, 2023*

    Model a stratified thermal energy storage, which uses one single tank that is charged from the top with hot fluid
    while the cold fluid returning to the storage is charged from the bottom. The model assumes a vertical
    discretization of the tank with layers of uniform temperatures

    When charging with the mapped feed temperature and mass flow, the return temperature is the one on the bottom
    layer of the storage.
    When discharging with the return temperature and mass flow required by the downstream elements, the discharge
    temperature is the one on top of the storage.

    Note that the time step should not be too long compared to the volume of a layer and the (dis)charging mass flow
    so that less than the volume of a layer will be displaced in a time step.

    :param prosumer: The prosumer object
    :param stratified_heat_storage_object: The stratified heat storage object
    :param order: The order of the controller
    :param level: The level of the controller
    :param init_soc: Initial state of charge
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "stratified_heat_storage_controller"

    def __init__(self, prosumer, stratified_heat_storage_object, order, level, init_layer_temps_c=None, plot=False,
                 bypass=True, in_service=True, index=None, name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, stratified_heat_storage_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)

        # Not in the paper nomenclature, is the number of layers
        self.N_l = int(self._get_element_param(prosumer, 'n_layers'))
        t_ext_c = float(self._get_element_param(prosumer, 't_ext_c'))

        if init_layer_temps_c is None:
            self._layer_temps_c = [t_ext_c] * self.N_l
        elif not np.iterable(init_layer_temps_c):
            self._layer_temps_c = [float(init_layer_temps_c)] * self.N_l
        else:
            self._layer_temps_c = list(init_layer_temps_c)
        # warm water under cold water does not last in a tank: an inverted initial profile is what it mixes to
        self._layer_temps_c = [float(t) for t in mix_inverted_layers(np.array(self._layer_temps_c, dtype=float))]

        self.fluid = prosumer.fluid
        # TODO: use thermal conductivity of prosumer.fluid
        k_w_per_mk = self._get_element_param(prosumer, 'k_fluid_w_per_mk')  # 0.598  # water
        self.H_m = self._get_element_param(prosumer, 'tank_height_m')
        r_int_m = self._get_element_param(prosumer, 'tank_internal_radius_m')
        d_insu_m = self._get_element_param(prosumer, 'insulation_thickness_m')
        r_ext_m = self._get_element_param(prosumer, 'tank_external_radius_m')
        self.A_m2 = np.pi * r_int_m ** 2
        perimeter_m = np.pi * r_int_m * 2

        k_insu_w_per_mk = self._get_element_param(prosumer, 'k_insu_w_per_mk')  # 45  # steel
        k_wall_w_per_mk = self._get_element_param(prosumer, 'k_wall_w_per_mk')
        self.k_star_w_per_mk = k_w_per_mk + k_wall_w_per_mk * ((r_ext_m ** 2 - r_int_m ** 2) / r_int_m ** 2)
        h_ext_w_per_m2k = self._get_element_param(prosumer, 'h_ext_w_per_m2k')  # natural convection

        # Heat transfer coefficient with the environment (diffusion through insulation + convection with ambient air)
        if h_ext_w_per_m2k == 0:
            self.U_w_per_m2k = k_insu_w_per_mk / d_insu_m
        else:
            self.U_w_per_m2k = 1 / ((1 / h_ext_w_per_m2k) + (d_insu_m / k_insu_w_per_mk))  # see eq. 6
        # We assume that the tank fluid to overall heat transfer coefficient for the top and bottom layers is the same
        # as the overall heat transfer coefficient
        self.U1_w_per_m2k = self.UN_w_per_m2k = self.U_w_per_m2k

        self.dz_m = self.H_m / self.N_l  # 𝛥z (layer high)
        self._ports = (self.N_l - 1, 0, self.N_l - 1, 0)  # (charge_in, charge_out, discharge_out, discharge_in)

        # Heat exchange areas with the environment: every layer loses through its
        # lateral surface (perimeter · dz); the bottom layer (1) and the top layer
        # (N) additionally through the end disc A, so the tank total is 2A + N·S_lat.
        # (Until 2026-09-09 S1 = Sl = A + S_lat and SN = S_lat: the cross-section
        # was counted on every interior layer and the top disc was missing — with
        # 20 layers the applied UA was ≈ 2× the cylinder's. See
        # tests/models/test_shs_loss_surfaces.py.)
        s_lateral_m2 = perimeter_m * self.dz_m
        self.Sl_m2 = s_lateral_m2                     # interior layers
        self.S1_m2 = self.SN_m2 = self.A_m2 + s_lateral_m2   # bottom / top layers

        # initial temperatures are stored for computing stored energy (see eq. 8 in the paper)
        self.init_layer_temps_c = self._layer_temps_c.copy()

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

        # Stagnation guard for the reapply loop: if the SHS's computed return
        # temperature stays within STAGNATION_TOL_C of its previous value for
        # MAX_REAPPLY_STAGNATION_COUNT consecutive iterations within the same
        # timestep, we've hit a fixed point that the upstream initiator cannot
        # reconcile (the SHS bottom-layer temp is incompatible with the
        # initiator's expected t_keep_return_c). Accept and proceed rather
        # than reapplying forever and timing out the outer max_iter budget.
        self._reapply_last_t_received_out_c = np.nan
        self._reapply_stagnation_count = 0
        self._reapply_last_time = None

        # Used for debugging
        self.plot = plot
        self.bypass = bypass
        if self.plot:
            self._layer_temps_tab_c = []
            self.t_charge_tab_c = []
            self.t_discharge_tab_c = []
            self.mdot_charge_tab_kg_per_s = []
            self.mdot_discharge_tab_kg_per_s = []

    def _effective_max_dt_s(self, prosumer,
                            mdot_charge_kg_per_s,
                            mdot_discharge_kg_per_s,
                            rho_kg_per_m3=None):
        """Return the per-substep time-step used by the TVD solver.

        - numeric -> use the pinned value unchanged.
        - ``None`` / ``NaN`` (legacy default) -> use ``self.resol`` (no
          sub-stepping). Preserves the historic behaviour of every test
          that relied on the default.

        ``mdot_charge_kg_per_s``, ``mdot_discharge_kg_per_s`` and
        ``rho_kg_per_m3`` are accepted for forward-compatibility with a
        future CFL-based auto-derivation; today they are unused.
        """
        user_max_dt = self._get_element_param(prosumer, 'max_dt_s')
        if user_max_dt is None or (isinstance(user_max_dt, float) and np.isnan(user_max_dt)):
            return float(self.resol)
        return float(user_max_dt)

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
        remaining_capacity_kwh = (self._get_max_stored_energy_kwh(t_ref_c, t_charge_c)
                                  - self._get_stored_energy_kwh(t_ref_c))
        return bool(mdot_demand_kg_per_s > 0
                    and remaining_capacity_kwh < self._get_element_param(prosumer, "max_remaining_capacity_kwh"))

    def _residual_discharge_mdot(self, prosumer, e_residual_kgk, t_discharge_out_c, t_demand_in_c):
        """
        Discharge mass flow that carries the residual demand energy ``e_residual_kgk`` (in kg/s·K, i.e.
        mdot·ΔT) at the top-layer temperature, or 0 when the tank is spent.

        Gate on min_useful_temp_c: once the top layer has fallen below the minimum usable temperature
        (minus ``MIN_USEFUL_MARGIN_K``) the tank is SPENT — the demand goes (honestly) uncovered. Without this gate the divisor
        (t_discharge_out − t_demand_in) → 0 as the tank drains toward the return temperature and the mass
        flow explodes, blowing up the TVD layer solver ("SHS model has diverged" with a negative layer).
        The flow never carries more over the step than the energy stored above ``t_demand_in_c``.
        """
        t_min_useful_c = self._get_element_param(prosumer, 'min_useful_temp_c')
        if t_min_useful_c is None or np.isnan(t_min_useful_c):
            t_min_useful_c = t_demand_in_c + 1.0  # ≥1 K usable ΔT floor
        if t_discharge_out_c >= t_min_useful_c - MIN_USEFUL_MARGIN_K and t_discharge_out_c - t_demand_in_c > 0.5:
            mdot_kg_per_s = max(0.0, e_residual_kgk / (t_discharge_out_c - t_demand_in_c))
            # The flow is sized on the top layer's temperature for the whole step: a nearly spent tank (a
            # thin hot top over cold water) would deliver more than it stores. Cap it at the energy stored
            # above the demand return, spread over the step.
            order = self._discharge_order()
            stored_kgk = float(np.sum(self._layer_masses_kg()[order]
                                      * np.maximum(0.0, np.asarray(self._layer_temps_c, dtype=float)[order] - t_demand_in_c)))
            return min(mdot_kg_per_s, stored_kgk / (self.resol * (t_discharge_out_c - t_demand_in_c)))
        return 0.0

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
        - discharge setpoint: clamped to zero when the top layer is not warmer than the return; a free
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
            mdot_discharge_kg_per_s = mdot_discharge_setpoint_kg_per_s if delta_t_discharge_c > 0.5 else 0.0

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

    def _resolve_ports(self, prosumer, t_charge_c, t_return_c, t_feed_c):
        """
        The layers of the four connections for this step, ``(charge_in, charge_out, discharge_out,
        discharge_in)`` (see ``shs_ports``): a fixed height, the tank's end by default, or placed on the
        current layers for the ports in ``auto_ports`` (an inflow at the layer of its own temperature, the
        discharge at the lowest layer still at the demand's feed, the return to the source at the coldest).
        Kept in ``self._ports`` for the plug-flow helpers and the layer solver.
        """
        n = self.N_l
        defaults = {"charge_in": n - 1, "charge_out": 0, "discharge_out": n - 1, "discharge_in": 0}
        layers = {port: layer_at_height(self._get_element_param(prosumer, HEIGHT_PARAMS[port]), n, self.dz_m, default)
                  for port, default in defaults.items()}
        auto = parse_auto_ports(self._get_element_param(prosumer, 'auto_ports'))
        temps_c = self._layer_temps_c
        if "charge_in" in auto and not np.isnan(t_charge_c):
            layers["charge_in"] = auto_inlet_layer(temps_c, t_charge_c)
        if "discharge_in" in auto and not np.isnan(t_return_c):
            layers["discharge_in"] = auto_inlet_layer(temps_c, t_return_c)
        if "discharge_out" in auto and not np.isnan(t_feed_c):
            layers["discharge_out"] = auto_discharge_layer(temps_c, t_feed_c)
        if "charge_out" in auto:
            layers["charge_out"] = int(np.argmin(np.asarray(temps_c, dtype=float)))
        self._ports = tuple(layers[port] for port in PORTS)
        return self._ports

    def _charge_order(self):
        """Layers in the order a charge pushes them out (from its outlet towards its inlet)."""
        charge_in, charge_out, _, _ = self._ports
        return plug_order(self.N_l, charge_out, charge_in)

    def _discharge_order(self):
        """Layers in the order a discharge draws them (from its outlet towards the return inlet)."""
        _, _, discharge_out, discharge_in = self._ports
        return plug_order(self.N_l, discharge_out, discharge_in)

    def _layer_masses_kg(self):
        """Mass of each layer (kg), bottom first."""
        temps_k = CELSIUS_TO_K + np.asarray(self._layer_temps_c, dtype=float)
        return np.asarray(self.fluid.get_density(temps_k), dtype=float) * self.A_m2 * self.dz_m

    def _charge_mdot_to_fill(self, t_charge_in_c):
        """
        Charge mass flow (kg/s) that pushes out, over one step, every bottom layer still more than
        ``MIN_CHARGE_DELTA_T_K`` under ``t_charge_in_c`` (plug flow from the top). Layers within that margin
        are full: counting them asked a full tank (layers a few mK under the target) for a whole tank volume
        per step, which the source delivered and the tank could not hold.
        """
        order = self._charge_order()
        cold = np.flatnonzero(np.asarray(self._layer_temps_c, dtype=float)[order] < t_charge_in_c - MIN_CHARGE_DELTA_T_K)
        if cold.size == 0:
            return 0.0
        return float(self._layer_masses_kg()[order][:cold[-1] + 1].sum()) / self.resol

    def _plug_flow_outlet_c(self, mass_kg, from_top, t_inflow_c):
        """
        Mean temperature (°C) of ``mass_kg`` of water leaving the tank over a step, plug flow: the bottom
        layers for the charge return (``from_top=False``), the top layers for the discharge. Beyond the
        tank's mass the inflow (``t_inflow_c``) passes straight through. The bottom / top layer alone is only
        right for a step that moves a fraction of a layer: a step that fills the tank returns warmer water,
        one that drains it delivers colder water.
        """
        order = self._discharge_order() if from_top else self._charge_order()
        temps_c = list(np.asarray(self._layer_temps_c, dtype=float)[order])
        masses_kg = list(self._layer_masses_kg()[order])
        if mass_kg <= 0:
            return float(temps_c[0])
        left_kg, heat_kgk = mass_kg, 0.0
        for t_c, m_kg in zip(temps_c, masses_kg):
            taken_kg = min(m_kg, left_kg)
            heat_kgk += taken_kg * t_c
            left_kg -= taken_kg
            if left_kg <= 0:
                break
        heat_kgk += max(0.0, left_kg) * t_inflow_c
        return heat_kgk / mass_kg

    def _plug_flow_discharge_mass_kg(self, heat_kgk, t_return_c):
        """
        Mass (kg) a discharge must draw from the top over a step to deliver ``heat_kgk`` (kg·K, i.e.
        energy / cp) above ``t_return_c``, plug flow: the inverse of ``_plug_flow_outlet_c`` on the discharge
        side. A tank holding less delivers what it holds (the whole tank's mass at most).
        """
        order = self._discharge_order()
        temps_c = np.asarray(self._layer_temps_c, dtype=float)[order]
        masses_kg = self._layer_masses_kg()[order]
        left_kgk, mass_kg = heat_kgk, 0.0
        for t_c, m_kg in zip(temps_c, masses_kg):
            if left_kgk <= 0:
                break
            gain_kgk_per_kg = t_c - t_return_c
            if gain_kgk_per_kg <= 0:
                break  # colder than the return: the rest of the tank holds nothing usable
            taken_kg = min(m_kg, left_kgk / gain_kgk_per_kg)
            mass_kg += taken_kg
            left_kgk -= taken_kg * gain_kgk_per_kg
        return mass_kg

    def _plug_flow_charge_mass_kg(self, heat_kgk, t_charge_in_c):
        """
        Mass (kg) a charge at ``t_charge_in_c`` pushes out of its outlet over a step to store ``heat_kgk``
        (kg·K, i.e. energy / cp), plug flow: the inverse of ``_plug_flow_outlet_c`` on the charge side.
        Beyond what the tank can still take, the rest of the stream passes through at the charge temperature
        and stores nothing, so the mass is capped at the tank's.
        """
        order = self._charge_order()
        left_kgk, mass_kg = heat_kgk, 0.0
        for t_c, m_kg in zip(np.asarray(self._layer_temps_c, dtype=float)[order], self._layer_masses_kg()[order]):
            gain_kgk_per_kg = t_charge_in_c - t_c
            if left_kgk <= 0:
                break
            if gain_kgk_per_kg <= 0:
                mass_kg += m_kg
                continue
            taken_kg = min(m_kg, left_kgk / gain_kgk_per_kg)
            mass_kg += taken_kg
            left_kgk -= taken_kg * gain_kgk_per_kg
        return mass_kg

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_demand_kg_per_s = np.sum(mdot_demand_tab_required_kg_per_s)
        t_charge_in_c = self._get_element_param(prosumer, 'min_useful_temp_c')  # self._layer_temps_c[-1]

        # External dispatch setpoints (NaN = none). They must shape the REQUEST
        # exactly as they shape the split in _calculate_heat_storage, otherwise
        # the source is asked for a flow the storage then dispatches differently
        # and the reapply loop can only stagnate on an inconsistent state.
        mdot_charge_setpoint_kg_per_s = self._get_setpoint(prosumer, 'mdot_charge_setpoint_kg_per_s')
        mdot_discharge_setpoint_kg_per_s = self._get_setpoint(prosumer, 'mdot_discharge_setpoint_kg_per_s')
        self._resolve_ports(prosumer, t_charge_in_c, t_demand_in_c, t_demand_out_c)

        # Share of the demand the bypass has to serve: all of it, unless a forced
        # discharge already carries part of the demand energy from the top layer.
        mdot_bypass_demand_kg_per_s = mdot_demand_kg_per_s
        if not np.isnan(mdot_discharge_setpoint_kg_per_s):
            delta_t_discharge_c = self._layer_temps_c[self._ports[2]] - t_demand_in_c
            e_demand_kgk = mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c)
            if delta_t_discharge_c > 0.5 and e_demand_kgk > 0:
                e_residual_kgk = max(0.0, e_demand_kgk - mdot_discharge_setpoint_kg_per_s * delta_t_discharge_c)
                mdot_bypass_demand_kg_per_s = mdot_demand_kg_per_s * e_residual_kgk / e_demand_kgk
        # If the required feed downstream temperature is null, it means that there is no downstream mapped controller
        # so ask treturn_required_c charge the storage at the min_useful_temp_c (or current top layer temperature ?)
        if t_demand_out_c < 1e-6 or mdot_demand_kg_per_s < 1e-6:
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
            return t_demand_out_c, t_demand_in_c, mdot_bypass_demand_kg_per_s

        if not np.isnan(mdot_charge_setpoint_kg_per_s):
            # Forced charge: ask upstream for exactly that (the cap below still applies).
            mdot_charge_kg_per_s = mdot_charge_setpoint_kg_per_s
        else:
            mdot_charge_kg_per_s = self._charge_mdot_to_fill(t_required_in_c)

        # Optional cap so the SHS doesn't ask the upstream producer for more
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

        t_charge_out_c = self._plug_flow_outlet_c(mdot_charge_kg_per_s * self.resol, False, t_required_in_c)
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
                                                           (t_required_in_c, t_required_out_c, mdot_required_kg_per_s))
            # The bypass share of the demand (all of it unless a forced discharge carries part of it).
            return self._reapply_request(prosumer, t_demand_out_c, t_demand_in_c, mdot_bypass_demand_kg_per_s,
                                         t_charge_out_c,
                                         (t_required_in_c, t_required_out_c, mdot_required_kg_per_s))

        return t_required_in_c, t_required_out_c, mdot_required_kg_per_s

    def _forced_charge_reapply_request(self, mdot_charge_setpoint_kg_per_s, forward_request):
        """
        Reapply request of a forced charge the source could not deliver in full: ``_apply_setpoints`` puts
        what arrives into the tank first (up to the setpoint), so all the energy the source delivered charges
        it. Request the mass that energy pushes out of the bottom (plug flow), at its mean temperature.
        """
        t_in_c = self.t_previous_in_charge_c
        t_keep_prev_c = self.t_previous_keep_return_c
        mdot_prev_kg_per_s = self.mdot_previous_in_kg_per_s
        if np.isnan(t_in_c) or np.isnan(t_keep_prev_c) or not mdot_prev_kg_per_s > 0 or t_in_c - t_keep_prev_c <= 1e-9:
            return forward_request
        heat_kgk = mdot_prev_kg_per_s * (t_in_c - t_keep_prev_c) * self.resol
        mass_kg = min(self._plug_flow_charge_mass_kg(heat_kgk, t_in_c),
                      mdot_charge_setpoint_kg_per_s * self.resol)
        if mass_kg <= 0:
            return forward_request
        return t_in_c, self._plug_flow_outlet_c(mass_kg, False, t_in_c), mass_kg / self.resol

    def _reapply_request(self, prosumer, t_demand_out_c, t_demand_in_c, mdot_demand_kg_per_s,
                         t_charge_out_c, forward_request):
        """
        Request to send upstream on a REAPPLY pass of the convergence loop.

        The source (HP condenser, HX, ...) delivered ``mdot_previous_in_kg_per_s``
        at ``t_previous_in_charge_c`` on the previous pass, heating it from the
        return it was promised (``t_previous_keep_return_c``); the SHS then split
        that stream (demand bypass first, remainder to charge) and found the
        actual mixed return ``t_previous_out_charge_c`` differed from the promise.

        A source that under-delivered was LIMITED (power / mass-flow cap) and keeps
        its feed temperature while shrinking the mass flow when the return it is
        promised gets colder. Re-requesting the forward charge mass flow at the
        colder actual return (the historical behaviour) therefore makes it deliver
        even less mass, the SHS -- which gives the bypass priority -- loses charge
        share, the mass-weighted return drops again, and so on: a fixed-point
        iteration whose contraction factor tends to 1 as the bottom layer approaches
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
        remaining_capacity_kwh = (self._get_max_stored_energy_kwh(t_charge_ref_in_c, t_in_c)
                                  - self._get_stored_energy_kwh(t_charge_ref_in_c))
        tank_full = remaining_capacity_kwh < self._get_element_param(prosumer, "max_remaining_capacity_kwh")

        if q_prev_w >= q_bypass_full_w and not (tank_full and mdot_demand_kg_per_s > 0):
            # Source covers the demand bypass; the surplus energy charges the tank. The charge mass and its
            # return come from the same plug flow the split will book (the return depends on the mass).
            mdot_bypass_kg_per_s = mdot_bypass_full_kg_per_s
            cp_charge_j_per_kgk = float(self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_in_c + t_charge_out_c) / 2))
            heat_kgk = max(0.0, q_prev_w - q_bypass_full_w) * self.resol / cp_charge_j_per_kgk
            mass_kg = self._plug_flow_charge_mass_kg(heat_kgk, t_in_c)
            if mdot_demand_kg_per_s > 0:
                # The split sends what the tank cannot take within the step to the demand
                mass_kg = min(mass_kg, self._charge_mdot_to_fill(t_in_c) * self.resol)
            mdot_charge_kg_per_s = mass_kg / self.resol
            t_charge_out_c = self._plug_flow_outlet_c(mass_kg, False, t_in_c)
            stored_kgk = mass_kg * (t_in_c - t_charge_out_c)
            if mdot_demand_kg_per_s > 0 and heat_kgk - stored_kgk > 1e-9 and delta_t_bypass_c > 1e-9:
                mdot_bypass_kg_per_s += (heat_kgk - stored_kgk) / self.resol / delta_t_bypass_c
        else:
            # Source cannot even cover the bypass (the SHS will discharge the
            # rest), or the tank is full (whole stream bypassed): no charge, the
            # delivered energy goes to the demand.
            mdot_charge_kg_per_s = 0.0
            if delta_t_bypass_c > 1e-9:
                mdot_bypass_kg_per_s = q_prev_w / (cp_bypass_j_per_kgk * delta_t_bypass_c)
            else:
                mdot_bypass_kg_per_s = 0.0

        mdot_required_kg_per_s = mdot_bypass_kg_per_s + mdot_charge_kg_per_s
        if mdot_required_kg_per_s > 1e-12:
            t_required_out_c = (mdot_charge_kg_per_s * t_charge_out_c
                                + mdot_bypass_kg_per_s * t_demand_in_c) / mdot_required_kg_per_s
        else:
            t_required_out_c = t_in_c
        return t_in_c, t_required_out_c, mdot_required_kg_per_s

    @property
    def _t_charge_out(self):
        """
        Temperature of the fluid returned to the initiator in °C (the charge outlet's layer)
        """
        return self._layer_temps_c[self._ports[1]]

    def _get_max_stored_energy_kwh(self, extraction_temp_c, t_charge_c):
        """
        Maximal storable energy E if charging at the temperature temp_charge_c.
        Calculated by comparing a case with uniform temperature to the initial state. See equation (8) in the paper

        :param extraction_temp_c: Useful Extraction temperature (only energy above this level is considered) (°C)
        :param t_charge_c: Temperature charge (°C)
        :return: Maximum storable energy E (kWh)
        """
        # 3.6e6 is the conversion factor from J to kWh
        ret = sum([float(self.fluid.get_density(CELSIUS_TO_K + t_charge_c)) * self.A_m2 *
                   float(self.fluid.get_heat_capacity(CELSIUS_TO_K + t_charge_c)) *
                   (t_charge_c - self.init_layer_temps_c[z]) * self.dz_m
                   for z in range(self.N_l) if t_charge_c >= extraction_temp_c - .1]) / 3.6e6
        return ret

    def _get_stored_energy_kwh(self, t_extraction_c):
        """
        Stored energy E(t) at any time
        Calculated by comparing current temperatures to the initial state. See equation (8) in the paper

        :param t_extraction_c: Useful Extraction temperature (only energy above this level is considered) (°C)
        :type t_extraction_c: float
        :return: Stored energy E(t) compared to initial state (kWh)
        """
        # 3.6e6 is the conversion factor from J to kWh
        temps_c = np.asarray(self._layer_temps_c, dtype=float)
        temps_k = CELSIUS_TO_K + temps_c
        per_layer_j = (np.asarray(self.fluid.get_density(temps_k)) * self.A_m2 * np.asarray(self.fluid.get_heat_capacity(temps_k))
                       * (temps_c - np.asarray(self.init_layer_temps_c, dtype=float)) * self.dz_m)
        ret = float(np.sum(per_layer_j[temps_c >= t_extraction_c - .1])) / 3.6e6
        return ret

    def _calculate_heat_storage(self, prosumer, mdot_demand_kg_per_s, t_received_in_c, t_demand_out_c, t_demand_in_c,
                                t_discharge_out_c, mdot_received_kg_per_s, t_charge_out_c):

        # NaN-to-zero guard at the contract boundary. ``_t_received_in_c`` and
        # ``_mdot_received_kg_per_s`` are NaN whenever the upstream FluidMix
        # initiator is off (e.g. HP_ON=0 from the optimiser). A NaN here
        # signals "no flow contract", not "unknown value": physically the
        # side carries no enthalpy and the temperature is irrelevant. Treat
        # as zero so the bypass branch and the TVD solver downstream see
        # clean values. The ``0 * NaN == NaN`` propagation in IEEE 754 would
        # otherwise corrupt every layer of ``_layer_temps_c`` within a single
        # sub-step. See ``tests/integrations/test_shs_nan_propagation.py``.
        if np.isnan(mdot_received_kg_per_s):
            mdot_received_kg_per_s = 0.0
        if np.isnan(t_received_in_c):
            assert mdot_received_kg_per_s == 0, (
                f"SHS {self.name}: t_received_in_c is NaN but "
                f"mdot_received_kg_per_s is non-zero ({mdot_received_kg_per_s}) "
                f"-- upstream initiator contract violation at timestep {self.time}."
            )
            t_received_in_c = float(self._layer_temps_c[-1])
        if np.isnan(t_demand_in_c):
            assert mdot_demand_kg_per_s == 0, (
                f"SHS {self.name}: t_demand_in_c is NaN but "
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
                # mdot_discharge_kg_per_s = sum(mdot_demand_tab_kg_per_s) - mdot_bypass_kg_per_s
                # If the required output temperature is between the feed and top layer temperature, calculate the
                # discharge mass flow to get this required temperature
                if abs(t_demand_out_c - t_discharge_out_c) > self._get_element_param(prosumer, "t_discharge_out_tol_c"):
                    mdot_discharge_kg_per_s = mdot_bypass_kg_per_s * (t_received_in_c - t_demand_out_c) / (
                            t_demand_out_c - t_discharge_out_c)
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
                    # the top-layer temperature with the mass flow that carries
                    # the demanded energy (considering that the return
                    # temperature would be the same).
                    #
                    # Gate on min_useful_temp_c: once the top layer has fallen
                    # below the minimum usable temperature the tank is SPENT —
                    # the demand goes (honestly) uncovered. Without this gate
                    # the divisor (t_discharge_out − t_demand_in) → 0 as the
                    # tank drains toward the return temperature and the mass
                    # flow explodes, blowing up the TVD layer solver ("SHS
                    # model has diverged" with a negative layer).
                    # (Tank spent — top below the usable threshold — gives no
                    # discharge; the demand reports q_uncovered instead.)
                    e_demand = mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c)
                    e_bypass = mdot_bypass_kg_per_s * (t_received_in_c - t_demand_in_c)  # iso-energy, as in _apply_setpoints
                    mdot_discharge_kg_per_s = self._residual_discharge_mdot(prosumer, e_demand - e_bypass,
                                                                            t_discharge_out_c, t_demand_in_c)
            else:
                # Enough (or more than enough) received to serve the demand by
                # bypass; the surplus (mdot_received − mdot_toprovide) would
                # charge the tank. But if the tank is FULL it cannot store that
                # surplus: charging it anyway drives the SHS's recomputed return
                # up toward the bottom-layer temperature while the source was
                # handed (and delivered against) the demand-return contract
                # ``t_keep_return_c``. The two returns then diverge, the reapply
                # loop can only stagnate, the source's return contract creeps
                # toward the feed so a power-limited source (HP at min_p_comp)
                # explodes its mass flow at the vanishing ΔT, and hundreds of kW
                # silently vanish (source books its full duty, SHS books only what
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
                    # with feed ≈ bottom stores ≈0 energy and returns q ≈ 0
                    # (rather than fabricating a bypass to a nonexistent demand
                    # at t_demand_in = 0).
                    mdot_charge_kg_per_s = 0.0
                    mdot_bypass_kg_per_s = mdot_received_kg_per_s
                else:
                    mdot_bypass_kg_per_s = mdot_toprovide_kg_per_s
                    mdot_charge_kg_per_s = mdot_received_kg_per_s - mdot_bypass_kg_per_s
                mdot_discharge_kg_per_s = 0
                t_bypass_in_c = t_received_in_c

            #     for i, m in enumerate(mdot_demand_tab_kg_per_s):
            #         if (t_discharge_c - t_return_demand_c) > 0:
            #             # Compensate the value of mass flow to provide the same energy
            #             # Because the discharge temperature is the one on the extraction layer
            #             # which can be different from the required feed temperature
            #             # FixMe: Take into account the temperature that will go through the storage from the production
            #             mdot_demand_tab_kg_per_s[i] = m * (t_feed_demand_c - t_return_demand_c) / (t_discharge_c - t_return_demand_c)
            #         else:
            #             # If the temperature in the storage is lower than the return temperature, it cannot provide any power
            #             mdot_demand_tab_kg_per_s[i] = 0
            #
            # mdot_discharge_kg_per_s = np.sum(mdot_demand_tab_kg_per_s)

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

        # FixMe: the feature of loading at intermediate layer is not working anymore with the TVD scheme
        height_charge_in_m = self._get_element_param(prosumer, 'height_charge_in_m')
        height_charge_out_m = self._get_element_param(prosumer, 'height_charge_out_m')
        height_discharge_out_m = self._get_element_param(prosumer, 'height_discharge_out_m')
        height_discharge_in_m = self._get_element_param(prosumer, 'height_discharge_in_m')
        layer_charge_in = height_charge_in_m / self.H_m * self.N_l if not np.isnan(height_charge_in_m) else None
        layer_charge_out = height_charge_out_m / self.H_m * self.N_l if not np.isnan(height_charge_out_m) else None
        layer_discharge_out = height_discharge_out_m / self.H_m * self.N_l if not np.isnan(height_discharge_out_m) else None
        layer_discharge_in = height_discharge_in_m / self.H_m * self.N_l if not np.isnan(height_discharge_in_m) else None

        cp_discharge_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + np.mean(self._layer_temps_c))
        rho_kg_per_m3 = self.fluid.get_density(CELSIUS_TO_K + np.mean(self._layer_temps_c))
        t_ext_c = self._get_element_param(prosumer, 't_ext_c')

        max_dt_s = self._effective_max_dt_s(prosumer,
                                            mdot_charge_kg_per_s,
                                            mdot_discharge_kg_per_s,
                                            rho_kg_per_m3)

        # Secondary NaN guard: ``mdot_charge_kg_per_s`` / ``mdot_discharge_kg_per_s``
        # are derived above from the (now NaN-cleaned) received/demand values, so
        # they should already be finite. Defend against a future refactor of the
        # bypass arithmetic introducing a fresh NaN path -- a NaN mdot reaching
        # the @njit TVD solver would corrupt every layer silently.
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

        # What leaves the tank over the step (plug flow from the start-of-step layers), not the bottom / top
        # layer alone: the return the source gets and the heat the demand gets
        t_charge_out_c = self._plug_flow_outlet_c(mdot_charge_kg_per_s * self.resol, False, t_received_in_c)
        mdot_charge_tank_kg_per_s = mdot_charge_kg_per_s
        if mdot_charge_kg_per_s > 0 and t_charge_out_c >= t_received_in_c:
            # A charge no warmer than the water it would push out only cools the tank (a top-entering
            # stream colder than the stratification): it passes by, back to the source, without exchange.
            # ToDo: enter at the layer of its own temperature (charge inlet height)
            mdot_charge_tank_kg_per_s = 0.0
            t_charge_out_c = t_received_in_c
        if mdot_discharge_kg_per_s > 0:
            # The split sized the discharge on the top layer; the plug flow draws the layers below it, warmer
            # in an inverted tank, colder when draining. Keep the energy the split sized, draw the mass that
            # carries it (or what the tank holds), so the demand gets neither more nor less than planned.
            heat_kgk = mdot_discharge_kg_per_s * self.resol * max(0.0, t_discharge_out_c - t_demand_in_c)
            mass_kg = self._plug_flow_discharge_mass_kg(heat_kgk, t_demand_in_c)
            mdot_discharge_kg_per_s = mass_kg / self.resol
            if mass_kg > 0:
                t_discharge_out_c = self._plug_flow_outlet_c(mass_kg, True, t_demand_in_c)

        charge_in, charge_out, discharge_out, discharge_in = self._ports
        self._layer_temps_c = ports_resolution_in_time(np.array(self._layer_temps_c, dtype=float),
                                                       charge_in, charge_out, discharge_out, discharge_in,
                                                       mdot_charge_tank_kg_per_s, t_received_in_c,
                                                       mdot_discharge_kg_per_s, t_demand_in_c,
                                                       t_ext_c, cp_discharge_j_per_kgk, rho_kg_per_m3,
                                                       self.A_m2, self.dz_m, self.Sl_m2, self.S1_m2, self.SN_m2,
                                                       self.k_star_w_per_mk, self.U_w_per_m2k, self.U1_w_per_m2k,
                                                       self.UN_w_per_m2k, self.resol, max_dt_s)

        assert (self._layer_temps_c > 0).all(), (f"The SHS model has diverged - "
                                                 f"Negative temperature in the storage for "
                                                 f"timestep {self.time} layers= {self._layer_temps_c}")

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

        # When discharging, the temperature of the fluid that will be added at the bottom of the storage is the
        # temperature returned by the downstream elements.
        # Simple average of the temperatures but will have to be weighted by the mass flows in the future
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_demand_kg_per_s = sum(mdot_demand_tab_kg_per_s)
        # The discharge temperature is the one of the discharge outlet's layer (the top by default)
        self._resolve_ports(prosumer, self._t_received_in_c, t_demand_in_c, t_demand_out_c)
        t_discharge_out_c = self._layer_temps_c[self._ports[2]]

        assert mdot_demand_kg_per_s >= 0, f"SHS {self.name} mdot_demand_kg_per_s is negative ({mdot_demand_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_demand_out_c >= t_demand_in_c, f"SHS {self.name} t_demand_out_c < t_demand_in_c is negative ({t_demand_out_c} < {t_demand_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_demand_in_c >= 0, f"SHS {self.name} t_demand_in_c is negative ({t_demand_in_c}) for timestep {self.time} in prosumer {prosumer.name}"

        layer_temp_init_c = self._layer_temps_c.copy()

        rerun = True
        while rerun:
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
                                                                                        t_discharge_out_c,
                                                                                        self._mdot_received_kg_per_s,
                                                                                        self._t_charge_out)

            # ``dump_on_last`` so a surplus the full tank could not store (see the
            # capacity-capped charge in _calculate_heat_storage) is actually
            # pushed onto the downstream demand, over-serving it (its
            # ``q_uncovered`` goes negative) rather than being silently dropped
            # by the default ``cap`` — which would just move the vanished energy
            # from the source⇄SHS boundary to the SHS⇄demand boundary. In normal
            # operation ``mdot_delivered ≈ mdot_demand`` so this is a no-op.
            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_delivered_kg_per_s,
                                                                   mdot_demand_tab_kg_per_s,
                                                                   overflow_strategy="dump_on_last")

            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_delivered_kg_per_s < mdot_demand_kg_per_s:
                # If the heat Pump is not able to deliver the required mass flow,
                # recalculate the condenser input temperature, considering that all the downstream elements will be
                # still return the same temperature, even if the mass flow delivered to them by the Heat Pump is lower
                t_return_tab_c = self.get_treturn_tab_c(prosumer)
                if abs(mdot_delivered_kg_per_s) > 1e-8:
                    t_return_demand_new_c = np.sum(result_mdot_tab_kg_per_s * t_return_tab_c) / mdot_delivered_kg_per_s
                else:
                    t_return_demand_new_c = t_demand_in_c
                if abs(t_return_demand_new_c - t_demand_in_c) > 1:
                    # If this recalculation changes the condenser input temperature, rerun the calculation
                    # with the new temperature
                    t_demand_in_c = t_return_demand_new_c
                    rerun = True

        result = np.array([[mdot_received_kg_per_s, t_received_in_c, t_received_out_c, q_received_kw,
                            mdot_charge_kg_per_s, t_received_in_c, t_charge_out_c, q_charge_kw,
                            mdot_discharge_kg_per_s, t_demand_in_c, t_discharge_out_c, q_discharge_kw,
                            mdot_delivered_kg_per_s, t_demand_in_c, t_delivered_out_c, q_delivered_kw,
                            e_stored_kwh, e_usable_kwh]])

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

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_delivered_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        # Used for debugging
        if self.plot:
            self._layer_temps_tab_c += [self._layer_temps_c]  # Store all the layers temps history for analysis
            self.t_charge_tab_c += [t_received_in_c]
            self.t_discharge_tab_c += [t_demand_in_c]
            self.mdot_charge_tab_kg_per_s += [mdot_charge_kg_per_s]
            self.mdot_discharge_tab_kg_per_s += [mdot_discharge_kg_per_s]

        # assert q_received_kw >= 0, f"SHS {self.name} q_received_kw is negative ({q_received_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        # assert q_delivered_kw >= 0, f"SHS {self.name} q_delivered_kw is negative ({q_delivered_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        # assert q_charge_kw >= 0, f"SHS {self.name} q_charge_kw is negative ({q_charge_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        # assert q_discharge_kw >= 0, f"SHS {self.name} q_discharge_kw is negative ({q_discharge_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        # assert e_stored_kwh >= 0, f"SHS {self.name} e_stored_kwh is negative ({e_stored_kwh}) for timestep {self.time} in prosumer {prosumer.name}"
        # assert mdot_received_kg_per_s >= 0, f"SHS {self.name} mdot_received_kg_per_s is negative ({mdot_received_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        # assert mdot_delivered_kg_per_s >= 0, f"SHS {self.name} mdot_delivered_kg_per_s is negative ({mdot_delivered_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"

        # Stagnation detection across reapply iterations within the same
        # timestep: if t_received_out_c has not changed meaningfully across
        # consecutive reapplies, the upstream/SHS pair is at an irreconcilable
        # fixed point (e.g. HP wants t_return=58 but SHS bottom layer is 64);
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
