"""
Module containing the DryCoolerController class.
"""

import logging
import numpy as np
from scipy import optimize

import pandapipes

from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.constants import TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.library.heat_exchanger_utils import compute_temp

logger = logging.getLogger()


def _get_wet_bulb_temperature(t_db_c, phi_air_in_percent):
    """
    The equation is valid for 5% <= phi_percent <= 99% and -200°C <= t_db_c <= 50°C.
    It deviates from the psychrometric chart with a mean absolute error of 0.3°C

    :param t_db_c: The dry bulb temperature of the air in °C
    :param phi_air_in_percent: The relative humidity of the air in percent (0-100)
    :return: The wet bulb temperature of the air in °C
    """
    t_wb_c = (t_db_c * np.arctan(.151977 * (phi_air_in_percent + 8.313659) ** .5) +
              np.arctan(t_db_c + phi_air_in_percent) - np.arctan(phi_air_in_percent - 1.676331) +
              .00391838 * phi_air_in_percent ** (3 / 2) * np.arctan(.023101 * phi_air_in_percent) - 4.686035)

    return t_wb_c


def _solve_t_bc_c(t_wb_c, phi_air_out_percent):
    """
    Solve the equation for the wet bulb temperature of the air after adiabatic pre-cooling

    :param t_wb_c: The wet bulb temperature of the air after adiabatic pre-cooling
    :param phi_air_out_percent: The relative humidity of the air in percent (0-100) at the output
    :return: The dry bulb temperature of the air after adiabatic pre-cooling
    """

    # Define the equation in terms of t_bc_c (the variable we are solving for)
    def equation(t_bc_c):
        return _get_wet_bulb_temperature(t_bc_c, phi_air_out_percent) - t_wb_c

    # Use fsolve to find the root of the equation, starting with an initial guess
    t_bc_c_initial_guess = np.array([t_wb_c])
    t_bc_c_solution = optimize.fsolve(equation, t_bc_c_initial_guess)

    return t_bc_c_solution[0]  # fsolve returns an array, so return the first element


def _adiabatic_pre_cooling(t_db_c, phi_air_in_percent, phi_air_out_percent=99):
    """
    Calculate the output temperature of the air after adiabatic pre-cooling

    :param t_db_c: ambient air dry bulb temperature in °C
    :param phi_air_in_percent: relative humidity of air in percent
    :param phi_air_out_percent: relative humidity of air in percent after adiabatic pre-cooling
    :return: the corresponding wet bulb temperature
    """
    if phi_air_in_percent > phi_air_out_percent:
        # If the air is already wetter than the expected output, no adiabatic pre-cooling is needed
        return t_db_c

    t_wb_c = _get_wet_bulb_temperature(t_db_c, phi_air_in_percent)

    t_db_out_c = _solve_t_bc_c(t_wb_c, phi_air_out_percent)

    return t_db_out_c


class DryCoolerController(BasicProsumerController):
    """
    Controller for dry coolers.

    First implementation of the dry cooler that do not model the heat exchange between the water the air

    :param prosumer: The prosumer object
    :param dry_cooler_object: The heat pump object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    @classmethod
    def name_class(self):
        return "dry_cooler_controller"

    def __init__(self, prosumer, dry_cooler_object, order=-1, level=-1, in_service=True, index=None,
                 name=None, **kwargs):
        """
        Initializes the DryCoolerController.
        """
        super().__init__(prosumer, dry_cooler_object, order=order, level=level, in_service=in_service, index=index,
                         name=name, **kwargs)

        self.fluid = prosumer.fluid
        self.cooling_fluid = pandapipes.call_lib('air')
        self.t_previous_out_c = np.nan
        self.t_previous_in_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_feed_required_c = self._get_input('t_in_c', prosumer)
        t_return_required_c = self._get_input('t_out_c', prosumer)
        mdot_required_kg_per_s = self._get_input('mdot_fluid_kg_per_s', prosumer)

        if not np.isnan(self.t_previous_out_c):
            assert self.mdot_previous_in_kg_per_s >= 0
            assert self.t_previous_in_c + 1e-9 >= self.t_previous_out_c
            if self.t_previous_in_c < self.t_previous_out_c:
                self.t_previous_in_c = self.t_previous_out_c
            return self.t_previous_in_c, self.t_previous_out_c, self.mdot_previous_in_kg_per_s
        else:
            assert mdot_required_kg_per_s >= 0
            assert t_feed_required_c >= t_return_required_c
            return t_feed_required_c, t_return_required_c, mdot_required_kg_per_s

    def _calculate_air_cooled_heat_exchanger(self, prosumer, t_fluid_in_c, t_fluid_out_c, mdot_fluid_kg_per_s, t_air_in_c):
        """
        Air Cooled Heat Exchanger calculation method based on LMTD method from nominal conditions

        :param prosumer: The prosumer object
        :param t_fluid_in_c: The input temperature of the fluid in °C
        :param t_fluid_out_c: The output temperature of the fluid in °C
        :param mdot_fluid_kg_per_s: Mass flow rate of the fluid in kg/s
        :param t_air_in_c: The input temperature of the air in °C
        :return: The output mass flow rate of the air in kg/s, the input and output temperature of the air in °C,
            the output mass flow rate of the fluid in kg/s, the input and output temperature of the fluid in °C
        """
        t_hot_air_nom_c = self._get_element_param(prosumer, 't_air_out_nom_c')
        t_cold_air_nom_c = self._get_element_param(prosumer, 't_air_in_nom_c')
        t_cold_fluid_nom_c = self._get_element_param(prosumer, 't_fluid_out_nom_c')
        t_hot_fluid_nom_c = self._get_element_param(prosumer, 't_fluid_in_nom_c')
        rho_air_kg_per_m3 = self.cooling_fluid.get_density(CELSIUS_TO_K + (t_hot_air_nom_c + t_cold_air_nom_c) / 2)
        mdot_air_nom_kg_per_s = self._get_element_param(prosumer, 'qair_nom_m3_per_h') * rho_air_kg_per_m3 / 3600

        delta_t_fluid_c = t_fluid_in_c - t_fluid_out_c
        cp_fluid_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_fluid_in_c + t_fluid_out_c) / 2)
        cp_air_j_per_kgk = self.cooling_fluid.get_heat_capacity(CELSIUS_TO_K + t_air_in_c)
        q_exchanged_w = cp_fluid_j_per_kgk * mdot_fluid_kg_per_s * delta_t_fluid_c

        if abs(q_exchanged_w) < 1e-6:
            mdot_air_kg_per_s = 0.
            return mdot_air_kg_per_s, t_air_in_c, t_air_in_c, mdot_fluid_kg_per_s, t_fluid_in_c, t_fluid_out_c

        delta_t_air_n = t_hot_air_nom_c - t_cold_air_nom_c
        cp_air_nom_j_per_kg_k = self.cooling_fluid.get_heat_capacity(CELSIUS_TO_K + (t_hot_air_nom_c + t_cold_air_nom_c) / 2)
        q_exchanged_nom_w = cp_air_nom_j_per_kg_k * mdot_air_nom_kg_per_s * delta_t_air_n
        q_ratio = q_exchanged_w / q_exchanged_nom_w

        delta_t_hot_nom_c = t_hot_fluid_nom_c - t_hot_air_nom_c
        delta_t_cold_nom_c = t_cold_fluid_nom_c - t_cold_air_nom_c

        delta_t_cold_c = t_fluid_out_c - t_air_in_c
        if delta_t_hot_nom_c == delta_t_cold_nom_c:
            lmtd_nom = delta_t_hot_nom_c
        else:
            lmtd_nom = (delta_t_hot_nom_c - delta_t_cold_nom_c) / np.log(delta_t_hot_nom_c / delta_t_cold_nom_c)
        a_cold = delta_t_cold_c / (q_ratio * lmtd_nom)

        min_delta_t_air_c = self._get_element_param(prosumer, 'min_delta_t_air_c')
        min_t_air_out_c = t_air_in_c + min_delta_t_air_c
        max_x = (t_fluid_in_c - min_t_air_out_c) / delta_t_cold_c - 1
        if max_x <= -1:
            max_x = -0.999
        min_a = np.log(1 + max_x) / max_x

        if min_delta_t_air_c and a_cold < min_a:
            # If 'a' is too low, q_exchanged_w is too big so reduce mdot_fluid_kg_per_s
            # else t_air_out_c would be colder than t_air_in_c
            a_cold = min_a
            q_ratio = delta_t_cold_c / (min_a * lmtd_nom)
            q_exchanged_w = q_ratio * q_exchanged_nom_w
            # FixMe: Change the mass flow rate at inlet ! (max mdot dependent on temp level) (could also change temp?)
            mdot_fluid_kg_per_s = q_exchanged_w / (cp_fluid_j_per_kgk * delta_t_fluid_c)
            # delta_t_cold_c = _calculate_cold_temperature_difference(a, delta_t_hot)
            t_air_out_c = min_t_air_out_c
            t_mean_air_k = CELSIUS_TO_K + (t_air_in_c + t_air_out_c) / 2
            mdot_air_kg_per_s = q_exchanged_w / (self.cooling_fluid.get_heat_capacity(t_mean_air_k) * (t_air_out_c - t_air_in_c))
        else:
            t_air_out_c, mdot_air_kg_per_s = compute_temp(q_ratio, q_exchanged_w, t_air_in_c, t_fluid_in_c, t_fluid_out_c,
                                                          delta_t_hot_nom_c, delta_t_cold_nom_c, cp_air_j_per_kgk)

        # If the primary mass flow is too low, no heat is exchanged to the secondary side
        if mdot_air_kg_per_s < 1e-6:
            mdot_fluid_kg_per_s = 0
            t_fluid_out_c = t_fluid_in_c
            t_air_out_c = t_air_in_c

        return mdot_air_kg_per_s, t_air_in_c, t_air_out_c, mdot_fluid_kg_per_s, t_fluid_in_c, t_fluid_out_c

    def _calculate_dry_cooler(self, prosumer, mdot_fluid_kg_per_s, t_in_required_c, t_out_required_c):
        """
        Main method for Dry Cooler physical calculation during one time step

        :param mdot_fluid_kg_per_s: Mass flow rate of water in kg/s
        :param t_in_required_c: Input temperature from feed pipe in °C
        :param t_out_required_c: Output temperature of the cooled water to the return pipe in °C
        """

        t_fluid_mean_c = (t_out_required_c + t_in_required_c) / 2
        cp_fluid_kj_per_kg_k = self.fluid.get_heat_capacity(CELSIUS_TO_K + t_fluid_mean_c) / 1000

        t_air_in_c = self._get_input('t_air_in_c', prosumer)
        phi_air_in_percent = self._get_input('phi_air_in_percent', prosumer)
        phi_air_out_percent = self._get_element_param(prosumer, 'phi_adiabatic_sat_percent')

        # If the adiabatic mode is activated, the air is pre-cooled
        if self._get_element_param(prosumer, 'adiabatic_mode'):
            t_air_in_c = _adiabatic_pre_cooling(t_air_in_c, phi_air_in_percent, phi_air_out_percent)

        # Air heat exchanger calculation
        (mdot_air_kg_per_s, t_air_in_c, t_air_out_c,
         mdot_fluid_kg_per_s, t_fluid_in_c, t_fluid_out_c) = self._calculate_air_cooled_heat_exchanger(prosumer,
                                                                                                       t_in_required_c,
                                                                                                       t_out_required_c,
                                                                                                       mdot_fluid_kg_per_s,
                                                                                                       t_air_in_c)
        rho_air_kg_per_m3 = self.cooling_fluid.get_density(CELSIUS_TO_K + (t_air_in_c + t_air_out_c) / 2)
        mdot_air_m3_per_h = mdot_air_kg_per_s * 3600 / rho_air_kg_per_m3
        q_exchanged_kw = mdot_fluid_kg_per_s * cp_fluid_kj_per_kg_k * (t_fluid_in_c - t_fluid_out_c)

        # Use the Fan Affinity Laws to calculate the power consumed by the fans
        n_nom_rpm = self._get_element_param(prosumer, 'n_nom_rpm')
        p_fan_nom_kw = self._get_element_param(prosumer, 'p_fan_nom_kw')
        qair_nom_m3_per_h = self._get_element_param(prosumer, 'qair_nom_m3_per_h')
        a = p_fan_nom_kw / (n_nom_rpm ** 3)
        b = qair_nom_m3_per_h / n_nom_rpm
        n_rpm = mdot_air_m3_per_h / b
        p_fans_kw = a * n_rpm ** 3 * self._get_element_param(prosumer, 'fans_number')

        return (q_exchanged_kw, p_fans_kw, n_rpm, mdot_air_m3_per_h,
                mdot_air_kg_per_s, t_air_in_c, t_air_out_c,
                mdot_fluid_kg_per_s, t_fluid_in_c, t_fluid_out_c)

    def _save_state(self):
        """Backup states before Run"""
        self._backup_state = {
            "t_previous_out_c": self.t_previous_out_c,
            "t_previous_in_c": self.t_previous_in_c,
            "mdot_previous_in_kg_per_s": self.mdot_previous_in_kg_per_s,
        }

    def _restore_state(self):
        """Restore states before Rerun"""
        if hasattr(self, "_backup_state"):
            self.t_previous_out_c = self._backup_state["t_previous_out_c"]
            self.t_previous_in_c = self._backup_state["t_previous_in_c"]
            self.mdot_previous_in_kg_per_s = self._backup_state["mdot_previous_in_kg_per_s"]

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

        mdot_supplied_kg_per_s = self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        t_in_supplied_c = self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        t_out_required_c = self._get_input('t_out_c', prosumer)

        assert not np.isnan(t_in_supplied_c), f"Dry Cooler {self.name} t_in_supplied_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_out_required_c), f"Dry Cooler {self.name} t_out_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_supplied_kg_per_s), f"Dry Cooler {self.name} mdot_supplied_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"

        (q_exchanged_kw, p_fans_kw, n_rpm, mdot_air_m3_per_h,
         mdot_air_kg_per_s, t_air_in_c, t_air_out_c,
         mdot_fluid_kg_per_s, t_fluid_in_c, t_fluid_out_c) = self._calculate_dry_cooler(prosumer,
                                                                                        mdot_supplied_kg_per_s,
                                                                                        t_in_supplied_c,
                                                                                        t_out_required_c)

        if not np.isnan(mdot_supplied_kg_per_s):
            # If the primary is fed with a fixed mass flow (not free air)
            if mdot_fluid_kg_per_s > mdot_supplied_kg_per_s:
                # If the primary mass flow is higher than the one required by the Cooler,
                # recalculate the secondary mass flow to reduce the heat demand to reduce the primary mass flow
                # ToDo: This case should never happen for the dry cooler ?
                assert abs(mdot_fluid_kg_per_s - mdot_supplied_kg_per_s) < .01
            elif mdot_fluid_kg_per_s < mdot_supplied_kg_per_s:
                # If the primary mass flow is lower than the one required by the Cooler,
                # model a bypass on the primary side where the extra mass flow doesn't exchange heat.
                # Recalculate the primary output temperature
                mdot_bypass_kg_per_s = mdot_supplied_kg_per_s - mdot_fluid_kg_per_s
                t_bypass_c = t_in_supplied_c
                t_fluid_out_c = (t_bypass_c * mdot_bypass_kg_per_s + t_fluid_out_c * mdot_fluid_kg_per_s) / mdot_supplied_kg_per_s
                mdot_fluid_kg_per_s = mdot_supplied_kg_per_s

        result = np.array([[q_exchanged_kw, p_fans_kw, n_rpm, mdot_air_m3_per_h,
                            mdot_air_kg_per_s, t_air_in_c, t_air_out_c,
                            mdot_fluid_kg_per_s, t_fluid_in_c, t_fluid_out_c]])

        self.last_result = {
            "q_exchanged_kw": q_exchanged_kw,
            "p_fans_kw": p_fans_kw,
            "n_rpm": n_rpm,
            "mdot_air_m3_per_h": mdot_air_m3_per_h,
            "mdot_air_kg_per_s": mdot_air_kg_per_s,
            "t_air_in_c": t_air_in_c,
            "t_air_out_c": t_air_out_c,
            "mdot_fluid_kg_per_s": mdot_fluid_kg_per_s,
            "t_fluid_in_c": t_fluid_in_c,
            "t_fluid_out_c": t_fluid_out_c,
        }

        assert round(t_fluid_out_c, 4) <= round(t_fluid_in_c, 4), f"Dry Cooler {self.name} t_fluid_out_c > t_fluid_in_c ({t_fluid_out_c} > {t_fluid_in_c}) for timestep {self.time} in prosumer {prosumer.name}"

        # ToDo: Add a condition to check whether the mass flows are equal
        if np.isnan(self.t_keep_return_c) or mdot_fluid_kg_per_s == 0 or abs(t_fluid_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C:  # or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0:
            # If the actual output temperature is the same as the promised one, the controller is correctly applied
            self.finalize(prosumer, result)
            self.applied = True
            self.t_previous_out_c = np.nan
            self.t_previous_in_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            self._unapply_initiators(prosumer)
            self.t_previous_out_c = t_fluid_out_c
            self.t_previous_in_c = t_in_supplied_c
            self.mdot_previous_in_kg_per_s = mdot_supplied_kg_per_s
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
