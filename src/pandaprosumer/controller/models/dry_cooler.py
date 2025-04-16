"""
Module containing the DryCoolerController class.
"""

import logging
import numpy as np
from scipy import optimize
from math import log

import pandapipes
import pandas as pd

from pandapipes import create_fluid_from_lib, call_lib
from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K, HeatExchangerControl
from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.constants import TEMPERATURE_CONVERGENCE_THRESHOLD_C

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


def solve_dichotomy(f, x_min, x_max):
    """
    Solve f(x)=0 by dichotomy in the interval [x_min, x_max].
    The function f should be strictly increasing, or x_min and x_max reversed if it is decreasing.

    :param f: Function to be solved.
    :param x_min: Minimum value.
    :param x_max: Maximum value.
    :return: The found value of x after convergence
    """
    x_mean = (x_max + x_min) / 2
    nb_runs = 0
    while (abs(f(x_mean)) > HeatExchangerControl.DICHOTOMY_CONVERGENCE_THRESHOLD
           and abs(x_max - x_min) > HeatExchangerControl.DICHOTOMY_CONVERGENCE_THRESHOLD):
        nb_runs += 1
        if nb_runs > 300:
            logger.warning(f"Dichotomy did not converge after {nb_runs} runs."
                           f"Reached xmin={x_min}, xmax={x_max}. Continuing with x_mean={x_mean}")
            break
        x_mean = (x_max + x_min) / 2
        if f(x_mean) < 0:
            x_min = x_mean
        else:
            x_max = x_mean
    return x_mean


def calculate_hot_temperature_difference(a, delta_t_cold):
    """
    Solve the equation with dichotomy to find t_out_1
    x is defined such as delta_t_cold / delta_t_hot = (1 - x)

    :param a: The parameter 'a'
    :param delta_t_cold: The temperature difference between the air cold (in) and water cold (out) temperatures
    :return: The temperature difference between the air hot (out) and water hot (in) temperatures
    """
    dichotomy_fun = lambda x: a * x - np.log(1 + x)
    if a > 1:
        # dichotomy_fun is strictly decreasing on [x_max, x_min], -1 < x < 0
        x_max = -1
        x_min = (1 - a) / (a - 0.001)
    else:
        # dichotomy_fun is strictly increasing on [x_min, x_max], x > 0
        x_min = (1 - a) / a
        x_max = 3 * x_min
    x_mean = solve_dichotomy(dichotomy_fun, x_min, x_max)
    # x_mean = optimize.newton(dichotomy_fun, (x_min + x_max) / 2)
    delta_t_hot = (1 + x_mean) * delta_t_cold
    return delta_t_hot


def compute_temp(q_ratio, q_exchanged_w, t_air_in_c, t_fluid_in_c, t_fluid_out_c,
                 delta_t_hot_nom_c, delta_t_cold_nom_c, cp_air_j_per_kgk):
    """
    Calculate the return temperature and the mass flow rate of the air

    :param q_ratio: The ratio of the exchanged heat and the nominal exchanged heat
    :param q_exchanged_w: The heat to be exchanged
    :param t_air_in_c: The air (cold) input temperature
    :param t_fluid_in_c: The fluid (hot) input temperature
    :param t_fluid_out_c: The fluid (cold) output temperature
    :param delta_t_hot_nom_c: The temperature difference between the nominal
        primary hot and secondary hot (out) temperature
    :param delta_t_cold_nom_c: The temperature difference between the nominal
        primary cold and secondary cold (out) temperature
    :param cp_air_j_per_kgk: The heat capacity of the air

    :return: The temperature on the primary side and the primary mass flow
    """
    if q_ratio == 0:
        # No heat transfer at the secondary side so no heat transfer at the primary side
        t_air_out_c = t_air_in_c
    else:
        delta_t_cold = t_fluid_out_c - t_air_in_c
        # Logarithmic mean temperature difference (LMTD) at nominal conditions
        if delta_t_hot_nom_c == delta_t_cold_nom_c:
            lmtd_nom = delta_t_hot_nom_c
        else:
            lmtd_nom = (delta_t_hot_nom_c - delta_t_cold_nom_c) / np.log(delta_t_hot_nom_c / delta_t_cold_nom_c)
        a_cold = delta_t_cold / (q_ratio * lmtd_nom)
        if a_cold > HeatExchangerControl.OUT_OF_RANGE_THRESHOLD:
            logger.warning("Heat Exchanger state too far from nominal conditions. "
                           f"The temperature difference between the primary (t_in_1_c={t_air_in_c}°C) and "
                           f"secondary side (t_out_2_c={t_fluid_out_c}°C) may be too high or the transferred heat "
                           "q_exchanged_w={q_exchanged_w}W too small compared to the nominal conditions")
            t_air_out_c = t_air_in_c
        else:
            delta_t_hot = calculate_hot_temperature_difference(a_cold, delta_t_cold)
            t_air_out_c = t_fluid_in_c - delta_t_hot

    # Find the primary mass flow rate so that the heat exchanged by the fluid on the secondary side is equal to q_exchanged
    # mdot_air_kg_per_s = q_exchanged_w / (cp_air_j_per_kgk * (t_air_out_c - t_air_in_c))
    if t_air_out_c - t_air_in_c == 0:
        mdot_air_kg_per_s = 0
    else:
        mdot_air_kg_per_s = q_exchanged_w / (cp_air_j_per_kgk * (t_air_out_c - t_air_in_c))
    # elif a_cold == 0:  # Note: Can go there with 'a_cold' not defined if T_in_1 is nan
    #     mdot_air_kg_per_s = HeatExchangerControl.MIN_PRIMARY_MASS_FLOW_KG_PER_S  # 0.2 m3/h  FixMe: Why ?
    # else:
    #     # Find the primary mass flow rate so that the heat exchanged by the fluid on the secondary side is equal to q_exchanged
    #     mdot_air_kg_per_s = q_exchanged_w / (cp_air_j_per_kgk * (t_air_out_c - t_air_in_c))
    # if t_air_out_c < t_air_in_c:
    #     # The fluid on the primary side should not cool down
    #     t_air_out_c = t_air_in_c
    #     mdot_air_kg_per_s = 0
    # FixMe: t_air_out_c=nan if T_hot_1 == T_hot_2
    return t_air_out_c, mdot_air_kg_per_s


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
    def name(cls):
        return "dry_cooler"

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
        t_feed_required_c = self._get_input('t_in_c')
        t_return_required_c = self._get_input('t_out_c')
        mdot_required_kg_per_s = self._get_input('mdot_fluid_kg_per_s')

        if not np.isnan(self.t_previous_out_c):
            assert self.mdot_previous_in_kg_per_s >= 0
            assert self.t_previous_in_c >= self.t_previous_out_c
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

        t_air_in_c = self._get_input('t_air_in_c')
        phi_air_in_percent = self._get_input('phi_air_in_percent')
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

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)
        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        mdot_supplied_kg_per_s = self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        t_in_supplied_c = self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        t_out_required_c = self._get_input('t_out_c')

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

        assert t_fluid_out_c <= t_fluid_in_c, f"Dry Cooler {self.name} t_fluid_out_c > t_fluid_in_c ({t_fluid_out_c} > {t_fluid_in_c}) for timestep {self.time} in prosumer {prosumer.name}"

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
