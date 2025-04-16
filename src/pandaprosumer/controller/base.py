"""
Module containing the BasicProsumerController class.
"""

import numpy as np
import pandas as pd
from pandapower.control.basic_controller import BasicCtrl
from pandapower.control.util.auxiliary import drop_same_type_existing_controllers, log_same_type_existing_controllers
import logging as pplog
from .mapped import MappedController
from ..mapping import FluidMixMapping

logger = pplog.getLogger(__name__)


class BasicProsumerController(MappedController):
    """
    Base class for all prosumer controllers that can be part of a 'get_t_m' chain.

    :param container: The prosumer object
    :param basic_prosumer_object: The basic prosumer object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param drop_same_existing_ctrl: Whether to drop existing controllers of the same type
    :param overwrite: Whether to overwrite existing controllers
    :param name: The name of the controller
    :param matching_params: Matching parameters for the controller
    :param kwargs: Additional keyword arguments
    """

    @classmethod
    def name(cls):
        return "basic_controller"

    def __init__(self, container, basic_prosumer_object, order=0, level=0, in_service=True, index=None,
                 drop_same_existing_ctrl=False, overwrite=False, name=None, matching_params=None, **kwargs):
        """
        Initializes the BasicProsumerController.
        """
        super().__init__(container, basic_prosumer_object, order, level, in_service, index,
                         drop_same_existing_ctrl, overwrite, name, matching_params, **kwargs)

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)

    def get_treturn_tab_c(self, prosumer):
        """
        Calculates the feed temperature and mass flow to deliver
        as well as the expected return temperature in °C and kg/s.

        Get the expected temperatures and mass flow of the responders (mapped downstream controllers)

        Provide the maximal feed temperature
        Calculate the mass flows to feed to the other responders to provide the same power
        (assuming that the return temperature is not changed!)
        Calculate the return temperature as the average of the expected return temperatures weighted by the mass flows

        # ToDo: the actual return temperature could be different if the mass flow provided is less than the requested

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature (float), Return Temperature (float), Mass Flow to deliver (np.array[float])
        """
        # tfeed, treturn = pd.Series(0, index=self.element_index), pd.Series(0, index=self.element_index)
        # m = pd.Series(0, index=self.element_index)
        responders = self._get_mapped_responders(prosumer)
        if len(responders) == 0:
            return np.array([])

        # Get the expected temperatures and mass flow of all the responders
        tfeed_tab_c, treturn_tab_c, mdot_tab_kg_per_s = np.array([]), np.array([]), np.array([])
        for responder in responders:
            tfeed_i, treturn_i, mdot_i = responder.t_m_to_receive(prosumer)
            tfeed_tab_c = np.append(tfeed_tab_c, tfeed_i)
            treturn_tab_c = np.append(treturn_tab_c, treturn_i)
            mdot_tab_kg_per_s = np.append(mdot_tab_kg_per_s, mdot_i)

        return treturn_tab_c

    def t_m_to_deliver(self, prosumer):
        """
        Calculates the feed temperature and mass flow to deliver
        as well as the expected return temperature in °C and kg/s.

        Get the expected temperatures and mass flow of the responders (mapped downstream controllers)

        Provide the maximal feed temperature
        Calculate the mass flows to feed to the other responders to provide the same power
        (assuming that the return temperature is not changed!)
        Calculate the return temperature as the average of the expected return temperatures weighted by the mass flows

        # ToDo: the actual return temperature could be different if the mass flow provided is less than the requested

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature (float), Return Temperature (float), Mass Flow to deliver (np.array[float])
        """
        # tfeed, treturn = pd.Series(0, index=self.element_index), pd.Series(0, index=self.element_index)
        # m = pd.Series(0, index=self.element_index)
        responders = self._get_mapped_responders(prosumer)
        if len(responders) == 0:
            return 0, 0, np.array([])
        
        # Get the expected temperatures and mass flow of all the responders
        tfeed_tab_c, treturn_tab_c, mdot_tab_kg_per_s = np.array([]), np.array([]), np.array([])
        for responder in responders:
            tfeed_i, treturn_i, mdot_i = responder.t_m_to_receive(prosumer)
            tfeed_tab_c = np.append(tfeed_tab_c, tfeed_i)
            treturn_tab_c = np.append(treturn_tab_c, treturn_i)
            mdot_tab_kg_per_s = np.append(mdot_tab_kg_per_s, mdot_i)

        # Provide the maximal feed temperature
        tfeed_res_c = max(tfeed_tab_c)

        # Calculate the mass flows to feed to the other responders to provide the same power
        delta_t_c = np.full(len(treturn_tab_c), tfeed_res_c) - treturn_tab_c
        # Safely compute the flow rate change where the condition is met
        valid_delta_t_c = np.where(delta_t_c != 0, delta_t_c, np.nan)  # Replace 0 with NaN for safety
        mdot_tab_temp_kg_per_s = mdot_tab_kg_per_s * (tfeed_tab_c - treturn_tab_c) / valid_delta_t_c  # Compute safely
        # Replace NaN with 0
        mdot_tab_updated_kg_per_s = np.where(np.isnan(mdot_tab_temp_kg_per_s), 0, mdot_tab_temp_kg_per_s)

        # Calculate the return temperature as the average of the expected return temperatures weighted by the mass flows
        mdot_kg_per_s = np.sum(mdot_tab_updated_kg_per_s)
        treturn_res_c = np.sum(mdot_tab_updated_kg_per_s * treturn_tab_c) / mdot_kg_per_s if abs(mdot_kg_per_s) > 1e-8 else tfeed_res_c

        return tfeed_res_c, treturn_res_c, mdot_tab_updated_kg_per_s

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s
        This superclass method implement a default behavior that should normally be overridden in the subclasses

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        tfeed_required_c, treturn_required_c, m_tab = self.t_m_to_deliver(prosumer)
        mdot_required_kg_per_s = sum(m_tab)
        return tfeed_required_c, treturn_required_c, mdot_required_kg_per_s

    def t_m_to_receive(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s
        Call the function _t_m_to_receive_init that should normally be overridden in the subclasses, to
        get the expected temperatures and mass flow of the controller
        and calculate the required mass flow and feed temperature that should still be provided
        given the values already mapped in the input to provide the expected values

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        tfeed_required_c, treturn_required_c, mdot_required_kg_per_s = self._t_m_to_receive_init(prosumer)

        # self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = np.nan
        # self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = np.nan

        mdot_supplied_kg_per_s = self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        tfeedin_supplied_c = self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]

        if not np.isnan(mdot_supplied_kg_per_s) and (mdot_required_kg_per_s - mdot_supplied_kg_per_s) < 1e-5:
            # If already all mass flow is supplied, don't required more (even if the temperature is not good)
            mdot_required_kg_per_s = 0
        elif not (np.isnan(mdot_supplied_kg_per_s) or np.isnan(tfeedin_supplied_c)):
            # Else calculate which mass flow and feed temp would provide the required values
                mdot_required_kg_per_s_tmp = mdot_required_kg_per_s - mdot_supplied_kg_per_s
                # tfeed_required_c = (mdot_supplied_kg_per_s * tfeedin_supplied_c) / (mdot_required_kg_per_s * treturn_required_c) / mdot_required_kg_per_s_tmp
                tfeed_required_c = treturn_required_c + ((tfeed_required_c - treturn_required_c) * mdot_required_kg_per_s - (tfeedin_supplied_c - treturn_required_c) * mdot_supplied_kg_per_s) / mdot_required_kg_per_s_tmp
                mdot_required_kg_per_s = mdot_required_kg_per_s_tmp

        self.t_keep_return_c = treturn_required_c

        return tfeed_required_c, treturn_required_c, mdot_required_kg_per_s

    def t_m_to_deliver_for_t(self, prosumer, t_feed_c):
        """
        For a given feed temperature in °C,
        Calculates the mass flow to deliver as well as the expected return temperature in °C and kg/s.

        Used for the element directly connected to a District Heating Network (Heat Exchanger, Heat Pump)
        to assess what would be the required mass flow through the substation for a given feed temperature

        For a given feed temperature in °C, calculate the required feed mass flow and the expected return temperature
        if this feed temperature is provided.
        This superclass method implement a default behavior that should normally be overridden in the subclasses
        if the model is dependent on the feed temperature.

        :param prosumer: The prosumer object
        :param t_feed_c: The feed temperature
        :return: A Tuple (Feed temperature (float), Return Temperature (float), Mass Flow to deliver (np.array[float])
        """
        responders = self._get_mapped_responders(prosumer)
        # If there is no responder, required no energy
        if len(responders) == 0:
            return 0, 0, np.array([])

        # Get the expected temperatures and mass flow of all responders
        tfeed_tab_c, treturn_tab_c, mdot_tab_kg_per_s = np.array([]), np.array([]), np.array([])
        for responder in responders:
            tfeed_i, treturn_i, mdot_i = responder.t_m_to_receive_for_t(prosumer, t_feed_c)
            tfeed_tab_c = np.append(tfeed_tab_c, tfeed_i)
            treturn_tab_c = np.append(treturn_tab_c, treturn_i)
            mdot_tab_kg_per_s = np.append(mdot_tab_kg_per_s, mdot_i)

        tfeed_res_c = max(tfeed_tab_c)

        # Calculate the mass flows to feed to the other responders to provide the same power
        delta_t_c = np.full(len(treturn_tab_c), tfeed_res_c) - treturn_tab_c
        condition = abs(delta_t_c) > 1e-8
        mdot_tab_kg_per_s *= np.where(condition, (tfeed_tab_c - treturn_tab_c) / delta_t_c, 0)

        # Calculate the return temperature as the average of the expected return temperatures weighted by the mass flows
        mdot_kg_per_s = np.sum(mdot_tab_kg_per_s)
        treturn_res_c = np.sum(mdot_tab_kg_per_s * treturn_tab_c) / mdot_kg_per_s if abs(mdot_kg_per_s) > 1e-8 else tfeed_res_c

        return tfeed_res_c, treturn_res_c, mdot_tab_kg_per_s
