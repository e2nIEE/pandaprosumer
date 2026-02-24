"""
Module containing the GasBoilerController class.
"""

import numpy as np

from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.base import BasicProsumerController


def _calculate_gas_boiler_temp(mdot_kg_per_s, t_out_c, t_in_c, cp_fluid_kj_per_kgk, heating_value_kj_per_kg, 
                               efficiency_percent, max_q_kw, min_q_kw, q_previous_kw, delta_t_previous_c,
                               max_ramp_up_kw_per_s, max_ramp_down_kw_per_s, time_step_s):
        # FixMe: q_fluid_kw reaches zero only if the max_ramp_down allows it
        # FixMe: It doesn't prevent fast turn on / turn off of the boiler
        
        # Calculate the demand heating power
        q_fluid_kw = mdot_kg_per_s * cp_fluid_kj_per_kgk * (t_out_c - t_in_c)
        
        # Apply ramp up/down constraints
        if not np.isnan(q_previous_kw):  # Constraint not applicable for the first timestep
            delta_q = (q_fluid_kw - q_previous_kw)
            if max_ramp_up_kw_per_s and delta_q > max_ramp_up_kw_per_s * time_step_s:
                # Limit ramp up speed
                q_fluid_kw = q_previous_kw + max_ramp_up_kw_per_s * time_step_s
                # Recalculate the affected outputs
                mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
            if max_ramp_down_kw_per_s and delta_q < -1 * max_ramp_down_kw_per_s * time_step_s:
                # Limit ramp down speed
                q_fluid_kw = q_previous_kw - max_ramp_down_kw_per_s * time_step_s
                # Recalculate the affected outputs
                # Recalculate the fluid mass flow is the temperature difference is > 0
                if t_out_c - t_in_c > 1e-3:
                    mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
                elif mdot_kg_per_s > 1e-3:
                    # If not, recalculate the output temperature instead
                    t_out_c = t_in_c + q_fluid_kw / (mdot_kg_per_s * cp_fluid_kj_per_kgk)
                elif not np.isnan(delta_t_previous_c):
                    # If the mass flow is also null, recalculate it considering the same temperature difference as the previous timestep
                    t_out_c = t_in_c + delta_t_previous_c
                    mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
                else:
                    mdot_kg_per_s = 0
                    q_fluid_kw = 0
                    t_out_c = t_in_c
        
        # Calculate the necessary amount of fuel from heat value    
        mdot_fuel_kg_per_s = q_fluid_kw / (efficiency_percent / 100) / heating_value_kj_per_kg

        # Check parameters
        if max_q_kw and q_fluid_kw > max_q_kw + 1e-3:
            # If the thermal power is too high, recalculate the output mass flow rate
            q_fluid_kw = max_q_kw
            mdot_fuel_kg_per_s = q_fluid_kw / heating_value_kj_per_kg
            # FixMe: Should update the output temperature or the mass flow rate ?
            # t_out_c = t_in_c + q_fluid_kw / (mdot_kg_per_s * cp_fluid_kj_per_kgk)
            mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
            
        if min_q_kw and 1e-3 < q_fluid_kw < min_q_kw - 1e-3:
            # If the thermal power is too low but not null, apply min power constraint
            q_fluid_kw = min_q_kw
            mdot_fuel_kg_per_s = q_fluid_kw / heating_value_kj_per_kg
            # Recalculate the fluid mass flow is the temperature difference is > 0
            if t_out_c - t_in_c > 1e-3:
                mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
            else:
                # If not, recalculate the output temperature instead
                t_out_c = t_in_c + q_fluid_kw / (mdot_kg_per_s * cp_fluid_kj_per_kgk)

        return q_fluid_kw, mdot_kg_per_s, t_in_c, t_out_c, mdot_fuel_kg_per_s


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

    def name_class(self):
        return "gas_boiler_controller"

    def __init__(self, prosumer, gas_boiler_object, order, level, in_service=True, index=None,
                 name=None, **kwargs):
        """
        Initializes the GasBoilerController.
        """
        super().__init__(prosumer, gas_boiler_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.fluid = prosumer.fluid
        max_q_kw = self._get_element_param(prosumer, 'max_q_kw')
        min_q_kw = self._get_element_param(prosumer, 'min_q_kw')
        if not np.isnan(max_q_kw) and not np.isnan(min_q_kw) and min_q_kw > max_q_kw:
            raise ValueError(f"Gas Boiler {self.name} in prosumer {prosumer.name} has min_q_kw > max_q_kw ({min_q_kw} > {max_q_kw})")


    def _calculate_gas_boiler(self, prosumer, mdot_kg_per_s, t_out_c, t_in_c):
        """
        Main method for Gas Boiler physical calculation during one time step

        :param mdot_kg_per_s: Mass flow rate in kg/s
        :param t_out_c: Output provided temperature to the feed pipe in °C
        :param t_in_c: Input temperature from return pipe in °C

        """
        cp_fluid_kj_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_out_c + t_in_c) / 2) / 1000
        max_q_kw = self._get_element_param(prosumer, 'max_q_kw')
        min_q_kw = self._get_element_param(prosumer, 'min_q_kw')
        efficiency_percent = self._get_element_param(prosumer, 'efficiency_percent')
        heating_value_kj_per_kg = self._get_element_param(prosumer, 'heating_value_kj_per_kg')
        max_ramp_up_kw_per_s = self._get_element_param(prosumer, 'max_ramp_up_kw_per_s')
        max_ramp_down_kw_per_s = self._get_element_param(prosumer, 'max_ramp_down_kw_per_s')
        q_previous_kw = self.last_result.get('q_kw', np.nan)
        delta_t_previous_c = self.last_result.get('t_out_c', np.nan) - self.last_result.get('t_in_c', np.nan)

        q_fluid_kw, mdot_kg_per_s, t_in_c, t_out_c, mdot_fuel_kg_per_s = _calculate_gas_boiler_temp(mdot_kg_per_s, 
                                                                                                    t_out_c, 
                                                                                                    t_in_c,
                                                                                                    cp_fluid_kj_per_kgk,
                                                                                                    heating_value_kj_per_kg,
                                                                                                    efficiency_percent, 
                                                                                                    max_q_kw,
                                                                                                    min_q_kw,
                                                                                                    q_previous_kw,
                                                                                                    delta_t_previous_c,
                                                                                                    max_ramp_up_kw_per_s,
                                                                                                    max_ramp_down_kw_per_s, 
                                                                                                    self.resol)
        
        return q_fluid_kw, mdot_kg_per_s, t_in_c, t_out_c, mdot_fuel_kg_per_s

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[self.obj.element_index[0]].in_service):
            self.applied = True
            return

        super().control_step(prosumer)

        t_out_required_c, t_in_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_required_kg_per_s = np.sum(mdot_tab_required_kg_per_s)

        assert not np.isnan(t_out_required_c), f"Gas Boiler {self.name} t_out_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_in_required_c), f"Gas Boiler {self.name} t_in_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_required_kg_per_s).any(), f"Gas Boiler {self.name} mdot_required_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert t_out_required_c >= t_in_required_c, f"Gas Boiler {self.name} t_out_required_c is lower than t_in_required_c for timestep {self.time} in prosumer {prosumer.name}"

        rerun = True
        while rerun:
            q_kw, mdot_delivered_kg_per_s, t_in_c, t_out_c, mdot_gas_kg_per_s = self._calculate_gas_boiler(
                prosumer,
                mdot_required_kg_per_s,
                t_out_required_c,
                t_in_required_c,
            )

            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(
                prosumer,
                mdot_delivered_kg_per_s,
                mdot_tab_required_kg_per_s,
            )

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

        # After merit-order capping, ensure mass and energy balance at the interface:
        # use the actually delivered mass flow (sum of responder flows) and, if necessary,
        # increase the outlet temperature so that the same thermal power q_kw is carried
        # by this mass flow.
        mdot_used_kg_per_s = np.sum(result_mdot_tab_kg_per_s)
        tol = 1e-9
        if abs(mdot_delivered_kg_per_s - mdot_used_kg_per_s) > tol:
            cp_fluid_kj_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_out_c + t_in_c) / 2) / 1000
            if mdot_used_kg_per_s > tol:
                t_out_c = t_in_c + q_kw / (cp_fluid_kj_per_kgk * mdot_used_kg_per_s)
                mdot_delivered_kg_per_s = mdot_used_kg_per_s
            elif -tol < mdot_used_kg_per_s < tol and q_kw > tol:
                mdot_delivered_kg_per_s = q_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
                # update result_mdot_tab_kg_per_s with the new mass flow, distribute evenly if several responders
                if len(result_mdot_tab_kg_per_s) > 0:
                    result_mdot_tab_kg_per_s = np.array(result_mdot_tab_kg_per_s) + (mdot_delivered_kg_per_s - mdot_used_kg_per_s) / len(result_mdot_tab_kg_per_s)
                else:
                    result_mdot_tab_kg_per_s = np.array([mdot_delivered_kg_per_s])

        assert q_kw >= 0, (
            f"Gas Boiler {self.name} q_kw is negative ({q_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        )

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        result = np.array([[q_kw, mdot_delivered_kg_per_s, t_in_c, t_out_c, mdot_gas_kg_per_s]])

        self.last_result = {
            "q_kw": q_kw,
            "mdot_delivered_kg_per_s": mdot_delivered_kg_per_s,
            "t_in_c": t_in_c,
            "t_out_c": t_out_c,
            "mdot_gas_kg_per_s": mdot_gas_kg_per_s,
        }

        self.finalize(prosumer, result, result_fluid_mix)

        self.applied = True
