"""
Module containing the GasBoilerController class.
"""

import numpy as np
from math import log
import pandas as pd

from pandapipes import create_fluid_from_lib, call_lib
from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.base import BasicProsumerController


class GasBoilerController(BasicProsumerController):
    """
    Controller for gas boilers.

    :param prosumer: The prosumer object
    :param gas_boiler_object: The gas boiler object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    @classmethod
    def name(cls):
        return "gas_boiler"

    def __init__(self, prosumer, gas_boiler_object, order, level, in_service=True, index=None,
                 name=None, **kwargs):
        """
        Initializes the GasBoilerController.
        """
        super().__init__(prosumer, gas_boiler_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.fluid = prosumer.fluid

    def _calculate_gas_boiler(self, prosumer, mdot_kg_per_s, t_out_c, t_in_c):
        """
        Main method for Gas Boiler physical calculation during one time step

        :param mdot_kg_per_s: Mass flow rate in kg/s
        :param t_out_c: Output provided temperature to the feed pipe in °C
        :param t_in_c: Input temperature from return pipe in °C

        """
        cp_fluid_kj_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_out_c + t_in_c) / 2) / 1000
        efficiency_percent = self._get_element_param(prosumer, 'efficiency_percent')
        heating_value_kj_per_kg = self._get_element_param(prosumer, 'heating_value_kj_per_kg')

        q_fluid_kw = mdot_kg_per_s * cp_fluid_kj_per_kgk * (t_out_c - t_in_c)

        mdot_gas_kg_per_s = q_fluid_kw / (efficiency_percent / 100) / heating_value_kj_per_kg

        # 8. Check parameters
        max_q_kw = self._get_element_param(prosumer, 'max_q_kw')
        if max_q_kw and q_fluid_kw > max_q_kw + 1e-3:
            # If the thermal power is too high, recalculate the output temperature

            mdot_gas_kg_per_s = max_q_kw / heating_value_kj_per_kg

            q_fluid_kw = max_q_kw
            # FixMe: Should update the output temperature or the mass flow rate ?
            t_out_c = t_in_c + q_fluid_kw / (mdot_kg_per_s * cp_fluid_kj_per_kgk)

        return q_fluid_kw, mdot_kg_per_s, t_in_c, t_out_c, mdot_gas_kg_per_s

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)

        t_out_required_c, t_in_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_required_kg_per_s = np.sum(mdot_tab_required_kg_per_s)

        assert not np.isnan(t_out_required_c), f"Gas Boiler {self.name} t_out_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_in_required_c), f"Gas Boiler {self.name} t_in_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_required_kg_per_s).any(), f"Gas Boiler {self.name} mdot_required_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert t_out_required_c >= t_in_required_c, f"Gas Boiler {self.name} t_out_required_c is lower than t_in_required_c for timestep {self.time} in prosumer {prosumer.name}"

        rerun = True
        while rerun:
            q_kw, mdot_delivered_kg_per_s, t_in_c, t_out_c, mdot_gas_kg_per_s = self._calculate_gas_boiler(prosumer,
                                                                                                   mdot_required_kg_per_s,
                                                                                                   t_out_required_c,
                                                                                                   t_in_required_c)

            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_delivered_kg_per_s,
                                                                   mdot_tab_required_kg_per_s)

            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_delivered_kg_per_s < mdot_required_kg_per_s:
                # If the gas boiler is not able to deliver the required mass flow,
                # recalculate the input temperature, considering that all the downstream elements will be
                # still return the same temperature, even if the mass flow delivered to them by the Boiler is lower
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

        assert q_kw >= 0, f"Gas Boiler {self.name} q_kw is negative ({q_kw}) for timestep {self.time} in prosumer {prosumer.name}"


        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        result = np.array([[q_kw, mdot_delivered_kg_per_s, t_in_c, t_out_c, mdot_gas_kg_per_s]])

        self.finalize(prosumer, result, result_fluid_mix)

        self.applied = True
