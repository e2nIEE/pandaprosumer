"""
Module containing the PandaPipesFeedConnectorController class.
"""

import numpy as np
import pandas as pd
from pandapipes import create_fluid_from_lib, call_lib
from pandaprosumer2.mapping.fluid_mix import FluidMixMapping

from pandaprosumer2.controller.base import BasicProsumerController


class PandapipesConnectorController(BasicProsumerController):
    """
    Controller for Pandapipes coupling to a demander prosumer.
    """

    @classmethod
    def name(cls):
        return "pandapipes_connector"

    def __init__(self, container, pandapipes_feed_connector_object, order, level,
                 in_service=True, index=None, **kwargs):
        """
        Initializes the PandapipesConnectorController.

        :param container: The prosumer object
        :param pandapipes_feed_connector_object: The pandapipes_feed_connector object
        :param order: The order of the controller
        :param level: The level of the controller
        :param in_service: The in-service status of the controller
        :param index: The index of the controller
        :param kwargs: Additional keyword arguments
        """
        super().__init__(container, pandapipes_feed_connector_object, order=order, level=level,
                         in_service=in_service, index=index, **kwargs)

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
        t_out_required_c, t_in_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        assert not np.isnan(t_in_required_c)
        assert not np.isnan(mdot_tab_required_kg_per_s)
        assert not np.isnan(t_out_required_c)
        return t_out_required_c, t_in_required_c, mdot_tab_required_kg_per_s

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)

        t_out_required_c, t_in_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_required_kg_per_s = np.sum(mdot_tab_required_kg_per_s)
        mdot_delivered_kg_per_s = mdot_required_kg_per_s

        rerun = True
        while rerun:
            if not np.isnan(self._mdot_received_kg_per_s):
                # If the inlet is fed with a fixed mass flow (not free air)
                if mdot_delivered_kg_per_s >= self._mdot_received_kg_per_s:
                    # If the inlet mass flow is higher than the one required,
                    # recalculate the secondary mass flow to reduce the heat demand to reduce the inlet mass flow
                    mdot_bypass_kg_per_s = 0
                    mdot_delivered_kg_per_s = self._mdot_received_kg_per_s
                    t_return_out_c = t_in_required_c
                else:
                    # If the inlet mass flow is lower than the one required,
                    # model a bypass on the inlet side where the extra mass flow doesn't exchange heat.
                    # Recalculate the output temperature
                    mdot_bypass_kg_per_s = self._mdot_received_kg_per_s - mdot_delivered_kg_per_s
                    t_return_out_c = (mdot_bypass_kg_per_s * self._t_received_in_c + mdot_delivered_kg_per_s * t_in_required_c) / self._mdot_received_kg_per_s
                    # FixMe: What if self._mdot_received_kg_per_s==0 ?

            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_delivered_kg_per_s,
                                                                   mdot_tab_required_kg_per_s)

            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_delivered_kg_per_s < mdot_required_kg_per_s:
                # If not able to deliver the required mass flow,
                # recalculate the input temperature, considering that all the downstream elements will be
                # still return the same temperature, even if the mass flow delivered to them is lower
                t_return_tab_c = self.get_treturn_tab_c(prosumer)
                if abs(mdot_delivered_kg_per_s) > 1e-8:
                    t_in_new_c = np.sum(result_mdot_tab_kg_per_s * t_return_tab_c) / mdot_delivered_kg_per_s
                else:
                    t_in_new_c = t_in_required_c
                if abs(t_in_new_c - t_in_required_c) > 1:
                    # If this recalculation changes the input temperature, rerun the calculation
                    # with the new temperature
                    t_in_required_c = t_in_new_c
                    rerun = True

        # # ToDo: Check case where cannot supplied all required mass flow
        # if mdot_required_kg_per_s > mdot_received_kg_per_s:
        #     mdot_bypass_kg_per_s = 0
        #     t_return_out_c = t_in_required_c
        # else:
        #     mdot_bypass_kg_per_s = mdot_received_kg_per_s - sum(mdot_res_tab_kg_per_s)
        #     t_return_out_c = (mdot_bypass_kg_per_s * t_received_feed_c + sum(mdot_res_tab_kg_per_s) * t_in_required_c) / mdot_received_kg_per_s

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: self._t_received_in_c, FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        result = np.array([[mdot_delivered_kg_per_s, mdot_bypass_kg_per_s,
                            self._t_received_in_c, t_return_out_c, t_in_required_c]])

        self.finalize(prosumer, result, result_fluid_mix)

        self.applied = True
