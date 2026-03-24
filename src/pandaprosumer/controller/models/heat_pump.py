"""
Module containing the HeatPumpController class.
"""

import numpy as np
from math import log

from pandapipes import call_lib

from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.controller.base import BasicProsumerController


class HeatPumpController(BasicProsumerController):
    """
    Controller for heat pumps.

    :param prosumer: The prosumer object
    :param heat_pump_object: The heat pump object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "heat_pump_controller"

    def __init__(self, prosumer, heat_pump_object, order, level, in_service=True, index=None, name=None, **kwargs):
        """
        Initializes the HeatPumpController.
        """
        super().__init__(prosumer, heat_pump_object, order=order, level=level, in_service=in_service, index=index,
                         name=name, **kwargs)

        cond_fluid = self._get_element_param(prosumer, 'cond_fluid')
        evap_fluid = self._get_element_param(prosumer, 'evap_fluid')
        if cond_fluid and cond_fluid != prosumer.fluid.name:
            self.cond_fluid = call_lib(cond_fluid)
        else:
            self.cond_fluid = prosumer.fluid
        if evap_fluid and evap_fluid != prosumer.fluid.name:
            self.evap_fluid = call_lib(evap_fluid)
        else:
            self.evap_fluid = prosumer.fluid
        # FixMe: Does it works when evap fluid is a gas (e.g. air) ?
        self.t_previous_evap_out_c = np.nan
        self.t_previous_evap_in_c = np.nan
        self.mdot_previous_evap_kg_per_s = np.nan
        
        # Store the previous compressor power for applying ramp up / ramp down speed constraints
        self.p_comp_previous_kw = np.nan

    @property
    def _t_evap_in_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        else:
            return self._get_input("t_evap_in_c")

    @property
    def _mdot_evap_in_kg_per_s(self):
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
        if not np.isnan(self.t_previous_evap_out_c):
            return self.t_previous_evap_in_c, self.t_previous_evap_out_c, self.mdot_previous_evap_kg_per_s
        else:
            delta_t_hot_default_c = self._get_element_param(prosumer, 'delta_t_hot_default_c')
            return self.t_m_to_receive_for_t(prosumer, t_feed_demand_c - delta_t_hot_default_c)

    def t_m_to_receive_for_t(self, prosumer, t_feed_c):
        """
        For a given feed temperature in °C, calculate the required feed mass flow and the expected return temperature
        if this feed temperature is provided.

        :param prosumer: The prosumer object
        :param t_feed_c: The feed temperature
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_cond_out_required_c, t_cond_in_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_cond_required_kg_per_s = np.sum(mdot_tab_required_kg_per_s)
        if mdot_cond_required_kg_per_s == 0:
            return t_cond_out_required_c, t_cond_in_required_c, 0
        pinch_c = self._get_element_param(prosumer, 'pinch_c')

        # FixMe: Do we need this function or use delta_t_hot_default_c in t_m_to_receive ?
        # FixMe: cop < 0 if t_cond_out_c < t_evap_in_c (t_feed_c)

        (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
         mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
         mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                    mdot_cond_required_kg_per_s,
                                                                                    t_cond_out_required_c,
                                                                                    t_cond_in_required_c,
                                                                                    t_feed_c,
                                                                                    pinch_c)
        if not np.isnan(self.t_previous_evap_out_c):
            return self.t_previous_evap_in_c, self.t_previous_evap_out_c, self.mdot_previous_evap_kg_per_s
        return t_feed_c, t_evap_out_c, mdot_evap_kg_per_s
    
    def _ramp_down(self, prosumer, t_cond_out_c, t_cond_in_c, t_evap_in_c, carnot_efficiency, default_delta_t_evap_c, max_decrease, pinch_c):
         # Need to ramp down gradually - maintain proportional operation
        p_comp_kw = max(0, self.p_comp_previous_kw - max_decrease)

        # Calculate operating percentage compared to previous state
        operating_ratio = p_comp_kw / self.p_comp_previous_kw

        # Maintain proportional temperatures (percentage of previous delta)
        # FIXME: use self.last_result['t_previous_evap_out_c'] instead
        if not np.isnan(self.t_previous_evap_out_c) and not np.isnan(self.t_previous_evap_in_c):
            delta_t_evap_previous = self.t_previous_evap_in_c - self.t_previous_evap_out_c
            delta_t_evap_c = delta_t_evap_previous * operating_ratio
            t_evap_out_c = t_evap_in_c - delta_t_evap_c
        else:
            # Fallback: use default delta_t_evap_c
            delta_t_evap_c = default_delta_t_evap_c
            t_evap_out_c = t_evap_in_c - delta_t_evap_c * operating_ratio

        # Use proportional COP from previous calculation (stored in last_result)
        if hasattr(self, 'last_result') and 'cop_hp' in self.last_result:
            cop_hp = self.last_result['cop_hp']
        else:
            # Fallback: calculate basic COP
            cop_carnot = (t_cond_in_c + CELSIUS_TO_K) / max(1, (t_cond_in_c - t_evap_in_c))
            cop_hp = carnot_efficiency * cop_carnot

        # Recalculate heat flows
        q_cond_kw = p_comp_kw * cop_hp
        q_evap_kw = q_cond_kw - p_comp_kw

        # Maintain proportional condenser delta T
        if t_cond_out_c - t_cond_in_c > 1e-3:
            delta_t_cond = (t_cond_out_c - t_cond_in_c) * operating_ratio
        else:
            delta_t_cond_previous_c = self.last_result.get('t_cond_out_c', np.nan) - self.last_result.get('t_cond_in_c', np.nan)
            delta_t_cond = delta_t_cond_previous_c
            t_cond_out_c = t_cond_in_c + delta_t_cond
            cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2) / 1000
            mdot_cond_kg_per_s = q_cond_kw / (cp_cond_kj_per_kgk * delta_t_cond) if delta_t_cond > 0.1 else 0
            return self._calculate_heat_pump(prosumer,
                                             mdot_cond_kg_per_s,
                                             t_cond_out_c,
                                             t_cond_in_c,
                                             t_evap_in_c,
                                             pinch_c)
        t_cond_out_c = t_cond_in_c + delta_t_cond

        # Calculate mass flows
        cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2) / 1000
        mdot_cond_kg_per_s = q_cond_kw / (cp_cond_kj_per_kgk * delta_t_cond) if delta_t_cond > 0.1 else 0

        cp_evap_kj_per_kgk = self.evap_fluid.get_heat_capacity(CELSIUS_TO_K + (t_evap_in_c + t_evap_out_c) / 2) / 1000
        mdot_evap_kg_per_s = q_evap_kw / (cp_evap_kj_per_kgk * delta_t_evap_c) if delta_t_evap_c > 0.1 else 0

        return (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c)

    def _calculate_heat_pump(self, prosumer, mdot_cond_kg_per_s, t_cond_out_c, t_cond_in_c, t_evap_in_c, pinch_c):
        """
        Main method for Heat Pump physical calculation during one time step
        FixMe: Use cop_hp or cop_lz ? (Need electric consumption data)
        FixMe: Check how the out of range cases should be manage (need data ?)
        """
        cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2) / 1000
        carnot_efficiency = self._get_element_param(prosumer, 'carnot_efficiency')

        # 1. Calculate power of condenser
        q_cond_kw = mdot_cond_kg_per_s * cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c)

        # 2. Calculate temp_out_evap in °C
        t_evap_out_c = t_evap_in_c - self._get_element_param(prosumer, 'delta_t_evap_c')
        cp_evap_kj_per_kgk = self.evap_fluid.get_heat_capacity(CELSIUS_TO_K + (t_evap_in_c + t_evap_out_c) / 2) / 1000

        if t_cond_out_c <= t_cond_in_c or t_evap_in_c <= t_evap_out_c:
            # If there is no demand on the condenser, the Heat Pump is not running
            # We have to take into account ramp down constraints here
            max_ramp_down_kw_per_s = self._get_element_param(prosumer, 'max_ramp_down_kw_per_s')

            if not np.isnan(self.p_comp_previous_kw) and self.p_comp_previous_kw > 0 and max_ramp_down_kw_per_s:
                time_step_s = self.resol
                max_decrease = max_ramp_down_kw_per_s * time_step_s
                delta_p = 0 - self.p_comp_previous_kw

                if delta_p < -max_decrease:
                    # Need to ramp down gradually - maintain proportional operation
                    default_delta_t_evap_c = self._get_element_param(prosumer, 'delta_t_evap_c')
                    return self._ramp_down(prosumer, t_cond_out_c, t_cond_in_c, t_evap_in_c, carnot_efficiency, default_delta_t_evap_c, max_decrease, pinch_c)
                   
            # Complete shutdown (no ramp constraint or already at zero)
            return (0, 0, 0, 0,
                    mdot_cond_kg_per_s, t_cond_in_c, t_cond_in_c,
                    0, t_evap_in_c, t_evap_in_c)

        # 3. Calculate carnot cop
        # FixMe: Why using the condenser output temperature ?
        cop_carnot = (t_cond_out_c + pinch_c + CELSIUS_TO_K) / (t_cond_out_c - t_evap_in_c)

        # 4. Calculate cop of heat pump
        cop_hp = carnot_efficiency * cop_carnot

        # 5. Calculate the compressor power power_comp
        p_comp_kw = q_cond_kw / cop_hp
        
        # Check COP calculation mode
        mode = self._get_element_param(prosumer, 'mode')
        if mode:
            mode = str(mode).lower()  # Make case insensitive
            if mode == 'lorenz':
                # Calculate Lorenz cop
                mean_th_c = (t_cond_out_c - t_cond_in_c) / log((t_cond_out_c + CELSIUS_TO_K) / (t_cond_in_c + CELSIUS_TO_K))
                mean_tc_c = (t_evap_in_c - t_evap_out_c) / log((t_evap_in_c + CELSIUS_TO_K) / (t_evap_out_c + CELSIUS_TO_K))
                cop_lorenz = mean_th_c / (mean_th_c - mean_tc_c)
                # Calculate cop of heat pump with Lorenz
                cop_hp_lz = carnot_efficiency * cop_lorenz
                p_comp_lz_kw = q_cond_kw / cop_hp_lz
                # Use Lorenz compressor power
                p_comp_kw = p_comp_lz_kw
            # else: default 'carnot' mode already calculated above

        # 6. Calculate power of evaporator Q_evap
        q_evap_kw = q_cond_kw - p_comp_kw

        # 7. Calculate mass flow of evaporator m_evap
        mdot_evap_kg_per_s = q_evap_kw / (cp_evap_kj_per_kgk * abs(t_evap_out_c - t_evap_in_c))

        # 8. Check parameters
        max_cop = self._get_element_param(prosumer, 'max_cop')
        if max_cop and cop_hp > max_cop + 1e-3:
            # If the cop is too high, consider calculate which condenser output temperature the HP can reach
            # with the max cop
            t_cond_out_c = (max_cop * (t_evap_in_c + CELSIUS_TO_K) / (max_cop - carnot_efficiency)) - CELSIUS_TO_K
            (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
             mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
             mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                        mdot_cond_kg_per_s,
                                                                                        t_cond_out_c,
                                                                                        t_cond_in_c,
                                                                                        t_evap_in_c,
                                                                                        pinch_c)
        max_t_cond_out_c = self._get_element_param(prosumer, 'max_t_cond_out_c')
        if max_t_cond_out_c and t_cond_out_c > max_t_cond_out_c + 1e-3:
            # If the condenser output temperature is too high, recalculate everything with the max temperature
            t_cond_out_c = max_t_cond_out_c
            (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
             mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
             mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                        mdot_cond_kg_per_s,
                                                                                        t_cond_out_c,
                                                                                        t_cond_in_c,
                                                                                        t_evap_in_c,
                                                                                        pinch_c)
        min_p_comp_kw = self._get_element_param(prosumer, 'min_p_comp_kw')
        if min_p_comp_kw and p_comp_kw < min_p_comp_kw - 1e-3:
            # If the compressor power is too low, the Heat Pump cannot run
            if self.p_comp_previous_kw < p_comp_kw:
                # If it was off before, it stays off
                return 0, 0, 0, 0, 0, t_cond_in_c, t_cond_in_c, 0, t_evap_in_c, t_evap_in_c
            else:
                # If it was on, it stays on at the minimum compressor power
                p_comp_kw = min_p_comp_kw
                mdot_cond_kg_per_s = p_comp_kw * cop_hp / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))
                (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                            mdot_cond_kg_per_s,
                                                                                            t_cond_out_c,
                                                                                            t_cond_in_c,
                                                                                            t_evap_in_c,
                                                                                            pinch_c)
                

        max_p_comp_kw = self._get_element_param(prosumer, 'max_p_comp_kw')
        if max_p_comp_kw and p_comp_kw > max_p_comp_kw + 1e-3:
            # If the compressor power is too high, consider that only the condenser mass flow will be affected
            # (not the temperatures) and recalculate everything
            mdot_cond_kg_per_s = max_p_comp_kw * cop_hp / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))
            (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
             mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
             mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                        mdot_cond_kg_per_s,
                                                                                        t_cond_out_c,
                                                                                        t_cond_in_c,
                                                                                        t_evap_in_c,
                                                                                        pinch_c)
        
        # 9. Apply ramp up/down constraints
        if not np.isnan(self.p_comp_previous_kw):  # No constraint for the first timestep
            max_ramp_up_kw_per_s = self._get_element_param(prosumer, 'max_ramp_up_kw_per_s')
            max_ramp_down_kw_per_s = self._get_element_param(prosumer, 'max_ramp_down_kw_per_s')
            delta_p = (p_comp_kw - self.p_comp_previous_kw)
            delta_t_cond_previous_c = self.last_result.get('t_cond_out_c', np.nan) - self.last_result.get('t_cond_in_c', np.nan)
            if max_ramp_up_kw_per_s and delta_p > max_ramp_up_kw_per_s * self.resol:
                # Limit ramp up
                p_comp_kw = self.p_comp_previous_kw + max_ramp_up_kw_per_s * self.resol
                # Recalculate only the affected outputs
                q_cond_kw = p_comp_kw * cop_hp
                if t_cond_out_c - t_cond_in_c > 1e-3:
                    mdot_cond_kg_per_s = q_cond_kw / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))
                    q_evap_kw = q_cond_kw - p_comp_kw
                    mdot_evap_kg_per_s = q_evap_kw / (cp_evap_kj_per_kgk * abs(t_evap_out_c - t_evap_in_c))
                else:
                    t_cond_out_c = t_cond_in_c + delta_t_cond_previous_c
                    mdot_cond_kg_per_s = q_cond_kw / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))
                    (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                     mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                     mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                                mdot_cond_kg_per_s,
                                                                                                t_cond_out_c,
                                                                                                t_cond_in_c,
                                                                                                t_evap_in_c,
                                                                                                pinch_c)

            elif max_ramp_down_kw_per_s and delta_p < -1 * max_ramp_down_kw_per_s * self.resol:
                # Limit ramp down
                p_comp_kw = self.p_comp_previous_kw - max_ramp_down_kw_per_s * self.resol
                # Recalculate only the affected outputs
                q_cond_kw = p_comp_kw * cop_hp
                if t_cond_out_c - t_cond_in_c > 1e-3:
                    mdot_cond_kg_per_s = q_cond_kw / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))
                    q_evap_kw = q_cond_kw - p_comp_kw
                    mdot_evap_kg_per_s = q_evap_kw / (cp_evap_kj_per_kgk * abs(t_evap_out_c - t_evap_in_c))
                else:
                    t_cond_out_c = t_cond_in_c + delta_t_cond_previous_c
                    mdot_cond_kg_per_s = q_cond_kw / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))
                    (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                     mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                     mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                                mdot_cond_kg_per_s,
                                                                                                t_cond_out_c,
                                                                                                t_cond_in_c,
                                                                                                t_evap_in_c,
                                                                                                pinch_c)

        return (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c)

    def _calculate_heat_pump_reverse(self, prosumer, mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c, t_cond_in_c, t_cond_out_c):
        """
        Main method for Heat Pump physical calculation during one time step
        """
        cp_evap_kj_per_kgk = self.cond_fluid.get_heat_capacity(CELSIUS_TO_K + (t_evap_in_c + t_evap_out_c) / 2) / 1000
        carnot_efficiency = self._get_element_param(prosumer, 'carnot_efficiency')
        pinch_c = self._get_element_param(prosumer, 'pinch_c')

        q_evap_kw = mdot_evap_kg_per_s * cp_evap_kj_per_kgk * (t_evap_in_c - t_evap_out_c)

        # FixMe: Is it okay to use the condenser input temperature ?
        cop_carnot = (t_cond_out_c + pinch_c + CELSIUS_TO_K) / (t_cond_out_c - t_evap_in_c)
        cop_hp = carnot_efficiency * cop_carnot
        p_comp_kw = q_evap_kw / (cop_hp - 1)
        q_cond_kw = q_evap_kw + p_comp_kw

        # FixMe: Should set the condenser output temperature or mass flow ?
        cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2) / 1000
        mdot_cond_kg_per_s = p_comp_kw * cop_hp / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))

        return (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c)

    def _save_state(self):
        self._backup_state = {
            "t_previous_evap_out_c": self.t_previous_evap_out_c,
            "t_previous_evap_in_c": self.t_previous_evap_in_c,
            "mdot_previous_evap_kg_per_s": self.mdot_previous_evap_kg_per_s,
            "p_comp_previous_kw": self.p_comp_previous_kw,
        }

    def _restore_state(self):
        if hasattr(self, "_backup_state"):
            self.t_previous_evap_out_c = self._backup_state["t_previous_evap_out_c"]
            self.t_previous_evap_in_c = self._backup_state["t_previous_evap_in_c"]
            self.mdot_previous_evap_kg_per_s = self._backup_state["mdot_previous_evap_kg_per_s"]
            self.p_comp_previous_kw = self._backup_state["p_comp_previous_kw"]

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if not prosumer.rerun:
            self._save_state()
        else:
            self._restore_state()

        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[self.obj.element_index[0]].in_service):
            self.applied = True
            return

        super().control_step(prosumer)

        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        t_cond_out_required_c, t_cond_in_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_cond_required_kg_per_s = np.sum(mdot_tab_required_kg_per_s)

        assert not np.isnan(mdot_cond_required_kg_per_s), f"Heat Pump {self.name} mdot_cond_required_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_cond_out_required_c), f"Heat Pump {self.name} t_cond_out_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_cond_in_required_c), f"Heat Pump {self.name} t_cond_in_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(self._t_evap_in_c), f"Heat Pump {self.name} t_evap_in_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert t_cond_out_required_c >= t_cond_in_required_c, f"Heat Pump {self.name} t_cond_out_required_c < t_cond_in_required_c for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_cond_required_kg_per_s >= 0, f"Heat Pump {self.name} mdot_cond_kg_per_s is negative ({mdot_cond_required_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"

        rerun = True
        while rerun:
            pinch_c = self._get_element_param(prosumer, 'pinch_c')

            (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
             mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
             mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                        mdot_cond_required_kg_per_s,
                                                                                        t_cond_out_required_c,
                                                                                        t_cond_in_required_c,
                                                                                        self._t_evap_in_c,
                                                                                        pinch_c)
            if not np.isnan(self._mdot_evap_in_kg_per_s):
                # If the evaporator is fed with a fixed mass flow (not free air)
                if mdot_evap_kg_per_s > self._mdot_evap_in_kg_per_s:
                    # If the evaporator mass flow is higher than the one required by the Heat Pump,
                    # recalculate the secondary mass flow to reduce the heat demand to reduce the evaporator mass flow
                    cp_evap_kj_per_kgk = self.evap_fluid.get_heat_capacity(CELSIUS_TO_K + (t_evap_in_c + t_evap_out_c) / 2) / 1000
                    cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2) / 1000
                    q_evap_kw = self._mdot_evap_in_kg_per_s * (cp_evap_kj_per_kgk * abs(t_evap_out_c - t_evap_in_c))
                    p_comp_kw = q_cond_kw - q_evap_kw
                    mdot_cond_kg_per_s = p_comp_kw * cop_hp / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))

                    (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                     mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                     mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump_reverse(prosumer,
                                                                                                        self._mdot_evap_in_kg_per_s,
                                                                                                        self._t_evap_in_c,
                                                                                                        t_evap_out_c,
                                                                                                        t_cond_in_c,
                                                                                                        t_cond_out_c)
                elif mdot_evap_kg_per_s < self._mdot_evap_in_kg_per_s:
                    # If the evaporator mass flow is lower than the one required by the Heat Pump,
                    # model a bypass on the evaporator side where the extra mass flow doesn't exchange heat.
                    # Recalculate the evaporator output temperature
                    mdot_bypass_kg_per_s = self._mdot_evap_in_kg_per_s - mdot_evap_kg_per_s
                    t_bypass_c = t_evap_in_c
                    t_evap_out_c = (t_bypass_c * mdot_bypass_kg_per_s + t_evap_out_c * mdot_evap_kg_per_s) / self._mdot_evap_in_kg_per_s
                    mdot_evap_kg_per_s = self._mdot_evap_in_kg_per_s

            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_cond_kg_per_s,
                                                                   mdot_tab_required_kg_per_s)

            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_cond_kg_per_s < mdot_cond_required_kg_per_s:
                # FixMe: Can't test this case in a single model test without mapping (no responders)
                # If the heat Pump is not able to deliver the required mass flow,
                # recalculate the condenser input temperature, considering that all the downstream elements will be
                # still return the same temperature, even if the mass flow delivered to them by the Heat Pump is lower
                t_return_tab_c = self.get_treturn_tab_c(prosumer)
                if abs(mdot_cond_kg_per_s) > 1e-8:
                    t_cond_in_new_c = np.sum(result_mdot_tab_kg_per_s * t_return_tab_c) / mdot_cond_kg_per_s
                else:
                    t_cond_in_new_c = t_cond_in_required_c
                if abs(t_cond_in_new_c - t_cond_in_required_c) > 1:
                    # If this recalculation changes the condenser input temperature, rerun the calculation
                    # with the new temperature
                    t_cond_in_required_c = t_cond_in_new_c
                    rerun = True

        # After merit-order capping, ensure mass and energy balance at the interface.
        # If the effective condenser mass flow differs from what the model used, re-run the
        # heat pump physics with the new mdot_cond so COP, p_comp, t_cond_out, etc. are consistent.
        mdot_used_kg_per_s = np.sum(result_mdot_tab_kg_per_s)
        tol = 1e-9
        mdot_cond_new = None
        if abs(mdot_cond_kg_per_s - mdot_used_kg_per_s) > tol:
            if mdot_used_kg_per_s > tol:
                mdot_cond_new = mdot_used_kg_per_s
            elif -tol < mdot_used_kg_per_s < tol and q_cond_kw > tol:
                cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(
                    CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2
                ) / 1000
                mdot_cond_new = q_cond_kw / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))
                # distribute new mass flow evenly to responders
                if len(result_mdot_tab_kg_per_s) > 0:
                    result_mdot_tab_kg_per_s = np.array(result_mdot_tab_kg_per_s) + (
                        mdot_cond_new - mdot_used_kg_per_s
                    ) / len(result_mdot_tab_kg_per_s)
                else:
                    result_mdot_tab_kg_per_s = np.array([mdot_cond_new])

        if mdot_cond_new is not None:
            pinch_c = self._get_element_param(prosumer, 'pinch_c')
            (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
             mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
             mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(
                prosumer,
                mdot_cond_new,
                t_cond_out_required_c,
                t_cond_in_required_c,
                self._t_evap_in_c,
                pinch_c,
            )

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_cond_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        result = np.array([[q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                            mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                            mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c]])

        self.last_result = {
            "q_cond_kw": q_cond_kw,
            "p_comp_kw": p_comp_kw,
            "q_evap_kw": q_evap_kw,
            "cop_hp": cop_hp,
            "mdot_cond_kg_per_s": mdot_cond_kg_per_s,
            "t_cond_in_c": t_cond_in_c,
            "t_cond_out_c": t_cond_out_c,
            "mdot_evap_kg_per_s": mdot_evap_kg_per_s,
            "t_evap_in_c": t_evap_in_c,
            "t_evap_out_c": t_evap_out_c,
        }

        assert cop_hp >= 0, f"Heat Pump {self.name} COP is negative ({cop_hp}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_evap_kg_per_s >= 0, f"Heat Pump {self.name} mdot_evap_kg_per_s is negative ({mdot_evap_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_cond_kg_per_s >= 0, f"Heat Pump {self.name} mdot_cond_kg_per_s is negative ({mdot_cond_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert p_comp_kw >= 0, f"Heat Pump {self.name} p_comp_kw is negative ({p_comp_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        assert q_cond_kw >= 0, f"Heat Pump {self.name} q_cond_kw is negative ({q_cond_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        assert q_evap_kw >= 0, f"Heat Pump {self.name} q_evap_kw is negative ({q_evap_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        max_t_cond_out_c = self._get_element_param(prosumer, 'max_t_cond_out_c')
        if not np.isnan(max_t_cond_out_c):
            assert t_cond_out_c <= max_t_cond_out_c, f"Heat Pump {self.name} t_cond_out_c is higher than the maximum ({t_cond_out_c} > {max_t_cond_out_c}) for timestep {self.time} in prosumer {prosumer.name}"

        if np.isnan(self.t_keep_return_c) or mdot_evap_kg_per_s == 0 or abs(t_evap_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0:
            # If the actual output temperature is the same as the promised one, the storage is correctly applied
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_evap_out_c = np.nan  # FIXME: should be nan ?
            self.t_previous_evap_in_c = np.nan
            self.mdot_previous_evap_kg_per_s = np.nan
            self.p_comp_previous_kw = p_comp_kw  # Store the last compressor power value
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            self._unapply_initiators(prosumer)
            self.t_previous_evap_out_c = t_evap_out_c
            self.t_previous_evap_in_c = t_evap_in_c
            self.mdot_previous_evap_kg_per_s = mdot_evap_kg_per_s
            # self.p_comp_previous_kw = p_comp_kw
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
