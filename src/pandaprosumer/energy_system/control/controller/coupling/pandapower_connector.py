"""
Module containing the HeatPumpController class.
"""

import numpy as np
from math import log
import pandas as pd

from pandapipes import create_fluid_from_lib, call_lib
from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.controller.base import BasicProsumerController


class PowerConnectorController(BasicProsumerController):
    """
    Controller for prosumer to pandapower connection.

    :param prosumer: The prosumer object
    :param power_connector_object: The PowerConnector object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    @classmethod
    def name(cls):
        return "power_connector"

    def __init__(self, prosumer, power_connector_object, order, level, in_service=True, index=None, name=None, **kwargs):
        """
        Initializes the Controller.
        """
        super().__init__(prosumer, power_connector_object, order=order, level=level, in_service=in_service, index=index,
                         name=name, **kwargs)

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)
        # Just take the input and mapp it to the ppower network so it will be written to the corresponding load element
        # The power is positive for load, negative for electricity generation
        # ToDo: Better using GenericMapping with application='subtract' or 2  different inputs, one for consumption and one for generation ?
        result = np.array([[self._get_input('p_kw')]])
        self.finalize(prosumer, result)

        self.applied = True
