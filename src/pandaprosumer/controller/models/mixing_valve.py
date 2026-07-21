"""
Module containing the MixingValveController class.
"""

import logging
import numpy as np

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.mapping import FluidMixMapping

logger = logging.getLogger(__name__)


class MixingValveController(BasicProsumerController):
    """
    Controller for a 3-way mixing valve.

    The valve draws hot fluid at t_in_c from an upstream producer (FluidMix
    initiator) and mixes it with return fluid recirculated at the responders'
    return temperature, so the responders receive their wished feed
    temperature. Mass and energy are conserved exactly under the constant-cp
    mixing rule (cp evaluated at the mean temperature; no heat loss, no
    pressure modeling).

    :param prosumer: The prosumer object
    :param mixing_valve_object: The mixing valve controller data object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "mixing_valve_controller"

    def __init__(self, prosumer, mixing_valve_object, order, level,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, mixing_valve_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.t_previous_in_c = np.nan
        self.t_previous_return_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

    @property
    def _t_received_c(self):
        """Supply temperature received from the upstream FluidMix, or NaN."""
        return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]

    @property
    def _mdot_received_kg_per_s(self):
        """Mass flow fixed by the upstream FluidMix initiator, or NaN if free."""
        return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]

    def calculate_mixing(self, t_in_c, t_out_req_c, t_return_req_c, mdot_out_req_kg_per_s):
        """
        Mixing algebra of the 3-way valve for a free (non-fixed) hot-leg flow.

        :param t_in_c: The hot supply temperature [°C]
        :param t_out_req_c: The feed temperature wished by the responders [°C]
        :param t_return_req_c: The responders' return temperature [°C]
        :param mdot_out_req_kg_per_s: The total mass flow required by the responders [kg/s]
        :return: A tuple (hot-leg mass flow [kg/s], recirculated mass flow [kg/s],
            delivered mass flow [kg/s], delivered feed temperature [°C])
        """
        if mdot_out_req_kg_per_s < 1e-6 or (t_out_req_c - t_return_req_c) < 1e-3:
            # Degenerate demand: nothing to deliver
            return 0., 0., 0., t_in_c
        if (t_in_c - t_return_req_c) < 1e-3:
            # Dead supply: cannot heat the return at all
            return 0., 0., 0., t_in_c
        if t_in_c <= t_out_req_c:
            # Cold supply: fully open, pass the flow through unchanged
            return mdot_out_req_kg_per_s, 0., mdot_out_req_kg_per_s, t_in_c
        mdot_in_kg_per_s = (mdot_out_req_kg_per_s
                            * (t_out_req_c - t_return_req_c) / (t_in_c - t_return_req_c))
        mdot_recirc_kg_per_s = mdot_out_req_kg_per_s - mdot_in_kg_per_s
        return mdot_in_kg_per_s, mdot_recirc_kg_per_s, mdot_out_req_kg_per_s, t_out_req_c
