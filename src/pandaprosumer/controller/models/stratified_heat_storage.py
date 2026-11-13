"""
Module containing the StratifiedHeatStorageController class.
"""

import numpy as np

from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.models.fluid_mix_heat_storage import (  # noqa: F401 (constants re-exported)
    MIN_CHARGE_DELTA_T_K, MIN_USEFUL_MARGIN_K, WATER_FREEZING_POINT_C, FluidMixHeatStorageController,
)
from pandaprosumer.controller.models.shs_ports import (
    HEIGHT_PARAMS, PORTS, auto_discharge_layer, auto_inlet_layer, layer_at_height, mix_inverted_layers,
    parse_auto_ports, ports_resolution_in_time,
)


class StratifiedHeatStorageController(FluidMixHeatStorageController):
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

    The FluidMix coupling (request, split, setpoints, reapply loop) is in
    :class:`FluidMixHeatStorageController`; this class holds the tank's layers and their physics.

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
        super().__init__(prosumer, stratified_heat_storage_object, order=order, level=level, bypass=bypass,
                         in_service=in_service, index=index, name=name, **kwargs)

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

        # Used for debugging
        self.plot = plot
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

    def _outlet_c(self, mass_kg, from_top, t_inflow_c):
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

    def _discharge_mass_for_heat_kg(self, heat_kgk, t_return_c):
        """
        Mass (kg) a discharge must draw from the top over a step to deliver ``heat_kgk`` (kg·K, i.e.
        energy / cp) above ``t_return_c``, plug flow: the inverse of ``_outlet_c`` on the discharge
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

    def _charge_mass_for_heat_kg(self, heat_kgk, t_charge_in_c):
        """
        Mass (kg) a charge at ``t_charge_in_c`` pushes out of its outlet over a step to store ``heat_kgk``
        (kg·K, i.e. energy / cp), plug flow: the inverse of ``_outlet_c`` on the charge side.
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

    def _short_circuits(self, t_charge_in_c):
        """
        Whether a charge and a discharge running at once short-circuit the tank: they share their connections
        (charge inlet = discharge outlet, charge outlet = discharge inlet) and the charge is no colder than the
        outlet layer, so it reaches the outlet straight instead of sinking into the tank.
        """
        charge_in, charge_out, discharge_out, discharge_in = self._ports
        return (charge_in == discharge_out and charge_out == discharge_in
                and t_charge_in_c >= self._layer_temps_c[discharge_out] - 1e-9)

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

    def _exchange(self, prosumer, mdot_charge_kg_per_s, t_received_in_c, mdot_discharge_kg_per_s,
                  t_discharge_out_c, t_demand_in_c):
        """
        Move the layers over the step (plug flow through the connections, wall losses, conduction, buoyancy
        mixing; see ``shs_ports.ports_resolution_in_time``) with the charge and the discharge the split decided.

        :return: ``(mdot_discharge_kg_per_s, t_charge_out_c, t_discharge_out_c)``
        """
        cp_discharge_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + np.mean(self._layer_temps_c))
        rho_kg_per_m3 = self.fluid.get_density(CELSIUS_TO_K + np.mean(self._layer_temps_c))
        t_ext_c = self._get_element_param(prosumer, 't_ext_c')

        max_dt_s = self._effective_max_dt_s(prosumer,
                                            mdot_charge_kg_per_s,
                                            mdot_discharge_kg_per_s,
                                            rho_kg_per_m3)

        charge_in, charge_out, discharge_out, discharge_in = self._ports
        # The heat the split sized for the demand, on the top layer
        discharge_heat_kgk_per_s = mdot_discharge_kg_per_s * max(0.0, t_discharge_out_c - t_demand_in_c)

        # Charging and discharging at once through the same connections (charge inlet = discharge outlet,
        # charge outlet = discharge inlet), the common flow short-circuits the tank: the charge water goes
        # straight to the demand, the demand's return straight back to the source; only the net flow crosses
        # the layers. Booking each outlet as if the other stream did not exist (the discharge drawn from the
        # start-of-step layers, colder than the charge entering the same layer) handed the demand lukewarm
        # water while the layers were heated by the full charge: a game tank charged with 440 kW gave 140 kW
        # at 51 degC to the network, its stored energy flat, ~300 kW lost every hour. Only a charge at least as
        # warm as the outlet layer reaches the outlet straight: a colder one sinks into the tank.
        mdot_short_kg_per_s = 0.0
        delta_t_short_c = t_received_in_c - t_demand_in_c
        if (self._short_circuits(t_received_in_c) and mdot_charge_kg_per_s > 0
                and discharge_heat_kgk_per_s > 0 and delta_t_short_c > 1e-9):
            mdot_short_kg_per_s = min(mdot_charge_kg_per_s, discharge_heat_kgk_per_s / delta_t_short_c)
            discharge_heat_kgk_per_s -= mdot_short_kg_per_s * delta_t_short_c
        mdot_charge_net_kg_per_s = mdot_charge_kg_per_s - mdot_short_kg_per_s

        # What leaves the tank over the step (plug flow from the start-of-step layers), not the bottom / top
        # layer alone: the return the source gets and the heat the demand gets
        t_charge_out_c = self._outlet_c(mdot_charge_net_kg_per_s * self.resol, False, t_received_in_c)
        mdot_charge_tank_kg_per_s = mdot_charge_net_kg_per_s
        if mdot_charge_net_kg_per_s > 0 and t_charge_out_c >= t_received_in_c:
            # A charge no warmer than the water it would push out only cools the tank (a top-entering
            # stream colder than the stratification): it passes by, back to the source, without exchange.
            # ToDo: enter at the layer of its own temperature (charge inlet height)
            mdot_charge_tank_kg_per_s = 0.0
            t_charge_out_c = t_received_in_c
        mdot_discharge_tank_kg_per_s = 0.0
        if discharge_heat_kgk_per_s > 0:
            # The split sized the discharge on the top layer; the plug flow draws the layers below it, warmer
            # in an inverted tank, colder when draining. Keep the energy the split sized, draw the mass that
            # carries it (or what the tank holds), so the demand gets neither more nor less than planned.
            mass_kg = self._discharge_mass_for_heat_kg(discharge_heat_kgk_per_s * self.resol, t_demand_in_c)
            mdot_discharge_tank_kg_per_s = mass_kg / self.resol
            if mass_kg > 0:
                t_discharge_out_c = self._outlet_c(mass_kg, True, t_demand_in_c)
        mdot_discharge_kg_per_s = mdot_short_kg_per_s + mdot_discharge_tank_kg_per_s
        if mdot_short_kg_per_s > 0:
            t_discharge_out_c = ((mdot_short_kg_per_s * t_received_in_c
                                  + mdot_discharge_tank_kg_per_s * t_discharge_out_c) / mdot_discharge_kg_per_s)
            t_charge_out_c = ((mdot_short_kg_per_s * t_demand_in_c + mdot_charge_net_kg_per_s * t_charge_out_c)
                              / mdot_charge_kg_per_s)

        self._layer_temps_c = ports_resolution_in_time(np.array(self._layer_temps_c, dtype=float),
                                                       charge_in, charge_out, discharge_out, discharge_in,
                                                       mdot_charge_tank_kg_per_s, t_received_in_c,
                                                       mdot_discharge_tank_kg_per_s, t_demand_in_c,
                                                       t_ext_c, cp_discharge_j_per_kgk, rho_kg_per_m3,
                                                       self.A_m2, self.dz_m, self.Sl_m2, self.S1_m2, self.SN_m2,
                                                       self.k_star_w_per_mk, self.U_w_per_m2k, self.U1_w_per_m2k,
                                                       self.UN_w_per_m2k, self.resol, max_dt_s)

        assert (self._layer_temps_c > 0).all(), (f"The SHS model has diverged - "
                                                 f"Negative temperature in the storage for "
                                                 f"timestep {self.time} layers= {self._layer_temps_c}")

        return mdot_discharge_kg_per_s, t_charge_out_c, t_discharge_out_c

    def _record_step(self, t_received_in_c, t_demand_in_c, mdot_charge_kg_per_s, mdot_discharge_kg_per_s):
        """Used for debugging: keep the layers' history (``plot=True``)."""
        if self.plot:
            self._layer_temps_tab_c += [self._layer_temps_c]  # Store all the layers temps history for analysis
            self.t_charge_tab_c += [t_received_in_c]
            self.t_discharge_tab_c += [t_demand_in_c]
            self.mdot_charge_tab_kg_per_s += [mdot_charge_kg_per_s]
            self.mdot_discharge_tab_kg_per_s += [mdot_discharge_kg_per_s]
