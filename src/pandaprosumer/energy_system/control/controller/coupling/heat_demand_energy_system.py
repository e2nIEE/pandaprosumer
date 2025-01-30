"""
Module containing the HeatDemandController class.
"""

import numpy as np
import pandas as pd
import logging
import math

from pandaprosumer2.constants import TEMPERATURE_CONVERGENCE_THRESHOLD_C, CELSIUS_TO_K
from pandaprosumer2.controller.base import BasicProsumerController
from pandaprosumer2.mapping.fluid_mix import FluidMixMapping

logger = logging.getLogger(__name__)


class HeatDemandEnergySystemController(BasicProsumerController):
    """
    Controller for Heat Demand, not a consumption of energy but used to represent the connection to a pandapipes
    network.
    Difference with normal heat demand: forward the input for mapping to connected network.
    The input should  not be mapped from a ConstProfile but from a Pandapipes network (ReadPipeProdController).

    :param container: The prosumer object
    :param heat_demand_object: The heat demand object
    :param order: The order of the controller
    :param level: The level of the controller
    :param scale_factor: The scale factor for the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param name: The name of the controller
    :param kwargs: Additional keyword arguments
    """

    @classmethod
    def name(cls):
        return "heat_demand_controller"

    def __init__(self, container, heat_demand_object, order=-1, level=-1,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Initializes the HeatDemandController.
        """
        super().__init__(container, heat_demand_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)

    @property
    def _q_demand_kw(self):
        return self.inputs[:, self.input_columns.index("q_demand_kw")][0]

    @property
    def _mdot_demand_kg_per_s(self):
        return self.inputs[:, self.input_columns.index("mdot_demand_kg_per_s")][0]

    @property
    def _t_feed_demand_c(self):
        return self.inputs[:, self.input_columns.index("t_feed_demand_c")][0]

    @property
    def _t_return_demand_c(self):
        return self.inputs[:, self.input_columns.index("t_return_demand_c")][0]

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

    def _demand_q_tf_tr_m(self, prosumer):
        if not(np.isnan(self._t_feed_demand_c) or np.isnan(self._t_return_demand_c)
               or np.isnan(self._q_demand_kw) or np.isnan(self._mdot_demand_kg_per_s)):
            raise ValueError("Should not provide a value for all Heat Demand inputs")

        if np.isnan(self._t_feed_demand_c):
            if np.isnan(self._t_return_demand_c) or np.isnan(self._q_demand_kw) or np.isnan(self._mdot_demand_kg_per_s):
                t_feed_demand_c = self.element_instance.t_in_set_c[self.element_index[0]]
            else:
                cp = float(prosumer.fluid.get_heat_capacity(273.15 + self._t_return_demand_c)) / 1000
                t_feed_demand_c = self._t_return_demand_c + self._q_demand_kw / (self._mdot_demand_kg_per_s * cp)
        else:
            t_feed_demand_c = self._t_feed_demand_c
        if np.isnan(self._t_return_demand_c):
            if np.isnan(self._q_demand_kw) or np.isnan(self._mdot_demand_kg_per_s):
                t_return_demand_c = self.element_instance.t_out_set_c[self.element_index[0]]
            else:
                cp = float(prosumer.fluid.get_heat_capacity(273.15 + t_feed_demand_c)) / 1000
                t_return_demand_c = t_feed_demand_c - self._q_demand_kw / (self._mdot_demand_kg_per_s * cp)
        else:
            t_return_demand_c = self._t_return_demand_c
        if np.isnan(self._mdot_demand_kg_per_s):
            if np.isnan(self._q_demand_kw):
                raise ValueError("Should provide at least mdot_demand_kg_per_s or q_demand_kw as Heat Demand input")
            else:
                cp = float(prosumer.fluid.get_heat_capacity(273.15 + (t_feed_demand_c + t_return_demand_c) / 2)) / 1000
                mdot_demand_kg_per_s = self._q_demand_kw / (cp * (t_feed_demand_c - t_return_demand_c))
        else:
            mdot_demand_kg_per_s = self._mdot_demand_kg_per_s
        if np.isnan(self._q_demand_kw):
            cp = float(prosumer.fluid.get_heat_capacity(273.15 + (t_feed_demand_c + t_return_demand_c) / 2)) / 1000
            q_demand_kw = mdot_demand_kg_per_s * cp * (t_feed_demand_c - t_return_demand_c)
        else:
            q_demand_kw = self._q_demand_kw
        return q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s = self._demand_q_tf_tr_m(prosumer)
        return t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)
        print("HeatDemandEnergySystemController control_step")
        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return
        q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s = self._demand_q_tf_tr_m(prosumer)

        t_mean_c = (self._t_in_c + t_return_demand_c) / 2
        cp_kj_per_kgk = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean_c)) / 1000
        if np.isnan(self._mdot_received_kg_per_s):
            q_received_kw = q_demand_kw
            mdot_received_kg_per_s = q_demand_kw / (cp_kj_per_kgk * (self._t_in_c - t_return_demand_c))
        else:
            mdot_received_kg_per_s = self._mdot_received_kg_per_s
            q_received_kw = cp_kj_per_kgk * mdot_received_kg_per_s * (self._t_in_c - t_return_demand_c)
        t_out_c = t_return_demand_c

        q_uncovered_kw = q_demand_kw - q_received_kw
        result = np.array([[q_received_kw, q_uncovered_kw, mdot_received_kg_per_s, self._t_in_c, t_out_c]])
        if np.isnan(result).any():
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
        else:
            if np.isnan(self.t_keep_return_c) or abs(t_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C:
                # If the actual output temperature is the same as the promised one, the storage is correctly applied
                # Difference with normal heat demand: forward the input for mapping to connected network
                result_fluid_mix = [{FluidMixMapping.TEMPERATURE_KEY: self._t_in_c,
                                     FluidMixMapping.MASS_FLOW_KEY: self._mdot_received_kg_per_s}]
                self.finalize(prosumer, result, result_fluid_mix)
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
