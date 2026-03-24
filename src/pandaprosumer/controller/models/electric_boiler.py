"""
Module containing the ElectricBoilerController class.
"""

import numpy as np

from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.base import BasicProsumerController


def _calculate_electric_boiler_temp(mdot_kg_per_s, t_out_c, t_in_c, cp_fluid_kj_per_kgk, 
                                    efficiency_percent, max_p_kw, min_p_kw, p_el_consumed_previous_kw,
                                    max_ramp_up_kw_per_s, max_ramp_down_kw_per_s, time_step_s, 
                                    allow_stop, max_t_out_c=None):
    # Calculate thermal power
    q_fluid_kw = mdot_kg_per_s * cp_fluid_kj_per_kgk * (t_out_c - t_in_c)

    # Calculate electric power
    p_el_consumed_kw = q_fluid_kw / (efficiency_percent / 100)
    
    # Apply maximum temperature constraint by keeping power constant and adjusting mass flow
    if max_t_out_c is not None and t_out_c > max_t_out_c:
        t_out_c = max_t_out_c
        # Keep power constant and recalculate mass flow
        if t_out_c - t_in_c > 1e-3:
            mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
        else:
            # If temperature difference is too small, set mass flow to zero
            mdot_kg_per_s = 0
            q_fluid_kw = 0
            p_el_consumed_kw = 0

    # Apply ramp up/down constraints
    if not np.isnan(p_el_consumed_previous_kw):  # Constraint not applicable for the first timestep
        delta_p = (p_el_consumed_kw - p_el_consumed_previous_kw)
        if max_ramp_up_kw_per_s and delta_p > max_ramp_up_kw_per_s * time_step_s:
            # Limit ramp up speed
            p_el_consumed_kw = p_el_consumed_previous_kw + max_ramp_up_kw_per_s * time_step_s
            # Recalculate the affected outputs
            q_fluid_kw = p_el_consumed_kw * (efficiency_percent / 100)
            mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
        if max_ramp_down_kw_per_s and delta_p < -1 * max_ramp_down_kw_per_s * time_step_s:
            # Limit ramp down speed
            p_el_consumed_kw = p_el_consumed_previous_kw - max_ramp_down_kw_per_s * time_step_s
            # Recalculate the affected outputs
            q_fluid_kw = p_el_consumed_kw * (efficiency_percent / 100)
            mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))

    # Apply minimum power constraint
    if min_p_kw:
        if 1e-3 < p_el_consumed_kw < min_p_kw - 1e-3:
            # If the electrical power is too low but not null, apply min power constraint
            p_el_consumed_kw = min_p_kw
            q_fluid_kw = p_el_consumed_kw * (efficiency_percent / 100)
            # Always recalculate the fluid mass flow to maintain the requested temperature
            # This ensures we deliver the minimum power at the requested temperature
            if t_out_c - t_in_c > 1e-3:
                mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
            else:
                # If temperature difference is too small, we can't maintain minimum power
                # This is an edge case that should be handled by the system design
                pass
        elif p_el_consumed_kw < 1e-3 and allow_stop == False and not np.isnan(p_el_consumed_previous_kw) and p_el_consumed_previous_kw > 1e-3:
            # If power would drop to zero but previous power was non-zero and allow_stop is False, maintain minimum power
            p_el_consumed_kw = min_p_kw
            q_fluid_kw = p_el_consumed_kw * (efficiency_percent / 100)
            # Always recalculate the fluid mass flow to maintain the requested temperature
            if t_out_c - t_in_c > 1e-3:
                mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
            elif mdot_kg_per_s != 0:
                # If mass flow is zero but we have a temperature difference, use that
                mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
    
    # Check maximum power constraint
    if max_p_kw and p_el_consumed_kw > max_p_kw + 1e-3:  # ToDo: Check numba if max_p_kw Nan
        # If the consumed electrical power is too high, recalculate the output mass flow rate
        p_el_consumed_kw = max_p_kw
        q_fluid_kw = p_el_consumed_kw * (efficiency_percent / 100)
        # FixMe: Should update the output temperature or the mass flow rate ?
        # t_out_c = t_in_c + q_fluid_kw / (mdot_kg_per_s * cp_fluid_kj_per_kgk)
        mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))

    # Apply maximum temperature constraint after all other calculations by keeping power constant
    if max_t_out_c is not None and t_out_c > max_t_out_c:
        t_out_c = max_t_out_c
        # Keep power constant and recalculate mass flow
        if t_out_c - t_in_c > 1e-3:
            mdot_kg_per_s = q_fluid_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
        else:
            # If temperature difference is too small, set mass flow to zero
            mdot_kg_per_s = 0
            q_fluid_kw = 0
            p_el_consumed_kw = 0

    return q_fluid_kw, mdot_kg_per_s, t_in_c, t_out_c, p_el_consumed_kw


class ElectricBoilerController(BasicProsumerController):
    """
    Controller for electric boilers.

    :param prosumer: The prosumer object
    :param electric_boiler_object: The electric boiler object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "electric_boiler_controller"

    def __init__(self, prosumer, electric_boiler_object, order, level, in_service=True, index=None,
                 name=None, **kwargs):
        """
        Initializes the ElectricBoilerController.
        """
        super().__init__(prosumer, electric_boiler_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.fluid = prosumer.fluid

    def _calculate_electric_boiler(self, prosumer, mdot_kg_per_s, t_out_c, t_in_c):
        """
        Main method for Electric Boiler physical calculation during one time step

        :param mdot_kg_per_s: Mass flow rate in kg/s
        :param t_out_c: Output provided temperature to the feed pipe in °C
        :param t_in_c: Input temperature from return pipe in °C

        """
        cp_fluid_kj_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_out_c + t_in_c) / 2) / 1000
        efficiency_percent = self._get_element_param(prosumer, 'efficiency_percent')
        max_p_kw = self._get_element_param(prosumer, 'max_p_kw')
        min_p_kw = self._get_element_param(prosumer, 'min_p_kw')
        p_el_consumed_previous_kw = self.last_result.get('p_kw', np.nan)
        max_ramp_up_kw_per_s = self._get_element_param(prosumer, 'max_ramp_up_kw_per_s')
        max_ramp_down_kw_per_s = self._get_element_param(prosumer, 'max_ramp_down_kw_per_s')
        allow_stop = self._get_element_param(prosumer, 'allow_stop')
        if allow_stop == None or np.isnan(allow_stop):
            allow_stop = True

        max_t_out_c = self._get_element_param(prosumer, 'max_t_out_c')
        if np.isnan(max_t_out_c):
            max_t_out_c = None

        q_fluid_kw, mdot_kg_per_s, t_in_c, t_out_c, p_el_consumed_kw = _calculate_electric_boiler_temp(mdot_kg_per_s,
                                                                                                       t_out_c,
                                                                                                       t_in_c,
                                                                                                       cp_fluid_kj_per_kgk,
                                                                                                       efficiency_percent,
                                                                                                       max_p_kw,
                                                                                                       min_p_kw,
                                                                                                       p_el_consumed_previous_kw,
                                                                                                       max_ramp_up_kw_per_s,
                                                                                                       max_ramp_down_kw_per_s,
                                                                                                       self.resol,
                                                                                                       allow_stop,
                                                                                                       max_t_out_c)

        return q_fluid_kw, mdot_kg_per_s, t_in_c, t_out_c, p_el_consumed_kw

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

        assert not np.isnan(t_out_required_c), f"Electric Boiler {self.name} t_out_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_in_required_c), f"Electric Boiler {self.name} t_in_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_required_kg_per_s).any(), f"Electric Boiler {self.name} mdot_required_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert t_out_required_c >= t_in_required_c, f"Electric Boiler {self.name} t_out_required_c is lower than t_in_required_c for timestep {self.time} in prosumer {prosumer.name}"

        rerun = True
        nb_runs = 0
        while rerun:
            nb_runs += 1
            if nb_runs > 20:
                raise Exception("Heat Exchanger calculation did not converge after 100 iterations", self.name, self.time, prosumer.name)
            q_kw, mdot_delivered_kg_per_s, t_in_c, t_out_c, p_kw = self._calculate_electric_boiler(prosumer,
                                                                                                   mdot_required_kg_per_s,
                                                                                                   t_out_required_c,
                                                                                                   t_in_required_c)

            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_delivered_kg_per_s,
                                                                   mdot_tab_required_kg_per_s)
            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_delivered_kg_per_s < mdot_required_kg_per_s:
                # If the electric boiler is not able to deliver the required mass flow,
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
            efficiency_percent = self._get_element_param(prosumer, 'efficiency_percent')
            if mdot_used_kg_per_s > tol:
                t_out_c = t_in_c + q_kw / (cp_fluid_kj_per_kgk * mdot_used_kg_per_s)
                mdot_delivered_kg_per_s = mdot_used_kg_per_s
                # Reapply max_t_out_c constraint after mass/energy balance adjustment
                max_t_out_c = self._get_element_param(prosumer, 'max_t_out_c')
                if not np.isnan(max_t_out_c) and t_out_c > max_t_out_c:
                    t_out_c = max_t_out_c
                    # Recalculate power to maintain consistency
                    q_kw = mdot_delivered_kg_per_s * cp_fluid_kj_per_kgk * (t_out_c - t_in_c)
                    # Recalculate electric power to maintain consistency with new thermal power
                    p_kw = q_kw / (efficiency_percent / 100)
            elif -tol < mdot_used_kg_per_s < tol and q_kw > tol:
                mdot_delivered_kg_per_s = q_kw / (cp_fluid_kj_per_kgk * (t_out_c - t_in_c))
                # update result_mdot_tab_kg_per_s with the new mass flow, distribute evenly if several responders
                if len(result_mdot_tab_kg_per_s) > 0:
                    result_mdot_tab_kg_per_s = np.array(result_mdot_tab_kg_per_s) + (mdot_delivered_kg_per_s - mdot_used_kg_per_s) / len(result_mdot_tab_kg_per_s)
                else:
                    result_mdot_tab_kg_per_s = np.array([mdot_delivered_kg_per_s])

        assert q_kw >= 0, f"Electric Boiler {self.name} q_kw is negative ({q_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        assert p_kw >= 0, f"Electric Boiler {self.name} p_kw is negative ({p_kw}) for timestep {self.time} in prosumer {prosumer.name}"

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        result = np.array([[q_kw, mdot_delivered_kg_per_s, t_in_c, t_out_c, p_kw]])

        self.last_result = {
            "q_kw": q_kw,
            "mdot_delivered_kg_per_s": mdot_delivered_kg_per_s,
            "t_in_c": t_in_c,
            "t_out_c": t_out_c,
            "p_kw": p_kw,
        }

        self.finalize(prosumer, result, result_fluid_mix)

        self.applied = True
