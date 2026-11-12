"""
Module containing the UniformHeatStorageController class.
"""

import numpy as np

from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.models.fluid_mix_heat_storage import (
    MIN_CHARGE_DELTA_T_K, FluidMixHeatStorageController,
)

#: Iterations of the bisections that size a flow from the heat it carries (precision 2**-60 of the bracket)
_BISECTION_ITER = 60


def mixed_tank_step(t_start_c, mass_kg, inflows, ua_kg_per_s, t_ext_c, dt_s):
    """
    Exact solution of a fully mixed tank over a step with constant inflows.

    Each inflow ``(mdot_kg_per_s, t_c)`` enters the tank and the same mass flow leaves it at the tank
    temperature; the wall loses ``UA · (T − t_ext)``. With ``ua_kg_per_s = UA / cp`` the tank temperature
    follows the linear ODE

        M · dT/dt = Σ mdot_i · (t_i − T) + ua · (t_ext − T)

    whose solution relaxes exponentially towards the mixing temperature
    ``T_inf = (Σ mdot_i · t_i + ua · t_ext) / (Σ mdot_i + ua)`` with the rate ``b = (Σ mdot_i + ua) / M``.
    Every outflow leaves at the tank temperature, so over the step it carries the time-mean temperature.
    The energy balance ``M · (T_end − T_start) = dt · [Σ mdot_i · (t_i − T_mean) + ua · (t_ext − T_mean)]``
    holds exactly, for any step length (no stability limit).

    :param t_start_c: Tank temperature at the start of the step (°C)
    :param mass_kg: Mass of water in the tank (kg)
    :param inflows: Iterable of ``(mdot_kg_per_s, t_c)``
    :param ua_kg_per_s: Wall heat-loss coefficient divided by the heat capacity, UA / cp (kg/s)
    :param t_ext_c: Ambient temperature (°C)
    :param dt_s: Step length (s)
    :return: ``(t_end_c, t_mean_c)``: tank temperature at the end of the step and its mean over the step
    """
    flow_kg_per_s = ua_kg_per_s
    flow_t_kgk_per_s = ua_kg_per_s * t_ext_c
    for mdot_kg_per_s, t_c in inflows:
        if mdot_kg_per_s > 0:
            flow_kg_per_s += mdot_kg_per_s
            flow_t_kgk_per_s += mdot_kg_per_s * t_c
    x = flow_kg_per_s * dt_s / mass_kg
    if x <= 1e-15:
        return t_start_c, t_start_c
    t_inf_c = flow_t_kgk_per_s / flow_kg_per_s
    t_end_c = t_inf_c + (t_start_c - t_inf_c) * np.exp(-x)
    t_mean_c = t_inf_c + (t_start_c - t_inf_c) * (-np.expm1(-x)) / x
    return float(t_end_c), float(t_mean_c)


class UniformHeatStorageController(FluidMixHeatStorageController):
    """
    Controller for uniform (fully mixed) hot-water storage tanks.

    The whole tank is at one temperature: the water entering it (the charge from the sources, the return of
    the demands) mixes instantly with its content, and the water leaving it (back to the sources, to the
    demands) leaves at the tank temperature. Over a step the tank temperature is solved exactly
    (:func:`mixed_tank_step`), with the wall heat losses.

    The FluidMix coupling (what is asked to the sources, the bypass / charge / discharge split, the external
    setpoints, the reapply loop) is the one of the stratified heat storage, in
    :class:`FluidMixHeatStorageController`: the uniform tank is a tank of a single layer whose four
    connections are on that layer.

    :param prosumer: The prosumer object
    :param uniform_heat_storage_object: The uniform heat storage controller data object
    :param order: The order of the controller
    :param level: The level of the controller
    :param t_tank_init_c: Initial tank temperature (°C). Default: the element's ``t_ext_c``
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param name: The name of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "uniform_heat_storage_controller"

    def __init__(self, prosumer, uniform_heat_storage_object, order, level, t_tank_init_c=None, in_service=True,
                 index=None, name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, uniform_heat_storage_object, order=order, level=level, bypass=True,
                         in_service=in_service, index=index, name=name, **kwargs)

        self._mass_kg = float(self._get_element_param(prosumer, 'mass_kg'))
        if not self._mass_kg > 0:
            raise ValueError(f"Uniform heat storage {name}: mass_kg must be positive, got {self._mass_kg}")

        if t_tank_init_c is None or (np.isscalar(t_tank_init_c) and np.isnan(t_tank_init_c)):
            t_tank_init_c = self._get_element_param(prosumer, 't_ext_c')
        self._layer_temps_c = [float(t_tank_init_c)]
        self.N_l = 1
        self._ports = (0, 0, 0, 0)  # (charge_in, charge_out, discharge_out, discharge_in): all on the one layer
        self.init_layer_temps_c = self._layer_temps_c.copy()

        self._ua_w_per_k, self._t_ext_c = self._read_losses(prosumer)
        self._q_loss_kw = 0.0

    def time_step(self, prosumer, time):
        """Read the wall losses of the element for the new step."""
        super().time_step(prosumer, time)
        self._ua_w_per_k, self._t_ext_c = self._read_losses(prosumer)

    @property
    def _t_tank_c(self):
        return float(self._layer_temps_c[0])

    def _read_losses(self, prosumer):
        """Wall heat-loss coefficient UA (W/K) and ambient temperature (°C); no loss when UA is not set."""
        u_w_per_m2k = self._get_element_param(prosumer, 'u_w_per_m2k')
        area_m2 = self._get_element_param(prosumer, 'area_wall_m2')
        ua_w_per_k = float(u_w_per_m2k) * float(area_m2)
        if np.isnan(ua_w_per_k) or ua_w_per_k < 0:
            ua_w_per_k = 0.0
        t_ext_c = float(self._get_element_param(prosumer, 't_ext_c'))
        return ua_w_per_k, t_ext_c

    def _ua_kg_per_s(self):
        """UA / cp at the tank temperature (kg/s), the loss term of :func:`mixed_tank_step`."""
        return self._ua_w_per_k / float(self.fluid.get_heat_capacity(CELSIUS_TO_K + self._t_tank_c))

    def _layer_masses_kg(self):
        """Mass of the tank (kg), as a one-layer array."""
        return np.array([self._mass_kg])

    def _outlet_c(self, mass_kg, from_top, t_inflow_c):
        """
        Mean temperature (°C) of ``mass_kg`` of water leaving the mixed tank over a step while the same mass
        enters at ``t_inflow_c``, with the wall losses (:func:`mixed_tank_step` with this single stream). Both
        outlets carry the tank water, so ``from_top`` does not matter.
        """
        if mass_kg <= 0:
            return self._t_tank_c
        return mixed_tank_step(self._t_tank_c, self._mass_kg, [(mass_kg / self.resol, t_inflow_c)],
                               self._ua_kg_per_s(), self._t_ext_c, self.resol)[1]

    def _mass_for_heat_kg(self, heat_kgk, t_inflow_c, charge):
        """
        Mass (kg) of a single stream at ``t_inflow_c`` to push through the tank over a step to exchange
        ``heat_kgk`` (kg·K): stored by a charge, ``m · (t_in − T_mean)``, or delivered by a discharge,
        ``m · (T_mean − t_return)``. Both grow with the mass towards ``M · |T − t_in|``; a larger heat is
        capped at ``_max_exchange_mass_kg``. Solved by bisection on ``_outlet_c``, so that the request and the
        step (:meth:`_exchange`) book the same returns.
        """
        delta_t_c = (t_inflow_c - self._t_tank_c) if charge else (self._t_tank_c - t_inflow_c)
        if heat_kgk <= 0 or delta_t_c <= MIN_CHARGE_DELTA_T_K:
            return 0.0

        def heat_kgk_of(mass_kg):
            t_out_c = self._outlet_c(mass_kg, not charge, t_inflow_c)
            return mass_kg * ((t_inflow_c - t_out_c) if charge else (t_out_c - t_inflow_c))

        mass_max_kg = self._max_exchange_mass_kg(delta_t_c, charge)
        if heat_kgk_of(mass_max_kg) <= heat_kgk:
            return mass_max_kg
        low, high = 0.0, mass_max_kg
        for _ in range(_BISECTION_ITER):
            mid = (low + high) / 2
            if heat_kgk_of(mid) < heat_kgk:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    def _discharge_mass_for_heat_kg(self, heat_kgk, t_return_c):
        """Mass (kg) a discharge draws over a step to deliver ``heat_kgk`` (kg·K) above ``t_return_c``."""
        return self._mass_for_heat_kg(heat_kgk, t_return_c, charge=False)

    def _charge_mass_for_heat_kg(self, heat_kgk, t_charge_in_c):
        """Mass (kg) a charge at ``t_charge_in_c`` pushes through the tank over a step to store ``heat_kgk``."""
        return self._mass_for_heat_kg(heat_kgk, t_charge_in_c, charge=True)

    def _measured_return(self, request):
        """
        The reapply request with the return the tank really gave back on the previous pass, when the source is
        asked again for the stream it delivered then (same feed temperature, same mass flow): the split will be
        the same, so will the return.

        A mixed tank that charges while it discharges (a forced charge with the demand served from the tank,
        a forced discharge with the surplus charging it) gives the charge back at its mean temperature, which
        the demand's return entering the tank lowers. The request computes the charge return without that
        discharge (``_outlet_c``): kept as the promise, the loop would stagnate on the gap.
        """
        t_in_c, t_out_c, mdot_kg_per_s = request
        if (not np.isnan(self.t_previous_out_charge_c)
                and abs(self.t_previous_in_charge_c - t_in_c) <= 1e-6
                and abs(self.mdot_previous_in_kg_per_s - mdot_kg_per_s) <= 1e-6 * max(1.0, mdot_kg_per_s)):
            return t_in_c, float(self.t_previous_out_charge_c), mdot_kg_per_s
        return request

    def _reapply_request(self, prosumer, t_demand_out_c, t_demand_in_c, mdot_demand_kg_per_s,
                         t_charge_out_c, forward_request):
        return self._measured_return(super()._reapply_request(prosumer, t_demand_out_c, t_demand_in_c,
                                                               mdot_demand_kg_per_s, t_charge_out_c,
                                                               forward_request))

    def _forced_charge_reapply_request(self, mdot_charge_setpoint_kg_per_s, forward_request,
                                       e_demand_kgk_per_s=0.0, t_demand_in_c=np.nan):
        return self._measured_return(super()._forced_charge_reapply_request(
            mdot_charge_setpoint_kg_per_s, forward_request, e_demand_kgk_per_s, t_demand_in_c))

    def _max_exchange_mass_kg(self, delta_t_c, charge):
        """
        Most mass (kg) a single stream ``delta_t_c`` away from the tank temperature pushes through the tank over
        a step, ``M · ln(ΔT / MIN_CHARGE_DELTA_T_K)``: the mass that brings the tank within
        ``MIN_CHARGE_DELTA_T_K`` of the stream (without loss), 0 when it is already there.

        A charge is also capped at the tank's mass, one tank volume per step (it then closes 1 − 1/e ≈ 63 % of
        the gap; the next steps close the rest). Without that cap a tank a few kelvin under the charge
        temperature asks its source for several tank volumes of water that come back almost as hot as they
        left: a power-limited source serving the tank and a demand then iterates on a return close to its
        own feed and does not converge.
        """
        if delta_t_c <= MIN_CHARGE_DELTA_T_K:
            return 0.0
        mass_kg = self._mass_kg * np.log(delta_t_c / MIN_CHARGE_DELTA_T_K)
        return float(min(mass_kg, self._mass_kg) if charge else mass_kg)

    def _charge_mdot_to_fill(self, t_charge_in_c):
        """
        Charge mass flow (kg/s) the tank asks for to fill at ``t_charge_in_c`` (``_max_exchange_mass_kg`` over
        one step); 0 when it is within ``MIN_CHARGE_DELTA_T_K`` of it.
        """
        return self._max_exchange_mass_kg(t_charge_in_c - self._t_tank_c, charge=True) / self.resol

    def _exchange(self, prosumer, mdot_charge_kg_per_s, t_received_in_c, mdot_discharge_kg_per_s,
                  t_discharge_out_c, t_demand_in_c):
        """
        Move the tank over the step with the charge and the discharge the split decided
        (:func:`mixed_tank_step`).

        The split sized the discharge on the tank temperature at the start of the step; the water leaving
        the tank over the step is colder when draining it, warmer when it charges at the same time. Keep the
        heat the split sized and draw the discharge flow that carries it, solved together with the charge
        and the losses (the heat a flow carries out of a mixed tank grows with the flow). A tank that cannot
        give it within the step (the flow would have to bring it within ``MIN_CHARGE_DELTA_T_K`` of the
        return) gives what that flow carries.

        A charge no warmer than the tank would only cool it: it passes by, back to the source, without
        exchange (as in the stratified heat storage).

        :return: ``(mdot_discharge_kg_per_s, t_charge_out_c, t_discharge_out_c)``
        """
        t_start_c = self._t_tank_c
        ua_w_per_k, t_ext_c = self._ua_w_per_k, self._t_ext_c
        ua_kg_per_s = self._ua_kg_per_s()

        mdot_charge_tank_kg_per_s = mdot_charge_kg_per_s
        if mdot_charge_kg_per_s > 0 and t_received_in_c <= t_start_c:
            mdot_charge_tank_kg_per_s = 0.0

        def step(mdot_dch_kg_per_s):
            return mixed_tank_step(t_start_c, self._mass_kg,
                                   [(mdot_charge_tank_kg_per_s, t_received_in_c), (mdot_dch_kg_per_s, t_demand_in_c)],
                                   ua_kg_per_s, t_ext_c, self.resol)

        heat_kgk_per_s = mdot_discharge_kg_per_s * max(0.0, t_discharge_out_c - t_demand_in_c)
        mdot_discharge_tank_kg_per_s = 0.0
        if heat_kgk_per_s > 0 and t_start_c - t_demand_in_c > MIN_CHARGE_DELTA_T_K:
            def heat_out(mdot_dch_kg_per_s):
                return mdot_dch_kg_per_s * (step(mdot_dch_kg_per_s)[1] - t_demand_in_c)

            mdot_cap_kg_per_s = max(mdot_discharge_kg_per_s,
                                    self._max_exchange_mass_kg(t_start_c - t_demand_in_c, charge=False) / self.resol)
            if heat_out(mdot_cap_kg_per_s) <= heat_kgk_per_s:
                mdot_discharge_tank_kg_per_s = mdot_cap_kg_per_s
            else:
                low, high = 0.0, mdot_cap_kg_per_s
                for _ in range(_BISECTION_ITER):
                    mid = (low + high) / 2
                    if heat_out(mid) < heat_kgk_per_s:
                        low = mid
                    else:
                        high = mid
                mdot_discharge_tank_kg_per_s = (low + high) / 2

        t_end_c, t_mean_c = step(mdot_discharge_tank_kg_per_s)
        assert t_end_c > 0, (f"Uniform heat storage {self.name}: the tank temperature fell to {t_end_c} °C "
                             f"at timestep {self.time}")
        self._layer_temps_c = [t_end_c]
        self._q_loss_kw = ua_w_per_k * (t_mean_c - t_ext_c) / 1e3

        t_charge_out_c = t_mean_c if mdot_charge_tank_kg_per_s > 0 or mdot_charge_kg_per_s <= 0 else t_received_in_c
        t_discharge_out_c = t_mean_c if mdot_discharge_tank_kg_per_s > 0 else t_start_c
        return mdot_discharge_tank_kg_per_s, t_charge_out_c, t_discharge_out_c

    def _extra_result_values(self, prosumer):
        return [self._t_tank_c, self._q_loss_kw]
