"""
Module containing the HeatExchangerController class.
"""

import logging
import numpy as np
from pandapipes import call_lib

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.library.heat_exchanger_utils import compute_temp

logger = logging.getLogger()


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
        primary_fluid = self._get_element_param(prosumer, 'primary_fluid')
        secondary_fluid = self._get_element_param(prosumer, 'secondary_fluid')
        if primary_fluid and primary_fluid != prosumer.fluid.name:
            self.primary_fluid = call_lib(primary_fluid)
        else:
            self.primary_fluid = prosumer.fluid
        if secondary_fluid and secondary_fluid != prosumer.fluid.name:
            self.secondary_fluid = call_lib(secondary_fluid)
        else:
            self.secondary_fluid = prosumer.fluid

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

        min_a = -np.log(1 - min_x) / min_x if min_x != 0 else 1  # FixMe: case where min_x == 1 or >= 1 ?

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
                                                      delta_t_hot_nom_c, delta_t_cold_nom_c, cp_1_j_per_kgk,
                                                      heat_consumer=False)

        # If the primary mass flow is too low, no heat is exchanged to the secondary side
        # if mdot_1_kg_per_s < 1e-6:
        #     mdot_2_kg_per_s = 0
        #     t_2_out_c = t_2_in_c
        return mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c

    def calculate_heat_exchanger_reverse(self, prosumer, t_1_in_c, t_1_out_c, mdot_1_kg_per_s, t_2_in_c):
        """
        Heat Exchanger calculation method based on LMTD method from nominal conditions.
        Reverse calculation that limit the primary side mass flow.

        :param prosumer: The prosumer object
        :param t_1_in_c: The input temperature of the fluid in °C
        :param t_1_out_c: The output temperature of the fluid in °C
        :param mdot_1_kg_per_s: Mass flow rate of the fluid in kg/s
        :param t_2_in_c: The input temperature of the secondary side in °C
        :return: The output mass flow rate of the secondary side in kg/s,
            the input and output temperature of the secondary side in °C,
            the output mass flow rate of the primary side in kg/s,
            the input and output temperature of the primary side in °C
        """
        t_1_hot_nom_c = self._get_element_param(prosumer, 't_1_in_nom_c')
        t_1_cold_nom_c = self._get_element_param(prosumer, 't_1_out_nom_c')
        t_2_cold_nom_c = self._get_element_param(prosumer, 't_2_in_nom_c')
        t_2_hot_nom_c = self._get_element_param(prosumer, 't_2_out_nom_c')
        mdot_2_nom_kg_per_s = self._get_element_param(prosumer, 'mdot_2_nom_kg_per_s')

        delta_t_fluid_c = t_1_in_c - t_1_out_c
        cp_fluid_j_per_kgk = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2)
        cp_2_j_per_kgk = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + t_2_in_c)
        q_exchanged_w = cp_fluid_j_per_kgk * mdot_1_kg_per_s * delta_t_fluid_c

        delta_t_2_n = t_2_hot_nom_c - t_2_cold_nom_c
        cp_2_nom_j_per_kg_k = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_2_hot_nom_c + t_2_cold_nom_c) / 2)
        q_exchanged_nom_w = cp_2_nom_j_per_kg_k * mdot_2_nom_kg_per_s * delta_t_2_n
        q_ratio = q_exchanged_w / q_exchanged_nom_w

        delta_t_hot_nom_c = t_1_hot_nom_c - t_2_hot_nom_c
        delta_t_cold_nom_c = t_1_cold_nom_c - t_2_cold_nom_c

        t_2_out_c, mdot_2_kg_per_s = compute_temp(q_ratio, q_exchanged_w, t_2_in_c, t_1_in_c, t_1_out_c,
                                                  delta_t_hot_nom_c, delta_t_cold_nom_c, cp_2_j_per_kgk,
                                                  heat_consumer=True)

        # If the primary mass flow is too low, no heat is exchanged to the secondary side
        if mdot_2_kg_per_s < 1e-6:
            mdot_1_kg_per_s = 0
            t_1_out_c = t_1_in_c
            t_2_out_c = t_2_in_c

        return mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c

    def _save_state(self):
        """Backup states before Run"""
        self._backup_state = {
            "t_previous_1_out_c": self.t_previous_1_out_c,
            "t_previous_1_in_c": self.t_previous_1_in_c,
            "mdot_previous_1_kg_per_s": self.mdot_previous_1_kg_per_s,
        }

    def _restore_state(self):
        """Restore states before Rerun"""
        if hasattr(self, "_backup_state"):
            self.t_previous_1_out_c = self._backup_state["t_previous_1_out_c"]
            self.t_previous_1_in_c = self._backup_state["t_previous_1_in_c"]
            self.mdot_previous_1_kg_per_s = self._backup_state["mdot_previous_1_kg_per_s"]

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if not prosumer.rerun:
            self._save_state()
        else:
            self._restore_state()

        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[
            self.obj.element_index[0]].in_service):  # FixMe: use gettattr element
            self.applied = True
            return

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
            # FixMe: case where t_out_2_required_c == t_in_2_required_c
            t_out_2_required_c_init = t_out_2_required_c
            if t_1_in_c < t_out_2_required_c:
                t_out_2_required_c = t_1_in_c - min(self._get_element_param(prosumer, 'delta_t_hot_default_c'), 5)
            if t_out_2_required_c < t_in_2_required_c:
                t_in_2_required_c += t_out_2_required_c - t_out_2_required_c_init

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
                    assert self._mdot_1_provided_kg_per_s >= 0, f"Heat Exchanger {self.name} received mass flow is negative for for timestep {self.time} in prosumer {prosumer.name}"
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
                        assert abs(mdot_1_kg_per_s - self._mdot_1_provided_kg_per_s) < .01,\
                            (f"Heat Exchanger {self.name} mdot_1_kg_per_s != self._mdot_1_provided_kg_per_s"
                             f" ({mdot_1_kg_per_s} != {self._mdot_1_provided_kg_per_s}) for for timestep"
                             f" {self.time} in prosumer {prosumer.name}")

                    elif mdot_1_kg_per_s < self._mdot_1_provided_kg_per_s:
                        # If the primary mass flow is lower than the one required by the Heat Exchanger,
                        # model a bypass on the primary side where the extra mass flow doesn't exchange heat.
                        # Recalculate the primary output temperature
                        mdot_bypass_kg_per_s = self._mdot_1_provided_kg_per_s - mdot_1_kg_per_s
                        t_bypass_c = t_1_in_c
                        t_1_out_c = (t_bypass_c * mdot_bypass_kg_per_s + t_1_out_c * mdot_1_kg_per_s) / self._mdot_1_provided_kg_per_s
                        mdot_1_kg_per_s = self._mdot_1_provided_kg_per_s

                result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                       mdot_2_kg_per_s,
                                                                       mdot_tab_required_kg_per_s)

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

            assert abs(mdot_2_kg_per_s - np.sum(result_mdot_tab_kg_per_s)) < 1e-3, \
                (f"Heat Exchanger {self.name} mdot_2_kg_per_s != sum(result_mdot_tab_kg_per_s) "
                 f"({mdot_2_kg_per_s} != {np.sum(result_mdot_tab_kg_per_s)}) for"
                 f" timestep {self.time} in prosumer {prosumer.name}")

        cp_1_kj_per_kg_k = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2) / 1000
        q_exchanged_kw = mdot_1_kg_per_s * cp_1_kj_per_kg_k * (t_1_in_c - t_1_out_c)
        result = np.array(
            [[q_exchanged_kw, mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c]]
        )

        self.last_result = {
            "q_exchanged_kw": q_exchanged_kw,
            "mdot_1_kg_per_s": mdot_1_kg_per_s,
            "t_1_in_c": t_1_in_c,
            "t_1_out_c": t_1_out_c,
            "mdot_2_kg_per_s": mdot_2_kg_per_s,
            "t_2_in_c": t_2_in_c,
            "t_2_out_c": t_2_out_c,
        }

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
