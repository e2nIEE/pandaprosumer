"""
Module containing the StratifiedHeatStorageController class.
"""

import numpy as np
from numba import njit

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C


@njit
def tvd_resolution_in_time(layer_temps_c,
                           mdot_charge_kg_per_s,
                           t_charge_c,
                           mdot_discharge_kg_per_s,
                           t_return_c,
                           t_ext_c,
                           cp_j_per_kgk,
                           rho_kg_per_m3,
                           A_m2,
                           dz_m,
                           Sl_m2,
                           S1_m2,
                           SN_m2,
                           k_star_w_per_mk,
                           U_w_per_m2k,
                           U1_w_per_m2k,
                           UN_w_per_m2k,
                           resol,
                           max_dt_s):
    if resol < max_dt_s:
        # If the resolution is too small, we use a timestep
        # that is a multiple of the resolution
        nb_intervals = 1
        dt_s = resol
    else:
        # Calculate the number of intervals needed to reach the resolution
        offset = 1 if resol // max_dt_s != resol / max_dt_s else 0
        nb_intervals = int(resol // max_dt_s + offset)
        dt_s = resol / nb_intervals

    # Repeat the calculation so the timestep is not too big
    for i in range(nb_intervals):
        layer_temps_c = tvd_convection_step(layer_temps_c,
                                            mdot_charge_kg_per_s,
                                            t_charge_c,
                                            mdot_discharge_kg_per_s,
                                            t_return_c,
                                            t_ext_c,
                                            cp_j_per_kgk,
                                            rho_kg_per_m3,
                                            A_m2,
                                            dz_m,
                                            Sl_m2,
                                            S1_m2,
                                            SN_m2,
                                            k_star_w_per_mk,
                                            U_w_per_m2k,
                                            U1_w_per_m2k,
                                            UN_w_per_m2k,
                                            dt_s)
    # layer_temps_c = np.linalg.solve(a, b).tolist()
    return layer_temps_c


@njit
def phi(r):
    """
    For the moment, only superbee is introduced.

    r is the ratio of successive gradients on the solution; see r_{i}={\frac {u_{i}-u_{i-1}}{u_{i+1}-u_{i}}}
    """
    limiterName = "superbee"
    if limiterName == "superbee":
        return np.maximum(0, np.maximum(np.minimum(1., 2 * r), np.minimum(2., r)))
    elif limiterName == "vanleer":  # Not used
        return (r + abs(r)) / (1 + abs(r))
    else:
        raise ValueError("only superbee and van Leer are supported")


@njit
def tvd_convection_step(layer_temps_c,
                        mdot_charge_kg_per_s,
                        t_charge_c,
                        mdot_discharge_kg_per_s,
                        t_return_c,
                        t_ext_c,
                        cp_j_per_kgk,
                        rho_kg_per_m3,
                        A_m2,
                        dz_m,
                        Sl_m2,
                        S1_m2,
                        SN_m2,
                        k_star_w_per_mk,
                        U_w_per_m2k,
                        U1_w_per_m2k,
                        UN_w_per_m2k,
                        resol):
    #
    # We introduce a constant time step
    #
    ## bottom layer, see equation (3) in the paper
    #
    T = layer_temps_c
    deltaT = np.diff(T, 1)
    T_return = t_return_c
    T_charge = t_charge_c
    T_amb = t_ext_c
    T_1 = T[0]
    T_N = T[-1]
    m_cC_p = mdot_charge_kg_per_s * cp_j_per_kgk
    m_dC_p = mdot_discharge_kg_per_s * cp_j_per_kgk
    m_eC_p = (mdot_charge_kg_per_s - mdot_discharge_kg_per_s) * cp_j_per_kgk

    k_starA_wm_per_k = k_star_w_per_mk * A_m2
    k_starAoverDz_w_per_k = k_starA_wm_per_k / dz_m

    term_1 = U1_w_per_m2k * S1_m2 * (T_amb - T_1)  # heat losses to the env
    term_2 = (4 / 3) * k_starAoverDz_w_per_k * deltaT[0]  # diffusive terms
    # term_3 = m_cC_p * (T_2 - T_1)                                                    # convective terms
    term_3 = m_cC_p * (deltaT[0])
    term_4 = m_dC_p * (T_return - T_1)
    delta_layer_0 = term_1 + term_2 + term_3 + term_4

    theta = np.ones_like(T)
    limiter = np.ones_like(T)
    num = np.zeros_like(T)
    den = np.ones_like(T)
    den[2:] = -deltaT[1:]

    if m_eC_p > 0:
        num[:-1] = -deltaT[:]
    else:
        num[2:] = -deltaT[:-1]

    eps = 1.e-10
    den1 = np.abs(den)
    for i in range(den.size):
        if den1[i] >= eps:
            theta[i] = num[i] / den[i]

    limiter = phi(theta)

    # T = np.array(T)
    deltaT = np.diff(T, 1)
    term_1 = U_w_per_m2k * Sl_m2 * (t_ext_c - T[1:-1])
    term_2 = k_starAoverDz_w_per_k * (deltaT[1:] - deltaT[:-1])
    mass_flow_balance_J_per_K_per_s = (
            mdot_charge_kg_per_s - mdot_discharge_kg_per_s)  # this term can be negative
    c = mass_flow_balance_J_per_K_per_s / rho_kg_per_m3 / A_m2

    if c > 0:
        oneMinusCfl = 1. - (c * resol / dz_m)
        term_3 = mass_flow_balance_J_per_K_per_s * deltaT[1:]
        # term_33 =-0.5 * mass_flow_balance_J_per_K_per_s * oneMinusCfl * ((self.T[i - 1] - self.T[i]) * self.limiter[i] - (self.T[i] - self.T[i + 1]) * self.limiter[i + 1] )
        term_33 = -0.5 * mass_flow_balance_J_per_K_per_s * oneMinusCfl * (
                -deltaT[:-1] * limiter[1:-1] + deltaT[1:] * limiter[2:])
    else:
        oneMinusCfl = 1. - (-c * resol / dz_m)
        term_3 = mass_flow_balance_J_per_K_per_s * deltaT[:-1]
        term_33 = +0.5 * mass_flow_balance_J_per_K_per_s * oneMinusCfl * (
                deltaT[1:] * limiter[1:-1] - deltaT[:-1] * limiter[0:-2])

    layer_temp_deltas = term_1 + term_2 + cp_j_per_kgk * (term_3 + term_33)
    # layer_temp_deltas = layer_temp_deltas.tolist()

    #
    term_1 = UN_w_per_m2k * SN_m2 * (T_amb - T_N)  # heat losses to the env
    # term_2 = (4 / 3) * self.k_starAoverDz * (T_N_minus_1 - T_N)                       # diffusive terms
    term_2 = -(4 / 3) * k_starAoverDz_w_per_k * deltaT[-1]  # diffusive terms

    # convective terms
    if m_eC_p > 0:
        term_3 = m_eC_p * (T_charge - T_N)
        # delta_layer_N_l = timeStep * (term_1 + term_2 + term_3) * self.denominator
        delta_layer_N_l = term_1 + term_2 + term_3
    else:
        # term_4 = m_dC_p * (T_N_minus_1 - T_N)
        term_4 = -m_dC_p * deltaT[-1]
        # delta_layer_N_l = timeStep * (term_1 + term_2 + term_4) * self.denominator
        delta_layer_N_l = term_1 + term_2 + term_4
    #
    # Assuming layer_temp_deltas is a NumPy array
    new_layer_temp_deltas = np.empty(len(layer_temp_deltas) + 2, dtype=layer_temp_deltas.dtype)

    # Assign the first and last layers
    new_layer_temp_deltas[0] = delta_layer_0
    new_layer_temp_deltas[-1] = delta_layer_N_l

    # Copy the original array into the middle
    new_layer_temp_deltas[1:-1] = layer_temp_deltas
    #
    denominator_k_per_j = 1. / (rho_kg_per_m3 * cp_j_per_kgk * A_m2 * dz_m)
    return T + resol * new_layer_temp_deltas * denominator_k_per_j  # ToDo: Divide ?


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
            self._layer_temps_c = init_layer_temps_c

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

        # Heat exchange areas
        self.SN_m2 = perimeter_m * self.dz_m
        self.S1_m2 = self.Sl_m2 = self.A_m2 + self.SN_m2

        # initial temperatures are stored for computing stored energy (see eq. 8 in the paper)
        self.init_layer_temps_c = self._layer_temps_c.copy()

        self.t_previous_out_charge_c = np.nan
        self.t_previous_in_charge_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

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

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_demand_kg_per_s = np.sum(mdot_demand_tab_required_kg_per_s)
        t_charge_in_c = self._get_element_param(prosumer, 'min_useful_temp_c')  # self._layer_temps_c[-1]
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

        # TODO: Is the return temp the bottom layer temp or the responders' t_return ?
        t_charge_out_c = self._t_charge_out

        # If the storage is full -> do not required heat from upstream for charging
        remaining_capacity_kwh = self._get_max_stored_energy_kwh(t_charge_in_c, t_required_in_c) - \
                                 self._get_stored_energy_kwh(t_charge_in_c)
        if mdot_demand_kg_per_s > 0 and remaining_capacity_kwh < self._get_element_param(prosumer,
                                                                                         "max_remaining_capacity_kwh"):
            # FixMe: Go here if min_useful_temp_c = t_charge_in_c > t_required_in_c = t_demand_out_c
            return t_demand_out_c, t_demand_in_c, mdot_demand_kg_per_s

        # For charging, Ask to receive a mass flow corresponding to the volume of all layers in the storage for which
        # the temperature is smaller than the feed temperature
        rho_mean_kg_per_m3 = self.fluid.get_density(CELSIUS_TO_K + np.mean(self._layer_temps_c))
        m_layer_kg = self.A_m2 * self.dz_m * rho_mean_kg_per_m3
        nb_cold_layers = np.sum(np.array(self._layer_temps_c) < t_required_in_c)
        mdot_charge_kg_per_s = nb_cold_layers * m_layer_kg / self.resol

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
        # bypass surplus (~95 kW per near-full-tank step in the Paris ECS loop).
        delta_t_demand_c = t_demand_out_c - t_demand_in_c
        if t_required_in_c - t_demand_in_c > 1e-9 and t_required_in_c > t_demand_out_c:
            mdot_bypass_kg_per_s = mdot_demand_kg_per_s * delta_t_demand_c / (t_required_in_c - t_demand_in_c)
        else:
            mdot_bypass_kg_per_s = mdot_demand_kg_per_s

        mdot_required_kg_per_s = mdot_bypass_kg_per_s + mdot_charge_kg_per_s
        if mdot_required_kg_per_s == 0:
            t_required_out_c = t_required_in_c
        else:
            t_required_out_c = (mdot_bypass_kg_per_s * t_demand_in_c + mdot_charge_kg_per_s * t_charge_out_c) / mdot_required_kg_per_s

        if not np.isnan(self.t_previous_out_charge_c):
            mdot_charge_kg_per_s = mdot_demand_kg_per_s * (t_demand_in_c - t_required_out_c) / (t_required_out_c - t_charge_out_c)
            return self.t_previous_in_charge_c, self.t_previous_out_charge_c, mdot_charge_kg_per_s

        return t_required_in_c, t_required_out_c, mdot_required_kg_per_s

    @property
    def _t_charge_out(self):
        """
        Temperature of the fluid returned to the initiator in °C
        """
        return self._layer_temps_c[0]

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
        ret = sum([float(self.fluid.get_density(CELSIUS_TO_K + self._layer_temps_c[z])) * self.A_m2 *
                   float(self.fluid.get_heat_capacity(CELSIUS_TO_K + self._layer_temps_c[z])) *
                   (self._layer_temps_c[z] - self.init_layer_temps_c[z]) * self.dz_m
                   for z in range(self.N_l) if self._layer_temps_c[z] >= t_extraction_c - .1]) / 3.6e6
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
            # the received water is hotter (e.g. HP at TcstCondOut=65 serving a
            # 58/51 °C demand) the bypass carries ~2× the demand energy and the
            # HeatDemand books q_received ≈ 2·q_demand — i.e. negative
            # q_uncovered / over-serve (~−30 kW avg in the Paris ECS loop, with
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
                    t_min_useful_c = self._get_element_param(prosumer, 'min_useful_temp_c')
                    if t_min_useful_c is None or np.isnan(t_min_useful_c):
                        t_min_useful_c = t_demand_in_c + 1.0  # ≥1 K usable ΔT floor
                    if t_discharge_out_c >= t_min_useful_c and t_discharge_out_c - t_demand_in_c > 0.5:
                        e_demand = mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c)
                        e_bypass = mdot_bypass_kg_per_s * (t_received_in_c - t_demand_out_c)
                        mdot_discharge_kg_per_s = max(0.0, (e_demand - e_bypass) / (t_discharge_out_c - t_demand_in_c))
                    else:
                        # Tank spent (top below the usable threshold) — no
                        # discharge; the demand reports q_uncovered instead.
                        mdot_discharge_kg_per_s = 0.0
            else:
                # If this energy can be provided, charging with the extra mass flow
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

        self._layer_temps_c = tvd_resolution_in_time(layer_temps_c=np.array(self._layer_temps_c),
                                                     mdot_charge_kg_per_s=mdot_charge_kg_per_s,
                                                     t_charge_c=t_received_in_c,
                                                     mdot_discharge_kg_per_s=mdot_discharge_kg_per_s,
                                                     t_return_c=t_demand_in_c,
                                                     t_ext_c=t_ext_c,
                                                     cp_j_per_kgk=cp_discharge_j_per_kgk,
                                                     rho_kg_per_m3=rho_kg_per_m3,
                                                     A_m2=self.A_m2,
                                                     dz_m=self.dz_m,
                                                     Sl_m2=self.Sl_m2,
                                                     S1_m2=self.S1_m2,
                                                     SN_m2=self.SN_m2,
                                                     k_star_w_per_mk=self.k_star_w_per_mk,
                                                     U_w_per_m2k=self.U_w_per_m2k,
                                                     U1_w_per_m2k=self.U1_w_per_m2k,
                                                     UN_w_per_m2k=self.UN_w_per_m2k,
                                                     resol=self.resol,
                                                     max_dt_s=max_dt_s)

        assert (self._layer_temps_c > 0).all(), (f"The SHS model has diverged - "
                                                 f"Negative temperature in the storage for "
                                                 f"timestep {self.time} layers= {self._layer_temps_c}")

        cp_discharge_j_per_kgk = float(self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_discharge_out_c + t_demand_in_c) / 2))
        q_discharge_kw = mdot_discharge_kg_per_s * cp_discharge_j_per_kgk * (t_discharge_out_c - t_demand_in_c) / 1e3

        min_useful_temp_c = self._get_element_param(prosumer, 'min_useful_temp_c')
        e_stored_kwh = self._get_stored_energy_kwh(min_useful_temp_c)

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

        return (q_delivered_kw, q_bypass_kw, q_discharge_kw, q_received_kw, q_charge_kw, e_stored_kwh,
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

        # The discharge temperature is the one on top of the storage
        # Note that the time step should not be too long compared to the volume of this top layer and the mass flow
        t_discharge_out_c = self._layer_temps_c[-1]

        # When discharging, the temperature of the fluid that will be added at the bottom of the storage is the
        # temperature returned by the downstream elements.
        # Simple average of the temperatures but will have to be weighted by the mass flows in the future
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_demand_kg_per_s = sum(mdot_demand_tab_kg_per_s)

        assert mdot_demand_kg_per_s >= 0, f"SHS {self.name} mdot_demand_kg_per_s is negative ({mdot_demand_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_demand_out_c >= t_demand_in_c, f"SHS {self.name} t_demand_out_c < t_demand_in_c is negative ({t_demand_out_c} < {t_demand_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_demand_in_c >= 0, f"SHS {self.name} t_demand_in_c is negative ({t_demand_in_c}) for timestep {self.time} in prosumer {prosumer.name}"

        layer_temp_init_c = self._layer_temps_c.copy()

        rerun = True
        while rerun:
            self._layer_temps_c = layer_temp_init_c.copy()

            (q_delivered_kw, q_bypass_kw, q_discharge_kw, q_received_kw, q_charge_kw, e_stored_kwh,
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

            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_delivered_kg_per_s,
                                                                   mdot_demand_tab_kg_per_s)

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
                            e_stored_kwh]])

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
            # Also break out when the reapply loop has stagnated -- see comment above.
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_out_charge_c = np.nan
            self.t_previous_in_charge_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
            self._reapply_last_t_received_out_c = np.nan
            self._reapply_stagnation_count = 0
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            self._layer_temps_c = layer_temp_init_c
            self._unapply_initiators(prosumer)
            self.t_previous_out_charge_c = t_received_out_c
            self.t_previous_in_charge_c = t_received_in_c
            self.mdot_previous_in_kg_per_s = mdot_delivered_kg_per_s
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
