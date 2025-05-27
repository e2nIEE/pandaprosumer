"""
Module containing the HeatDemandController class.
"""

import numpy as np
import logging

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C

logger = logging.getLogger(__name__)


class HeatDemandController(BasicProsumerController):
    """
    Controller for Heat Demand.

    :param prosumer: The prosumer object
    :param heat_demand_object: The heat demand object
    :param order: The order of the controller
    :param level: The level of the controller
    :param scale_factor: The scale factor for the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param name: The name of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "heat_demand_controller"

    def __init__(self, prosumer, heat_demand_object, order=-1, level=-1,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Initializes the HeatDemandController.
        """
        super().__init__(prosumer, heat_demand_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.t_previous_out_c = np.nan
        self.t_previous_in_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

    @property
    def _q_demand_kw(self):
        return self._get_input('q_demand_kw')

    @property
    def _mdot_demand_kg_per_s(self):
        return self._get_input('mdot_demand_kg_per_s')

    def _t_feed_demand_c(self,prosumer):
        return self._get_input('t_feed_demand_c',prosumer)

    @property
    def _t_return_demand_c(self):
        return self._get_input('t_return_demand_c')

    @property
    def _t_in_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        else:
            return np.nan
        # return self.inputs[:, self.input_columns.index("fluid_mix")][0][FluidMixMapping.TEMPERATURE_KEY]

    @property
    def _mdot_received_kg_per_s(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        else:
            return np.nan
        # if np.isnan(self.inputs[:, self.input_columns.index("fluid_mix")][0]):
        #     return np.nan
        # return self.inputs[:, self.input_columns.index("fluid_mix")][0][FluidMixMapping.MASS_FLOW_KEY]

    def q_to_receive_kw(self, prosumer):
        """
        Calculates the heat to receive in kW.

        :param prosumer: The prosumer object
        :return: Heat to receive in kW
        """
        self.applied = False
        q_to_receive_kw = 0.
        for responder in self._get_generic_mapped_responders(prosumer):
            # The demand is normally not mapped to anything
            q_to_receive_kw += responder.q_to_receive_kw(prosumer)
        q_to_receive_kw += self._q_demand_kw # The actual demand
        if not np.isnan(self._get_input('q_received_kw')):
            # If there is already some power in the input, don't require it again
            q_received_kw = self._get_input('q_received_kw')
            q_to_receive_kw -= q_received_kw
            q_to_receive_kw = max(0., q_to_receive_kw)
        return q_to_receive_kw

    def _demand_q_tf_tr_m(self, prosumer):
        if all(not np.isnan(val) for val in (
        self._t_feed_demand_c(prosumer), self._t_return_demand_c, self._q_demand_kw, self._mdot_demand_kg_per_s)):
            raise ValueError("Should not provide a value for all Heat Demand inputs")

        t_feed_demand_c = (self._t_feed_demand_c(prosumer)
                           if not np.isnan(self._t_feed_demand_c(prosumer))
                           else self._calc_t_feed(prosumer))
        t_return_demand_c = (self._t_return_demand_c
                             if not np.isnan(self._t_return_demand_c)
                             else self._calc_t_return(prosumer))

        mdot_demand_kg_per_s = (self._mdot_demand_kg_per_s
                                if not np.isnan(self._mdot_demand_kg_per_s)
                                else self._calc_mdot(prosumer, t_feed_demand_c, t_return_demand_c))

        q_demand = (self._q_demand_kw
                    if not np.isnan(self._q_demand_kw)
                    else self._calc_q(prosumer, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s))

        return q_demand, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s

    def _calc_t_feed(self, prosumer):
        if any(np.isnan(val) for val in (self._t_return_demand_c, self._q_demand_kw, self._mdot_demand_kg_per_s)):
            if self._get_element_param(prosumer, 'heating'):
                if not hasattr(self.element_instance, 't_in_set_c'):
                    raise ValueError("t_feed_demand_c (t_in_set_c) needs to be defined")
                return self.element_instance.t_in_set_c[self.element_index[0]]
            else:
                if not hasattr(self.element_instance, 't_out_set_c'):
                    raise ValueError("t_feed_demand_c (t_out_set_c) needs to be defined")
                return self.element_instance.t_out_set_c[self.element_index[0]]
        cp = prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + self._t_return_demand_c) / 1000
        if  self._get_element_param(prosumer, 'heating'):
            t_feed = self._t_return_demand_c + self._q_demand_kw / (self._mdot_demand_kg_per_s * cp)
        else:
            t_feed = self._t_return_demand_c - self._q_demand_kw / (self._mdot_demand_kg_per_s * cp)
        return t_feed

    def _calc_t_return(self, prosumer):
        if any(val is None or np.isnan(val) for val in (self._q_demand_kw, self._mdot_demand_kg_per_s)):
            if self._get_element_param(prosumer, 'heating'):
                if not hasattr(self.element_instance, 't_out_set_c'):
                    raise ValueError("t_return_demand_c (t_out_set_c) needs to be defined")
                return self.element_instance.t_out_set_c[self.element_index[0]]
            else:
                if not hasattr(self.element_instance, 't_in_set_c'):
                    raise ValueError("t_return_demand_c (t_in_set_c) needs to be defined")
                return self.element_instance.t_in_set_c[self.element_index[0]]

        t_feed = self._t_feed_demand_c(prosumer)
        cp = prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_feed) / 1000
        assert cp > 0 and not np.isnan(cp), "Invalid heat capacity"
        if self._get_element_param(prosumer, 'heating'):
            t_return = t_feed - self._q_demand_kw / (self._mdot_demand_kg_per_s * cp)
        else:
            t_return = t_feed + self._q_demand_kw / (self._mdot_demand_kg_per_s * cp)
        return t_return

    def _calc_mdot(self, prosumer, t_feed, t_return):
        if np.isnan(self._q_demand_kw):
            raise ValueError("Should provide at least mdot_demand_kg_per_s or q_demand_kw as Heat Demand input")
        t_mean = (t_feed + t_return) / 2
        cp = prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean) / 1000
        if self._get_element_param(prosumer, 'heating'):
            dT = (t_feed - t_return)
        else : dT = (t_return - t_feed)
        return self._q_demand_kw / (cp * dT) if abs(dT) >= 1e-12 else 0

    def _calc_q(self, prosumer, t_feed, t_return, mdot_demand_kg_per_s):
        t_mean_c = (t_feed + t_return) / 2
        cp = prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean_c) / 1000
        if self._get_element_param(prosumer, 'heating'):
            q = mdot_demand_kg_per_s * cp * (t_feed- t_return)
        else:
            q = mdot_demand_kg_per_s * cp * (t_return - t_feed)
        return q

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s = self._demand_q_tf_tr_m(prosumer)
        if not np.isnan(self.t_previous_out_c):
            return self.t_previous_in_c, self.t_previous_out_c, self.mdot_previous_in_kg_per_s
        else:
            if self._get_element_param(prosumer, 'heating') and (t_feed_demand_c <= t_return_demand_c or mdot_demand_kg_per_s < 1e-12):
                t_feed_demand_c = t_return_demand_c
                mdot_demand_kg_per_s = 0
            elif not self._get_element_param(prosumer, 'heating') and (
                    t_feed_demand_c >= t_return_demand_c or mdot_demand_kg_per_s < 1e-12):
                t_return_demand_c = t_feed_demand_c
                mdot_demand_kg_per_s = 0
            assert not np.isnan(t_feed_demand_c)
            assert not np.isnan(t_return_demand_c)
            assert not np.isnan(mdot_demand_kg_per_s)
            assert mdot_demand_kg_per_s >= 0
            # assert t_feed_demand_c >= t_return_demand_c
            return t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if self.in_service and getattr(prosumer, self.obj.element_name).iloc[self.obj.element_index[0]].in_service:
            super().control_step(prosumer)
            if not self._are_initiators_converged(prosumer):
                # If some of the initiators are not converged, do not run the control step
                self._unapply_initiators(prosumer)
                self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                  FluidMixMapping.MASS_FLOW_KEY: np.nan}
                return

            if not np.isnan(self._get_input('q_received_kw')):
                q_received_kw = self._get_input('q_received_kw')
                q_uncovered_kw = self._q_demand_kw - q_received_kw
                result = np.array([[q_received_kw, q_uncovered_kw, 0, 0, 0]])
                self.finalize(prosumer, result)
                self.applied = True
                return

            q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s = self._demand_q_tf_tr_m(prosumer)

            # ToDo: If t_in < t_out, return t_in, not t_out

            assert not np.isnan(self._t_in_c), f"Heat Demand {self.name} t_in_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
            assert not np.isnan(t_feed_demand_c), f"Heat Demand {self.name} t_feed_demand_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
            assert not np.isnan(t_return_demand_c), f"Heat Demand {self.name} t_return_demand_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
            assert not np.isnan(q_demand_kw), f"Heat Demand {self.name} q_demand_kw is NaN for timestep {self.time} in prosumer {prosumer.name}"
            assert not np.isnan(mdot_demand_kg_per_s), f"Heat Demand {self.name} mdot_demand_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"
            if not self._get_element_param(prosumer, 'heating'):
                t_mean_c = (self._t_in_c + t_return_demand_c) / 2
                cp_kj_per_kgk = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean_c)) / 1000

                if np.isnan(self._mdot_received_kg_per_s):
                    q_received_kw = q_demand_kw
                    mdot_received_kg_per_s = q_demand_kw / (cp_kj_per_kgk * (t_return_demand_c - self._t_in_c))
                else:
                    mdot_received_kg_per_s = self._mdot_received_kg_per_s
                    q_received_kw = cp_kj_per_kgk * mdot_received_kg_per_s * (t_return_demand_c - self._t_in_c)
            else:
                t_mean_c = (self._t_in_c + t_return_demand_c) / 2
                cp_kj_per_kgk = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean_c)) / 1000
                if np.isnan(self._mdot_received_kg_per_s):
                    q_received_kw = q_demand_kw
                    mdot_received_kg_per_s = q_demand_kw / (cp_kj_per_kgk * (self._t_in_c - t_return_demand_c))
                else:
                    mdot_received_kg_per_s = self._mdot_received_kg_per_s
                    q_received_kw = cp_kj_per_kgk * mdot_received_kg_per_s * (self._t_in_c - t_return_demand_c)
            t_out_c = t_return_demand_c
            # Calculate the difference between the received and the required power, wo considering the temperature level
            # FixMe: Consider the temperature level in the output
            q_uncovered_kw = q_demand_kw - q_received_kw
            result = np.array([[q_received_kw, q_uncovered_kw, mdot_received_kg_per_s, self._t_in_c, t_out_c]])
            if np.isnan(result).any():
                self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                  FluidMixMapping.MASS_FLOW_KEY: np.nan}
            else:
                if np.isnan(self.t_keep_return_c) or mdot_received_kg_per_s == 0 or abs(t_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C:  # or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0:
                    # If the actual output temperature is the same as the promised one, the storage is correctly applied
                    self.finalize(prosumer, result)
                    self.applied = True
                    self.t_previous_out_c = np.nan
                    self.t_previous_in_c = np.nan
                    self.mdot_previous_in_kg_per_s = np.nan
                else:
                    # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
                    self._unapply_initiators(prosumer)
                    self.t_previous_out_c = t_out_c
                    self.t_previous_in_c = self._t_in_c
                    self.mdot_previous_in_kg_per_s = mdot_received_kg_per_s
                    self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                      FluidMixMapping.MASS_FLOW_KEY: np.nan}

        else: self.applied = True  # self.in_service = False