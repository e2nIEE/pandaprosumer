"""
Module containing the HeatExchangerController class.
"""

import logging
import numpy as np
from pandapipes import call_lib
from scipy import optimize

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.constants import CELSIUS_TO_K, HeatExchangerControl, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.controller.models.dry_cooler import compute_temp as compute_temp_reverse

logger = logging.getLogger()


def solve_dichotomy(f, x_min, x_max):
    """
    Solve f(x)=0 by dichotomy in the interval [x_min, x_max].
    The function f should be strictly decreasing, or x_max and x_min reversed if it is increasing.

    :param f: Function to be solved.
    :param x_min: Minimum value.
    :param x_max: Maximum value.
    :return: The found value of x after convergence
    """
    x_mean = (x_max + x_min) / 2
    while (abs(f(x_mean)) > HeatExchangerControl.DICHOTOMY_CONVERGENCE_THRESHOLD
           and abs(x_max - x_min) > HeatExchangerControl.DICHOTOMY_CONVERGENCE_THRESHOLD):
        x_mean = (x_max + x_min) / 2
        if f(x_mean) > 0:
            x_min = x_mean
        else:
            x_max = x_mean
    return x_mean


def calculate_cold_temperature_difference(a, delta_t_hot):
    """
    Solve the equation with dichotomy to find t_out_1
    x is defined such as delta_t_cold / delta_t_hot = (1 - x) 

    :param a: The parameter 'a'
    :param delta_t_hot: The temperature difference between the primary hot (in) and secondary hot (out) temperatures
    :return: The temperature difference between the primary cold (out) and secondary cold (in) temperatures
    """
    dichotomy_fun = lambda x: a * x + np.log(1 - x)
    if a > 1:
        # dichotomy_fun is strictly decreasing on [x_min, x_max], 0 < x < 1
        x_max = 1
        x_min = (a - 1) / (a - 0.001)
    else:
        # dichotomy_fun is strictly increasing on [x_max, x_min], x < 0
        x_max = (a - 1) / a
        x_min = 3 * x_max

    x_mean = solve_dichotomy(dichotomy_fun, x_min, x_max)
    # x_mean = optimize.newton(dichotomy_fun, (x_min + x_max) / 2)

    delta_t_cold = (1 - x_mean) * delta_t_hot
    return delta_t_cold


def compute_temp(q_ratio, q_exchanged_w, t_1_in_c, t_2_in_c, t_2_out_c,
                 delta_t_hot_nom_c, delta_t_cold_nom_c, cp_1_j_per_kgk):
    """
    Calculate the return temperature on the primary side and the primary mass flow

    :param q_ratio: The ratio of the exchanged heat and the nominal exchanged heat
    :param q_exchanged_w: The heat to be exchanged
    :param t_1_in_c: The primary feed (hot) temperature
    :param t_2_in_c: The secondary input (cold) temperature (return pipe)
    :param t_2_out_c: The secondary output (hot) temperature (feed pipe)
    :param delta_t_hot_nom_c: The temperature difference between the nominal
        primary hot and secondary hot (out) temperature
    :param delta_t_cold_nom_c: The temperature difference between the nominal
        primary cold and secondary cold (out) temperature
    :param cp_1_j_per_kgk: The heat capacity of the fluid in the primary side

    :return: The temperature on the primary side and the primary mass flow
    """
    if q_ratio == 0:
        # No heat transfer at the secondary side so no heat transfer at the primary side
        t_1_out_c = t_1_in_c
    else:
        delta_t_hot = t_1_in_c - t_2_out_c
        # Logarithmic mean temperature difference (LMTD) at nominal conditions
        # FixMe: what if delta_t_hot_n == delta_t_cold_n ? wikipedia: limit val: lmtd_n = delta_t_hot_n = delta_t_cold_n
        if delta_t_hot_nom_c == delta_t_cold_nom_c:
            lmtd_nom = delta_t_hot_nom_c
        else:
            lmtd_nom = (delta_t_hot_nom_c - delta_t_cold_nom_c) / np.log(delta_t_hot_nom_c / delta_t_cold_nom_c)
        a = delta_t_hot / (q_ratio * lmtd_nom)
        if a > HeatExchangerControl.OUT_OF_RANGE_THRESHOLD:
            logger.warning("Heat Exchanger state too far from nominal conditions. "
                           f"The temperature difference between the primary (t_1_in_c={t_1_in_c}°C) and "
                           f"secondary side (t_2_out_c={t_2_out_c}°C) may be too high or the transferred heat "
                           f"q_exchanged_w={q_exchanged_w}W too small compared to the nominal conditions")
            t_1_out_c = t_1_in_c
        else:
            delta_t_cold = calculate_cold_temperature_difference(a, delta_t_hot)
            t_1_out_c = t_2_in_c + delta_t_cold

    # Find the primary mass flow rate so that the heat exchanged by the fluid on the primary side is equal to q_exchanged
    # mdot_1_kg_per_s = q_exchanged_w / (cp_1_j_per_kgk * (t_1_in_c - t_1_out_c))
    if t_1_in_c - t_1_out_c == 0:
        mdot_1_kg_per_s = 0
    else:
        mdot_1_kg_per_s = q_exchanged_w / (cp_1_j_per_kgk * (t_1_in_c - t_1_out_c))
    # elif a == 0:  # Note: Can go there with 'a' not defined if T_in_1 is nan
    #     mdot_1_kg_per_s = HeatExchangerControl.MIN_PRIMARY_MASS_FLOW_KG_PER_S  # 0.2 m3/h  FixMe: Why ?
    # else:
    #     # Find the primary mass flow rate so that the heat exchanged by the fluid on the primary side is equal to q_exchanged
    #     mdot_1_kg_per_s = q_exchanged_w / (cp_1_j_per_kgk * (t_1_in_c - t_1_out_c))
    if t_1_out_c > t_1_in_c:
        # The fluid on the primary side should not cool down
        t_1_out_c = t_1_in_c
        mdot_1_kg_per_s = 0
    # FixMe: t_1_out_c=nan if T_hot_1 == T_hot_2
    # self._a = a
    return t_1_out_c, mdot_1_kg_per_s  # , T_in_2, T_out_2, Q_2


class HeatExchangerController(BasicProsumerController):
    """
    Controller for Heat Exchanger systems.

    The heat exchanger is implemented from KS conservation and logarithmic mean temperature difference (LMTD)

    In the heat exchanger element some nominal temperatures and mass flows are specified.
    The resulting return temperature on the primary side is calculated from this state,
    then the primary mass flow is deducted.

    The temperature on the primary side must be higher than on the secondary (t_in_1 > t_out_2 and t_out_1 > t_in_2).

    Primary:
    t_in_1 = t_hot_1 = t_feed_1
    t_out_1 = t_cold_1 = t_return_1 (result of _compute_temp)

    Secondary:
    t_in_2 = t_cold_2 = t_return_2
    t_out_2 = t_hot_2 = t_feed_2

    :param prosumer: The prosumer object
    :param heat_exchanger_object: The heat exchanger object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "heat_exchanger_controller"

    def __init__(self, prosumer, stratified_heat_storage_object, order, level,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, stratified_heat_storage_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)

        self.primary_fluid = call_lib(self.element_instance.primary_fluid[self.element_index[0]]) \
            if self.element_instance.primary_fluid[self.element_index[0]] else prosumer.fluid
        self.secondary_fluid = call_lib(self.element_instance.secondary_fluid[self.element_index[0]]) \
            if self.element_instance.secondary_fluid[self.element_index[0]] else prosumer.fluid

        self.t_previous_1_out_c = np.nan
        self.t_previous_1_in_c = np.nan
        self.mdot_previous_1_kg_per_s = np.nan

    # FixMe: Fix the mapping (generic or fluid mix) and how to handle _mdot_feedin_kg_per_s
    @property
    def _t_feed_in_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        else:
            return self.inputs[:, self.input_columns.index("t_feed_in_c")][0]

    @property
    def _mdot_1_provided_kg_per_s(self):
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
        t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s = self.t_m_to_deliver(prosumer)
        if not np.isnan(self.t_previous_1_out_c):
            return self.t_previous_1_in_c, self.t_previous_1_out_c, self.mdot_previous_1_kg_per_s
        else:
            delta_t_hot_default_c = self._get_element_param(prosumer, 'delta_t_hot_default_c')
            return self.t_m_to_receive_for_t(prosumer, t_feed_demand_c + delta_t_hot_default_c)

    def t_m_to_receive_for_t(self, prosumer, t_feed_c):
        """
        For a given feed temperature in °C, calculate the required feed mass flow and the expected return temperature 
        if this feed temperature is provided.

        :param prosumer: The prosumer object
        :param t_feed_c: The feed temperature
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_out_2_required_c, t_in_2_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_2_required_kg_per_s = sum(mdot_tab_required_kg_per_s)

        t_1_in_c = t_feed_c

        if mdot_2_required_kg_per_s < 1e-6 or abs(t_out_2_required_c - t_in_2_required_c) < 1e-3:
            # If the secondary mass flow is too low, no heat is exchanged
            t_1_out_c = t_1_in_c
            mdot_1_kg_per_s = 0
        else:
            (mdot_1_kg_per_s, t_1_in_c, t_1_out_c,
             mdot_2_kg_per_s, t_2_in_c, t_2_out_c) = self.calculate_heat_exchanger(prosumer,
                                                                                   t_out_2_required_c,
                                                                                   t_in_2_required_c,
                                                                                   mdot_2_required_kg_per_s,
                                                                                   t_1_in_c)

        if not np.isnan(self.t_previous_1_out_c):
            # FixMe: This doesn't make sense
            mdot_previous_1_in_kg_per_s = self.mdot_previous_1_kg_per_s
            assert mdot_previous_1_in_kg_per_s >= 0
            assert self.t_previous_1_in_c >= self.t_previous_1_out_c
            return self.t_previous_1_in_c, self.t_previous_1_out_c, mdot_previous_1_in_kg_per_s

        assert not np.isnan(t_1_in_c)
        assert not np.isnan(t_1_out_c)
        assert not np.isnan(mdot_1_kg_per_s)
        assert mdot_1_kg_per_s >= 0, f"Heat Exchanger {self.name}: Negative mass flow {mdot_1_kg_per_s} kg/s at timestep {self.time} in prosumer {prosumer.name}"
        assert t_1_in_c >= t_1_out_c
        return t_1_in_c, t_1_out_c, mdot_1_kg_per_s

    def calculate_heat_exchanger(self, prosumer, t_2_out_c, t_2_in_c, mdot_2_kg_per_s, t_1_in_c):
        """
        Main Heat Exchanger calculation method

        :param prosumer: The prosumer object
        :param t_2_out_c: The secondary output (hot feed pipe) temperature
        :param t_2_in_c: The secondary input (cold return pipe) temperature
        :param mdot_2_kg_per_s: The secondary mass flow
        :param t_1_in_c: The primary input (hot feed pipe) temperature
        """
        t_1_hot_nom_c = self._get_element_param(prosumer, 't_1_in_nom_c')
        t_1_cold_nom_c = self._get_element_param(prosumer, 't_1_out_nom_c')
        t_2_cold_nom_c = self._get_element_param(prosumer, 't_2_in_nom_c')
        t_2_hot_nom_c = self._get_element_param(prosumer, 't_2_out_nom_c')
        mdot_2_nom_kg_per_s = self._get_element_param(prosumer, 'mdot_2_nom_kg_per_s')

        delta_t_2_c = t_2_out_c - t_2_in_c

        cp_2_j_per_kgk = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_2_out_c + t_2_in_c) / 2)
        cp_1_j_per_kgk = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + t_1_in_c)
        q_exchanged_w = cp_2_j_per_kgk * mdot_2_kg_per_s * delta_t_2_c

        max_q_kw = self._get_element_param(prosumer, 'max_q_kw')
        if q_exchanged_w > max_q_kw * 1000:
            q_exchanged_w = max_q_kw * 1000
            mdot_2_kg_per_s = max_q_kw * 1000 / (cp_2_j_per_kgk * delta_t_2_c)

        delta_t_2_nom_c = t_2_hot_nom_c - t_2_cold_nom_c
        cp_2_nom_j_per_kg_k = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_2_hot_nom_c + t_2_cold_nom_c) / 2)
        q_exchanged_nom_w = cp_2_nom_j_per_kg_k * mdot_2_nom_kg_per_s * delta_t_2_nom_c
        q_ratio = q_exchanged_w / q_exchanged_nom_w

        delta_t_hot_nom_c = t_1_hot_nom_c - t_2_hot_nom_c
        delta_t_cold_nom_c = t_1_cold_nom_c - t_2_cold_nom_c
        delta_t_hot_c = t_1_in_c - t_2_out_c
        # Logarithmic mean temperature difference (LMTD) at nominal conditions
        if delta_t_hot_nom_c == delta_t_cold_nom_c:
            lmtd_nom = delta_t_hot_nom_c
        else:
            lmtd_nom = (delta_t_hot_nom_c - delta_t_cold_nom_c) / np.log(delta_t_hot_nom_c / delta_t_cold_nom_c)
        a = delta_t_hot_c / (q_ratio * lmtd_nom)

        min_delta_t_1_c = self._get_element_param(prosumer, 'min_delta_t_1_c')
        max_t_1_out_c = t_1_in_c - min_delta_t_1_c
        min_x = 1 - (max_t_1_out_c - t_2_in_c) / delta_t_hot_c

        min_a = -np.log(1 - min_x) / min_x

        if a < min_a:
            # If 'a' is too low, q_exchanged_w is too big so reduce mdot_2_kg_per_s
            # else t_1_out_c would be hotter than t_1_in_c
            a = min_a
            q_ratio = delta_t_hot_c / (min_a * lmtd_nom)
            q_exchanged_w = q_ratio * q_exchanged_nom_w
            mdot_2_kg_per_s = q_exchanged_w / (cp_2_j_per_kgk * delta_t_2_c)
            # delta_t_cold = _calculate_cold_temperature_difference(a, delta_t_hot_c)
            t_1_out_c = max_t_1_out_c
            t_mean_1_c = CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2
            mdot_1_kg_per_s = q_exchanged_w / (self.primary_fluid.get_heat_capacity(t_mean_1_c) * (t_1_in_c - t_1_out_c))
        else:
            t_1_out_c, mdot_1_kg_per_s = compute_temp(q_ratio, q_exchanged_w, t_1_in_c, t_2_in_c, t_2_out_c,
                                                      delta_t_hot_nom_c, delta_t_cold_nom_c, cp_1_j_per_kgk)

        # If the primary mass flow is too low, no heat is exchanged to the secondary side
        # if mdot_1_kg_per_s < 1e-6:
        #     mdot_2_kg_per_s = 0
        #     t_2_out_c = t_2_in_c
        return mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c

    def calculate_heat_exchanger_reverse(self, prosumer, t_1_in_c, t_1_out_c, mdot_1_kg_per_s, t_2_in_c):
        """
        Air Cooled Heat Exchanger calculation method based on LMTD method from nominal conditions

        :param prosumer: The prosumer object
        :param t_1_in_c: The input temperature of the fluid in °C
        :param t_1_out_c: The output temperature of the fluid in °C
        :param mdot_1_kg_per_s: Mass flow rate of the fluid in kg/s
        :param t_2_in_c: The input temperature of the air in °C
        :return: The output mass flow rate of the air in kg/s, the input and output temperature of the air in °C,
            the output mass flow rate of the fluid in kg/s, the input and output temperature of the fluid in °C
        """
        t_1_hot_nom_c = self._get_element_param(prosumer, 't_1_in_nom_c')
        t_1_cold_nom_c = self._get_element_param(prosumer, 't_1_out_nom_c')
        t_2_cold_nom_c = self._get_element_param(prosumer, 't_2_in_nom_c')
        t_2_hot_nom_c = self._get_element_param(prosumer, 't_2_out_nom_c')
        mdot_2_nom_kg_per_s = self._get_element_param(prosumer, 'mdot_2_nom_kg_per_s')

        delta_t_fluid_c = t_1_in_c - t_1_out_c
        cp_fluid_j_per_kgk = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2)
        cp_air_j_per_kgk = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + t_2_in_c)
        q_exchanged_w = cp_fluid_j_per_kgk * mdot_1_kg_per_s * delta_t_fluid_c

        delta_t_air_n = t_2_hot_nom_c - t_2_cold_nom_c
        cp_air_nom_j_per_kg_k = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_2_hot_nom_c + t_2_cold_nom_c) / 2)
        q_exchanged_nom_w = cp_air_nom_j_per_kg_k * mdot_2_nom_kg_per_s * delta_t_air_n
        q_ratio = q_exchanged_w / q_exchanged_nom_w

        delta_t_hot_nom_c = t_1_hot_nom_c - t_2_hot_nom_c
        delta_t_cold_nom_c = t_1_cold_nom_c - t_2_cold_nom_c

        t_2_out_c, mdot_2_kg_per_s = compute_temp_reverse(q_ratio, q_exchanged_w, t_2_in_c, t_1_in_c, t_1_out_c,
                                                          delta_t_hot_nom_c, delta_t_cold_nom_c, cp_air_j_per_kgk)

        # If the primary mass flow is too low, no heat is exchanged to the secondary side
        if mdot_2_kg_per_s < 1e-6:
            mdot_1_kg_per_s = 0
            t_1_out_c = t_1_in_c
            t_2_out_c = t_2_in_c

        return mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c

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

        t_out_2_required_c, t_in_2_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_2_required_kg_per_s = sum(mdot_tab_required_kg_per_s)

        t_1_in_c = self._t_feed_in_c

        assert not np.isnan(t_1_in_c), f"Heat Exchanger {self.name} t_1_in_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_out_2_required_c), f"Heat Exchanger {self.name} t_out_2_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_in_2_required_c), f"Heat Exchanger {self.name} t_in_2_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_2_required_kg_per_s), f"Heat Exchanger {self.name} mdot_2_required_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"

        if mdot_2_required_kg_per_s < 1e-6 or abs(t_out_2_required_c - t_in_2_required_c) < 1e-3:
            # If the secondary mass flow is too low, no heat is exchanged
            t_1_out_c = t_1_in_c
            mdot_1_kg_per_s = 0
            mdot_2_kg_per_s = mdot_2_required_kg_per_s
            t_2_in_c = t_in_2_required_c
            t_2_out_c = t_out_2_required_c
            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer, mdot_2_kg_per_s,
                                                                   mdot_tab_required_kg_per_s)
        else:
            # FixMe: What to do in these cases ?
            assert t_1_in_c >= t_out_2_required_c, f"Heat Exchanger {self.name} t_1_in_c < t_out_2_required_c ({t_1_in_c} < {t_out_2_required_c}) for timestep {self.time} in prosumer {prosumer.name}"
            assert t_out_2_required_c >= t_in_2_required_c, f"Heat Exchanger {self.name} t_out_2_required_c < t_in_2_required_c ({t_out_2_required_c} < {t_in_2_required_c}) for timestep {self.time} in prosumer {prosumer.name}"

            rerun = True
            nb_runs = 0
            while rerun:
                nb_runs += 1
                if nb_runs > 20:
                    raise Exception("Heat Exchanger calculation did not converge after 100 iterations", self.name, self.time, prosumer.name)
                (mdot_1_kg_per_s, t_1_in_c, t_1_out_c,
                 mdot_2_kg_per_s, t_2_in_c, t_2_out_c) = self.calculate_heat_exchanger(prosumer,
                                                                                       t_out_2_required_c,
                                                                                       t_in_2_required_c,
                                                                                       mdot_2_required_kg_per_s,
                                                                                       t_1_in_c)

                # ToDo: Manage the case where m_1_kg_per_s_in < mdot_1_kg_per_s
                # If the input mass flow is smaller than the one required by the Heat Exchanger,
                # The primary return temperature is assumed equal to the secondary cold input
                # if m_1_kg_per_s_in < mdot_1_kg_per_s:
                #     t_1_out_c = t_cold_2
                #     mdot_1_kg_per_s = m_1_kg_per_s_in

                if not np.isnan(self._mdot_1_provided_kg_per_s):
                    # If the primary is fed with a fixed mass flow (not free air)
                    if mdot_1_kg_per_s > self._mdot_1_provided_kg_per_s:
                        # If the primary mass flow is higher than the one required by the Heat Exchanger,
                        # recalculate the secondary mass flow to reduce the heat demand to reduce the primary mass flow
                        # delta_t_2_c = t_2_out_c - t_2_in_c
                        # delta_t_1_c = t_1_in_c - t_1_out_c
                        # cp_1_j_per_kg_k = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2)
                        # cp_2_j_per_kg_k = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_2_out_c + t_2_in_c) / 2)
                        # q_exchanged_w = self._mdot_feed_in_kg_per_s * cp_1_j_per_kg_k * delta_t_1_c
                        # mdot_2_kg_per_s = q_exchanged_w / (cp_2_j_per_kg_k * delta_t_2_c)

                        # FixMe: The recalculation of the secondary mass flow lead to a higher mass flow, is it ok ?

                        (mdot_1_kg_per_s, t_1_in_c, t_1_out_c,
                         mdot_2_kg_per_s, t_2_in_c, t_2_out_c) = self.calculate_heat_exchanger_reverse(prosumer,
                                                                                                       t_1_in_c,
                                                                                                       t_1_out_c,
                                                                                                       self._mdot_1_provided_kg_per_s,
                                                                                                       t_2_in_c)

                        # ToDo: Check that mdot_1_kg_per_s==self._mdot_1_provided_kg_per_s
                        assert abs(mdot_1_kg_per_s - self._mdot_1_provided_kg_per_s) < .01
                    elif mdot_1_kg_per_s < self._mdot_1_provided_kg_per_s:
                        # If the primary mass flow is lower than the one required by the Heat Exchanger,
                        # model a bypass on the primary side where the extra mass flow doesn't exchange heat.
                        # Recalculate the primary output temperature
                        mdot_bypass_kg_per_s = self._mdot_1_provided_kg_per_s - mdot_1_kg_per_s
                        t_bypass_c = t_1_in_c
                        t_1_out_c = (t_bypass_c * mdot_bypass_kg_per_s + t_1_out_c * mdot_1_kg_per_s) / self._mdot_1_provided_kg_per_s
                        mdot_1_kg_per_s = self._mdot_1_provided_kg_per_s

                result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer, mdot_2_kg_per_s, mdot_tab_required_kg_per_s)

                rerun = False
                if len(self._get_mapped_responders(prosumer)) > 1 and mdot_2_kg_per_s < mdot_2_required_kg_per_s:
                    # If the heat Pump is not able to deliver the required mass flow,
                    # recalculate the condenser input temperature, considering that all the downstream elements will be
                    # still return the same temperature, even if the mass flow delivered to them by the Heat Pump is lower
                    t_return_tab_c = self.get_treturn_tab_c(prosumer)
                    if abs(mdot_2_kg_per_s) > 1e-8:
                        t_2_in_new_c = np.sum(result_mdot_tab_kg_per_s * t_return_tab_c) / mdot_2_kg_per_s
                    else:
                        t_2_in_new_c = t_in_2_required_c
                    if abs(t_2_in_new_c - t_in_2_required_c) > 1:
                        # If this recalculation changes the condenser input temperature, rerun the calculation
                        # with the new temperature
                        t_in_2_required_c = t_2_in_new_c
                        rerun = True

        if mdot_2_kg_per_s > mdot_2_required_kg_per_s:
            # If the actual output mass flow is higher than the one required, redistribute the extra mass flow
            # to the other downstream elements,
            # so the through the secondary side mass flow is the same as the total distributed mass flow
            for i in range(len(result_mdot_tab_kg_per_s)):
                result_mdot_tab_kg_per_s[i] = result_mdot_tab_kg_per_s[i] + (mdot_2_kg_per_s - mdot_2_required_kg_per_s) / len(result_mdot_tab_kg_per_s)

            assert abs(mdot_2_kg_per_s - np.sum(result_mdot_tab_kg_per_s)) < 1e-3

        result = np.array([[mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c]])

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_2_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        assert t_2_out_c >= 0, f"Heat Exchanger {self.name} t_2_out_c is negative ({t_2_out_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_2_in_c >= 0, f"Heat Exchanger {self.name} t_2_in_c is negative ({t_2_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_1_out_c >= 0, f"Heat Exchanger {self.name} t_1_out_c is negative ({t_1_out_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_1_in_c >= 0, f"Heat Exchanger {self.name} t_1_in_c is negative ({t_1_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_2_kg_per_s >= 0, f"Heat Exchanger {self.name} mdot_2_kg_per_s is negative ({mdot_2_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_1_kg_per_s >= 0, f"Heat Exchanger {self.name} mdot_1_kg_per_s is negative ({mdot_1_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_1_out_c <= t_1_in_c, f"Heat Exchanger {self.name} t_1_out_c > t_1_in_c ({t_1_out_c} > {t_1_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_2_out_c >= t_2_in_c, f"Heat Exchanger {self.name} t_2_out_c < t_2_in_c ({t_2_out_c} < {t_2_in_c}) for timestep {self.time} in prosumer {prosumer.name}"

        if np.isnan(self.t_keep_return_c) or mdot_1_kg_per_s == 0 or abs(t_1_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C:  # or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0:
            # If the actual output temperature is the same as the promised one, the storage is correctly applied
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_1_out_c = np.nan
            self.t_previous_1_in_c = np.nan
            self.mdot_previous_1_kg_per_s = np.nan
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            # FixMe: Should not do that if the initiators is not on the same level
            self._unapply_initiators(prosumer)
            self.t_previous_1_out_c = t_1_out_c
            self.t_previous_1_in_c = t_1_in_c
            self.mdot_previous_1_kg_per_s = mdot_1_kg_per_s
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
