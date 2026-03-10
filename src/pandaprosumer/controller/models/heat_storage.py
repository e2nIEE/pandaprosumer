"""
Module containing the HeatStorageController class.

The heat storage controller supports two connection modes:
- **GenericMapping**: power-only interface (q_received_kw input; soc, q_delivered_kw output).
- **FluidMixMapping**: temperature and mass-flow interface (uniform tank model; optional
  min_temp_c / max_temp_c to derive SOC from tank temperature).
"""

import numpy as np
import pandas as pd
import warnings

from pandaprosumer import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


def _calculate_heat_storage(prosumer, mdot_demand_kg_per_s,
                            t_received_in_c, t_demand_out_c,
                            t_demand_in_c, t_discharge_out_c,
                            mdot_received_kg_per_s, t_charge_out,
                            current_temp, capacity_kg):
    # Check if we have incoming flow (initiator power)
    has_incoming_flow = not (
                np.isnan(mdot_received_kg_per_s) or np.isnan(t_received_in_c)) and mdot_received_kg_per_s > 0

    # Check if we have demand
    has_demand = mdot_demand_kg_per_s > 0 and current_temp > t_demand_in_c

    if has_incoming_flow:
        # Case 1: We have incoming flow (initiator power)
        if has_demand:
            cp_j_per_kgk = prosumer.get_cp_fluid_j_per_kgk(current_temp)

            # Case 1a: We have both incoming flow and demand
            # First, try to satisfy demand directly from incoming flow
            # Calculate energy available from incoming flow
            q_available_from_initiator_kw = mdot_received_kg_per_s * (
                        t_received_in_c - t_demand_in_c) * cp_j_per_kgk / 1000

            if q_available_from_initiator_kw >= 0:
                # Incoming flow can satisfy demand directly
                # Use incoming flow to satisfy demand
                mdot_to_deliver_kg_per_s = mdot_demand_kg_per_s
                q_delivered_kw = mdot_to_deliver_kg_per_s * (t_received_in_c - t_demand_in_c) * cp_j_per_kgk / 1000
                t_out_c = t_received_in_c  # Output temperature is incoming temperature

                # Calculate remaining flow after satisfying demand
                remaining_mdot_kg_per_s = mdot_received_kg_per_s - mdot_to_deliver_kg_per_s

                if remaining_mdot_kg_per_s > 0:
                    # Case 1a-i: Extra incoming flow available - store it in tank
                    # Calculate energy to store
                    q_to_store_kw = remaining_mdot_kg_per_s * (t_received_in_c - current_temp) * cp_j_per_kgk / 1000

                    # Update tank temperature based on stored energy
                    if capacity_kg > 0:
                        energy_stored_kj = q_to_store_kw * 3600
                        delta_t = energy_stored_kj / (capacity_kg * cp_j_per_kgk)
                        new_temp = current_temp + delta_t

                        # Apply temperature limits
                        min_t = self._get_element_param(prosumer, "min_temp_c")
                        max_t = self._get_element_param(prosumer, "max_temp_c")
                        if min_t is not None and max_t is not None and max_t > min_t:
                            new_temp = float(np.clip(new_temp, min_t, max_t))

                        t_tank_c = new_temp

                    # For remaining flow, mix with tank
                    mdot_to_deliver_kg_per_s += remaining_mdot_kg_per_s
                    t_out_c = current_temp
            else:
                # Case 1a-ii: Incoming flow cannot satisfy demand, need to use stored energy
                # Use all incoming flow first
                mdot_to_deliver_kg_per_s = mdot_received_kg_per_s
                q_delivered_kw = mdot_to_deliver_kg_per_s * (t_received_in_c - t_demand_in_c) * cp_j_per_kgk / 1000
                t_out_c = t_received_in_c

                # Calculate remaining demand
                remaining_demand_kg_per_s = mdot_demand_kg_per_s - mdot_to_deliver_kg_per_s

                if remaining_demand_kg_per_s > 0 and current_temp > t_demand_in_c:
                    # Use stored energy to satisfy remaining demand
                    additional_mdot = remaining_demand_kg_per_s
                    mdot_to_deliver_kg_per_s += additional_mdot

                    # Energy from stored heat
                    additional_q = additional_mdot * (current_temp - t_demand_in_c) * cp_j_per_kgk / 1000
                    q_delivered_kw += additional_q

                    # Update tank temperature based on energy used
                    energy_used_kj = additional_q * 3600
                    if capacity_kg > 0 and energy_used_kj > 0:
                        delta_t = energy_used_kj / (capacity_kg * cp_j_per_kgk)
                        t_tank_c = max(current_temp - delta_t, t_demand_in_c)

                    t_out_c = current_temp
        else:
            # Case 1b: We have incoming flow but no demand - store all incoming energy
            q_delivered_kw, mdot_to_deliver_kg_per_s, t_out_c, new_t = self._calculate_uniform_tank_step(
                prosumer, mdot_received_kg_per_s, t_received_in_c
            )
            # When charging (q_delivered_kw < 0), we still need to pass through the flow
            # but q_delivered_kw remains negative to indicate charging
            if q_delivered_kw < 0:
                # Charging: pass through the incoming flow but q_delivered_kw is negative
                mdot_to_deliver_kg_per_s = mdot_received_kg_per_s
            t_tank_c = new_t
    elif has_demand:
        # Case 2: No incoming flow but we have demand - discharge from storage
        mdot_to_deliver_kg_per_s = mdot_demand_kg_per_s
        t_out_c = current_temp

        # Calculate energy delivered and update tank temperature
        q_delivered_kw = mdot_to_deliver_kg_per_s * (t_out_c - t_demand_in_c) * cp_j_per_kgk / 1000

        # Update tank temperature based on energy delivered
        energy_delivered_kj = q_delivered_kw * 3600
        if capacity_kg > 0 and energy_delivered_kj > 0:
            delta_t = energy_delivered_kj / (capacity_kg * cp_j_per_kgk)
            t_tank_c = max(current_temp - delta_t, t_demand_in_c)
    else:
        # Case 3: No flow, no delivery
        q_delivered_kw = 0.0
        mdot_to_deliver_kg_per_s = 0.0

    # Calculate heat losses (after determining energy flows)
    self._calculate_heat_losses(prosumer)

    # Calculate t_received_out_c - temperature returned to initiator
    # Calculate t_received_out_c - temperature returned to initiator
    # Logic: if only supplying demand: demand return temp; if only charging: initial tank temp; if mix: weighted average

    if has_incoming_flow and not has_demand:
        # Case: Incoming flow but no demand - could be charging or return flow from discharge
        if t_received_in_c > current_temp:
            # Charging scenario: hot water coming in to charge tank
            t_received_out_c = current_temp
        else:
            # Discharging scenario: cold return water coming back from demand
            # Return the incoming temperature (which is the return temperature)
            t_received_out_c = t_received_in_c
    elif has_incoming_flow and has_demand:
        # Case: Mix scenario - need to determine if this is charging, discharging, or both
        if t_received_in_c > current_temp:
            # Case: Incoming flow is hotter than tank - this is charging scenario
            # The initiator is providing hot water to charge the tank
            if mdot_to_deliver_kg_per_s > 0:
                # Calculate the portion used for demand vs charging
                mdot_for_demand = min(mdot_demand_kg_per_s, mdot_received_kg_per_s)
                mdot_for_charging = mdot_to_deliver_kg_per_s - mdot_for_demand

                if mdot_for_charging > 0:
                    # Mix of both: weighted average
                    t_received_out_c = (
                                               mdot_for_demand * t_demand_in_c +
                                               mdot_for_charging * current_temp
                                       ) / mdot_to_deliver_kg_per_s
                else:
                    # Only demand: return demand return temperature
                    t_received_out_c = t_demand_in_c
            else:
                t_received_out_c = current_temp
        else:
            # Case: Incoming flow is colder than tank - this is discharging scenario
            # The initiator is providing cold return water while we deliver hot water
            # Return the demand return temperature (which is the incoming temperature)
            t_received_out_c = t_received_in_c
    elif has_demand:
        # Case: Only discharging - return demand return temperature
        t_received_out_c = t_demand_in_c
    else:
        # Case: No flow - return current tank temperature
        t_received_out_c = self._temperature

        # Update SOC from temperature
        soc_fluid = self._soc_from_temperature(prosumer)
        if soc_fluid is not None and not np.isnan(soc_fluid):
            self._soc = soc_fluid
        soc_out = float(self._soc) if not np.isnan(self._soc) else 0.0
        q_delivered_kw = float(q_delivered_kw)

        # Calculate charging and delivered power (both should be positive)
        if q_delivered_kw < 0:
            q_ch_kw = -q_delivered_kw  # Positive charging power
            q_delivered_kw_positive = 0.0  # No delivery when charging
            q_discharge_kw = 0.0  # No discharge when charging
            q_charge_kw = q_ch_kw  # Charging power
        else:
            q_ch_kw = 0.0  # No charging when delivering
            q_delivered_kw_positive = q_delivered_kw  # Positive delivered power
            q_discharge_kw = q_delivered_kw  # Discharge power when delivering
            q_charge_kw = 0.0  # No charging when discharging

        # Determine temperatures for charge and discharge
        if has_incoming_flow and q_charge_kw > 0:
            # Charging scenario
            t_charge_in_c = t_received_in_c  # Incoming temperature
            t_charge_out_c = self._temperature  # Tank temperature after charging
            t_discharge_in_c = np.nan  # No discharge
            t_discharge_out_c = np.nan  # No discharge
            mdot_charge_kg_per_s = mdot_received_kg_per_s  # Charge mass flow
            mdot_discharge_kg_per_s = 0.0  # No discharge mass flow
        elif q_discharge_kw > 0:
            # Discharging scenario (with or without explicit demand)
            t_charge_in_c = np.nan  # No charging
            t_charge_out_c = np.nan  # No charging
            # When discharging, incoming flow is return water, outgoing flow is hot water from tank
            if has_incoming_flow:
                t_discharge_in_c = t_received_in_c  # Incoming return water temperature
            else:
                t_discharge_in_c = np.nan  # No incoming flow
            # Use initial temperature for discharge output (what's delivered to demand)
            t_discharge_out_c = prosumer if prosumer is not None else self._temperature
            mdot_charge_kg_per_s = 0.0  # No charge mass flow
            mdot_discharge_kg_per_s = mdot_to_deliver_kg_per_s  # Discharge mass flow
        else:
            # No charging or discharging
            t_charge_in_c = np.nan
            t_charge_out_c = np.nan
            t_discharge_in_c = np.nan
            t_discharge_out_c = np.nan
            mdot_charge_kg_per_s = 0.0
            mdot_discharge_kg_per_s = 0.0

    # q_delivered_kw is the total delivered power (bypass + discharge)
    # In fluid mix mode, we need to calculate this properly
    q_delivered_kw = q_discharge_kw
    if has_demand and mdot_to_deliver_kg_per_s > 0:
        # Calculate bypass power: power that goes directly from initiator to demand
        # This happens when initiator provides more energy than needed for tank charging
        if has_incoming_flow and t_received_in_c > self._temperature:
            # Initiator is hotter than tank - potential for bypass
            cp_j_per_kgk = prosumer.get_cp_fluid_j_per_kgk([t_received_in_c, self._temperature])
            q_bypass_kw = mdot_to_deliver_kg_per_s * cp_j_per_kgk * (t_received_in_c - t_demand_in_c) / 1000
            q_delivered_kw = q_discharge_kw + q_bypass_kw

    return (soc_out, t_tank_c, q_ch_kw, q_discharge_kw, q_delivered_kw, mdot_charge_kg_per_s,
            t_charge_in_c, t_charge_out_c, mdot_discharge_kg_per_s, t_discharge_in_c, t_discharge_out_c)


class HeatStorageController(BasicProsumerController):
    """
    Controller for heat storage systems.

    Can be used with GenericMapping (power only) or FluidMixMapping (temperature and
    mass flows, uniform tank model). Optional min_temp_c and max_temp_c allow
    computing SOC from tank temperature when using FluidMixMapping.
    """

    def name_class(self):
        return "heat_storage_controller"

    def __init__(self, prosumer, heat_storage_object, order, level, init_soc=0.,
                 init_temperature=None, in_service=True, index=None, **kwargs):
        """
        Initializes the HeatStorageController.

        :param prosumer: The prosumer object
        :param heat_storage_object: The heat storage object
        :param order: The order of the controller
        :param level: The level of the controller
        :param init_soc: Initial state of charge (power-only mode or fallback)
        :param init_temperature: Initial uniform tank temperature [°C] for FluidMix mode (from element if None)
        :param in_service: The in-service status of the controller
        :param index: The index of the controller
        :param kwargs: Additional keyword arguments
        """
        super().__init__(prosumer, heat_storage_object, order=order, level=level,
                         in_service=in_service, index=index, **kwargs)
        self._soc = float(init_soc)
        self.last_soc = float(init_soc)
        # Fluid mode: uniform tank state (set from element in control_step if used)
        self._temperature = float(init_temperature) if init_temperature is not None else None
        self.t_previous_out_c = np.nan
        self.t_previous_in_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

    def _use_fluid_mix_mode(self, prosumer):
        """True if tank has capacity_kg (and thus supports FluidMix / uniform tank)."""
        cap = self._get_element_param(prosumer, "capacity_kg")
        return cap is not None and not (isinstance(cap, float) and np.isnan(cap)) and cap > 0

    def _init_fluid_state_from_element(self, prosumer):
        """Initialize uniform tank temperature from element if not already set."""
        # Only (re)initialize when we don't yet have a valid internal temperature.
        needs_init = (
            self._temperature is None
            or (isinstance(self._temperature, float) and np.isnan(self._temperature))
        )
        if needs_init:
            init_t = self._get_element_param(prosumer, "init_temperature_c")
            if init_t is not None and not (isinstance(init_t, float) and np.isnan(init_t)):
                self._temperature = float(init_t)
        if self._temperature is None or (isinstance(self._temperature, float) and np.isnan(self._temperature)):
            raise ValueError(f"Not valid Heat Storage initial temperature: {self._temperature}")

    @property
    def _t_received_in_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        return np.nan

    @property
    def _mdot_received_kg_per_s(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        return np.nan

    def _soc_from_temperature(self, prosumer):
        """Compute SOC from tank temperature using element min_temp_c / max_temp_c if set."""
        if self._temperature is None or (isinstance(self._temperature, float) and np.isnan(self._temperature)):
            return None
        min_t = self._get_element_param(prosumer, "min_temp_c")
        max_t = self._get_element_param(prosumer, "max_temp_c")
        if min_t is None or (isinstance(min_t, float) and np.isnan(min_t)):
            return None
        if max_t is None or (isinstance(max_t, float) and np.isnan(max_t)):
            return None
        delta = float(max_t) - float(min_t)
        if delta <= 0:
            return None
        soc = (self._temperature - float(min_t)) / delta
        return float(np.clip(soc, 0.0, 1.0))

    def _calculate_available_energy_kwh(self, prosumer):
        """Calculate the available energy in the storage in kWh."""
        soc = self._soc_from_temperature(prosumer)
        if soc is None or np.isnan(soc):
            return 0.0
        e_capacity_kwh = self._get_element_param(prosumer, "e_capacity_kwh")
        available_energy_kwh = (1-soc) * e_capacity_kwh
        return available_energy_kwh

    def _calculate_heat_losses(self, prosumer):
        """Update internal temperature for wall heat losses."""
        u = self._get_element_param(prosumer, "u_w_per_m2k")
        if u is None or (isinstance(u, float) and np.isnan(u)):
            u = 0
        area = self._get_element_param(prosumer, "area_wall_m2")
        if area is None or (isinstance(area, float) and np.isnan(area)):
            area = 0
        t_ext = self._get_element_param(prosumer, "t_ext_c")
        if t_ext is None or (isinstance(t_ext, float) and np.isnan(t_ext)):
            t_ext = 25.0
        t_ext = float(t_ext)
        capacity_kg = float(self._get_element_param(prosumer, "capacity_kg"))
        q_loss_w = u * area * (self._temperature - t_ext)
        cp_j_per_kgk = self.get_cp_fluid_j_per_kgk(prosumer, self._temperature)
        loss_w_per_k = cp_j_per_kgk * self.resol * capacity_kg
        if loss_w_per_k > 0:
            t_loss_c = q_loss_w / loss_w_per_k
            self._temperature -= t_loss_c

    def _calculate_uniform_tank_step(self, prosumer, mdot_delivered_kg_per_s, t_in_c):
        """
        One timestep of uniform tank: heat losses then mixing.
        Returns (q_delivered_kw, mdot_delivered_kg_per_s, t_out_c, new_temperature).
        """
        # Store initial temperature before heat losses
        t_before_loss_c = self._temperature
        
        self._calculate_heat_losses(prosumer)  # FIXME: calculate twice ?
        t_out_c = self._temperature  # Tank temperature after heat losses
        capacity_kg = float(self._get_element_param(prosumer, "capacity_kg"))
        m_received_kg = mdot_delivered_kg_per_s * self.resol
        
        # Calculate energy before mixing
        cp_j_per_kgk = self.get_cp_fluid_j_per_kgk(prosumer, t_before_loss_c)
        
        # Calculate energy delivered to/from storage
        # When fluid flows through the tank, energy is transferred based on temperature difference
        # Positive q_delivered_kw means storage is delivering energy (discharging)
        # Negative q_delivered_kw means storage is receiving energy (charging)
        q_delivered_kw = mdot_delivered_kg_per_s * (t_out_c - t_in_c) * cp_j_per_kgk / 1000
        
        # Update tank temperature after mixing
        # This is the key physical equation for a uniform tank
        # Mix incoming flow with tank temperature BEFORE heat losses
        if capacity_kg > 0:
            new_temp = (
                (capacity_kg - m_received_kg) * t_before_loss_c + m_received_kg * t_in_c
            ) / capacity_kg
            
            # Apply temperature limits from element parameters
            min_t = self._get_element_param(prosumer, "min_temp_c")
            max_t = self._get_element_param(prosumer, "max_temp_c")
            if min_t is not None and max_t is not None and max_t > min_t and not (min_t <= new_temp <= max_t):
                warnings.warn(f"In prosumer {prosumer.name} at timestep {self.time} - HeatStorageController {self.name}: Applying temperature limits to new tank temperature {new_temp:.2f}°C (min: {min_t}°C, max: {max_t}°C)", RuntimeWarning)
                new_temp = float(np.clip(new_temp, min_t, max_t))
        else:
            new_temp = t_out_c  # No capacity means no change in temperature
                    
        return q_delivered_kw, mdot_delivered_kg_per_s, t_out_c, new_temp

    def q_to_receive_kw(self, prosumer):
        """
        Heat to receive in kW (used in GenericMapping / power-only mode).
        """
        _e_capacity_kwh = self._get_element_param(prosumer, "e_capacity_kwh")
        fill_level_kwh = min(self._soc, 1) * _e_capacity_kwh
        q_to_receive_kw = (_e_capacity_kwh - fill_level_kwh) * 3600 / self.resol
        q_to_receive_kw += self.q_to_deliver_kw(prosumer)
        if not np.isnan(self._get_input("q_received_kw")):
            q_received_kw = self._get_input("q_received_kw")
            q_to_receive_kw -= q_received_kw
            q_to_receive_kw = max(0.0, q_to_receive_kw)
        return q_to_receive_kw

    def q_to_deliver_kw(self, prosumer):
        """Heat to deliver in kW (sum of generic-mapped responders' demand)."""
        q_to_deliver_kw = 0.0
        for responder in self._get_generic_mapped_responders(prosumer):
            q_to_deliver_kw += responder.q_to_receive_kw(prosumer)
        return q_to_deliver_kw
    
    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_demand_kg_per_s = np.sum(mdot_demand_tab_required_kg_per_s)
        
        # Get temperature limits from element parameters
        max_tank_temp_c = self._get_element_param(prosumer, "max_temp_c")
        min_tank_temp_c = self._get_element_param(prosumer, "min_temp_c")
        
        # Initialize with default values
        t_feed_c = max_tank_temp_c if max_tank_temp_c is not None else 80.0
        t_return_c = min_tank_temp_c if min_tank_temp_c is not None else 40.0
        
        # If there is a demand, we need to supply the demand and potentially charge the storage
        if mdot_demand_kg_per_s > 0 and t_demand_out_c > t_demand_in_c > 1e-6:
            # For fluid mix mode, we ask for the demand temperature and mass flow + a mass flow that would fill the tank
            t_feed_c = t_demand_out_c
            t_return_c = t_demand_in_c
            mdot_required_kg_per_s = mdot_demand_kg_per_s
            # Find the energy left to fill the tank
            e_available_kwh = self._calculate_available_energy_kwh(prosumer)
            # Calculate the corresponding mass flow
            cp_j_per_kgk = self.get_cp_fluid_j_per_kgk(prosumer, [t_feed_c, t_return_c])
            energy_needed_to_fill_kwh = e_available_kwh
            temperature_diff = t_feed_c - t_return_c
            if temperature_diff > 1e-6 and energy_needed_to_fill_kwh > 0:
                q_to_receive_kw = energy_needed_to_fill_kwh / (self.resol / 3600)  # Set the power to deliver to fill the tank within one timestep
                mdot_fill_kg_per_s = q_to_receive_kw * 1000 / (cp_j_per_kgk * temperature_diff)                #  Add the mass flow needed to fill the tank to the mass flow needed to satisfy demand, so that we ask for enough energy to do both
                mdot_required_kg_per_s += mdot_fill_kg_per_s
            return t_feed_c, t_return_c, mdot_required_kg_per_s
        else:
            # If there is no demand, ask to fill the tank to maintain temperature
            if max_tank_temp_c is None or min_tank_temp_c is None or max_tank_temp_c <= min_tank_temp_c:
                # Use reasonable defaults if temperature limits are not properly set
                t_return_c = self._temperature if self._temperature is not None and not np.isnan(self._temperature) else 40.0
                t_feed_c = t_return_c + 20.0  # default to a 20°C temperature difference for charging when no limits are set
            else:
                t_feed_c = max_tank_temp_c
                t_return_c = min_tank_temp_c
            
            # Calculate required mass flow based on power needs
            # Find the energy left to fill the tank
            e_available_kwh = self._calculate_available_energy_kwh(prosumer)
            # Calculate the corresponding mass flow
            cp_j_per_kgk = self.get_cp_fluid_j_per_kgk(prosumer, [t_feed_c, t_return_c])
            energy_needed_to_fill_kwh = e_available_kwh
            temperature_diff = t_feed_c - t_return_c
            if temperature_diff > 1e-6 and energy_needed_to_fill_kwh > 0:
                q_to_receive_kw = energy_needed_to_fill_kwh / (self.resol / 3600)  # Set the power to deliver to fill the tank within one timestep
                mdot_required_kg_per_s = q_to_receive_kw * 1000 / (cp_j_per_kgk * temperature_diff)
            else:
                mdot_required_kg_per_s = 0.0
            
            return t_feed_c, t_return_c, mdot_required_kg_per_s

    def _save_state(self):
        """Backup states before run."""
        self._backup_state = {"soc": self._soc}
        if self._temperature is not None:
            self._backup_state["temperature"] = self._temperature
            self._backup_state["t_previous_out_c"] = self.t_previous_out_c
            self._backup_state["t_previous_in_c"] = self.t_previous_in_c
            self._backup_state["mdot_previous_in_kg_per_s"] = self.mdot_previous_in_kg_per_s

    def _restore_state(self):
        """Restore states before rerun."""
        if hasattr(self, "_backup_state"):
            self._soc = self._backup_state["soc"]
            if "temperature" in self._backup_state:
                self._temperature = self._backup_state["temperature"]
                self.t_previous_out_c = self._backup_state["t_previous_out_c"]
                self.t_previous_in_c = self._backup_state["t_previous_in_c"]
                self.mdot_previous_in_kg_per_s = self._backup_state["mdot_previous_in_kg_per_s"]

    def control_step(self, prosumer):
        """
        Executes the control step.
        Uses power-only balance when only GenericMapping is used; uses uniform tank
        (temperature and mass flows) when FluidMixMapping is used and capacity_kg is set.
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

        # FluidMix mode: uniform tank with temperature and mass flows
        if self._use_fluid_mix_mode(prosumer):
            self._run_control_step_fluid_mix(prosumer)
            return

        # Power-only mode (GenericMapping)
        self._run_control_step_power_only(prosumer)

    def _run_control_step_power_only(self, prosumer):
        """Power-only balance (q_received_kw -> soc, q_delivered_kw)."""
        q_to_deliver_kw = self.q_to_deliver_kw(prosumer)
        _e_capacity_kwh = self._get_element_param(prosumer, "e_capacity_kwh")
        e_received_kwh = self._get_input("q_received_kw") * self.resol / 3600
        potential_kwh = self._soc * _e_capacity_kwh + e_received_kwh
        demand_kwh = q_to_deliver_kw * self.resol / 3600
        if demand_kwh > potential_kwh:
            demand_kwh = potential_kwh
        if not isinstance(demand_kwh, np.ndarray) and demand_kwh == 0:
            demand_kwh = np.array([0.0]) / self.resol / 3600
        fill_level_kwh = potential_kwh - demand_kwh

        excess_energy_kwh = max(0, fill_level_kwh - _e_capacity_kwh)
        if excess_energy_kwh > 0:
            raise ValueError(
                f"Excess energy detected: {excess_energy_kwh} kWh exceeds the maximum capacity."
            )

        self._soc = float(np.asarray(fill_level_kwh).flat[0]) / _e_capacity_kwh
        demand_kw = float(np.asarray(demand_kwh).flat[0]) / (self.resol / 3600)
        assert 0 <= self._soc <= 1, (
            f"SOC = {self._soc} invalid for controller {self.name} in prosumer {prosumer.name} "
            f"at timestep {self.time}"
        )
        # Get tank temperature for output (use _temperature if available, otherwise derive from SOC or use default)
        t_tank_c = self._temperature if self._temperature is not None and not np.isnan(self._temperature) else 40.0
        # For power-only mode, t_received_out_c is not applicable, use tank temperature
        t_received_out_c = t_tank_c
        # Calculate charging and delivered power (both should be positive)
        # Charging occurs when demand is negative OR when there's excess input power after meeting demand
        input_power_kw = self._get_input("q_received_kw")
        
        if demand_kw < 0:
            # Negative demand means explicit charging request
            q_ch_kw = -demand_kw  # Positive charging power
            q_delivered_kw = 0.0   # No delivery when charging
            q_charge_kw = q_ch_kw  # Charging power
            q_discharge_kw = 0.0  # No discharge when charging
        elif input_power_kw > 0 and demand_kw == 0:
            # Input power available but no demand -> charge with all input power
            q_ch_kw = input_power_kw  # Positive charging power
            q_delivered_kw = 0.0       # No delivery
            q_charge_kw = q_ch_kw      # Charging power
            q_discharge_kw = 0.0       # No discharge
        else:
            # Normal discharging case
            q_ch_kw = 0.0           # No charging when delivering
            q_delivered_kw = demand_kw  # Positive delivered power
            q_charge_kw = 0.0      # No charging when discharging
            q_discharge_kw = q_delivered_kw  # Discharge power when delivering
        
        # In power-only mode, use tank temperature for charge/discharge temperatures
        # Mass flows are 0 since we don't have fluid information
        # Avoid NaN values - use appropriate defaults when not applicable
        # FIXME
        if q_ch_kw > 0:  # Charging
            t_charge_in_c = t_tank_c
            t_charge_out_c = t_tank_c
            t_discharge_in_c = t_tank_c  # Not discharging
            t_discharge_out_c = t_tank_c  # Not discharging
            mdot_charge_kg_per_s = 0.0  # No mass flow info in power-only mode
            mdot_discharge_kg_per_s = 0.0
        elif q_delivered_kw > 0:  # Discharging
            t_charge_in_c = t_tank_c  # Not charging
            t_charge_out_c = t_tank_c  # Not charging
            t_discharge_in_c = t_tank_c
            t_discharge_out_c = t_tank_c
            mdot_charge_kg_per_s = 0.0
            mdot_discharge_kg_per_s = 0.0  # No mass flow info in power-only mode
        else:  # No activity
            t_charge_in_c = t_tank_c
            t_charge_out_c = t_tank_c
            t_discharge_in_c = t_tank_c
            t_discharge_out_c = t_tank_c
            mdot_charge_kg_per_s = 0.0
            mdot_discharge_kg_per_s = 0.0

        # q_delivered_kw is the total delivered power (bypass + discharge)
        # In power-only mode, this equals q_discharge_kw since there's no bypass concept
        q_delivered_kw = q_discharge_kw
        
        result = np.array([[float(self._soc), t_tank_c, q_ch_kw, q_discharge_kw, q_delivered_kw, mdot_charge_kg_per_s, 
                            t_charge_in_c, t_charge_out_c, mdot_discharge_kg_per_s, t_discharge_in_c, t_discharge_out_c]])
        self.last_result = {"soc": self._soc, "t_tank_c": t_tank_c, "q_ch_kw": q_ch_kw, "q_dch_kw": q_discharge_kw, "q_delivered_kw": q_delivered_kw, "mdot_ch_kg_per_s": mdot_charge_kg_per_s,
                           "t_ch_in_c": t_charge_in_c, "t_ch_out_c": t_charge_out_c, "mdot_dch_kg_per_s": mdot_discharge_kg_per_s,
                           "t_dch_in_c": t_discharge_in_c, "t_dch_out_c": t_discharge_out_c}
        self.finalize(prosumer, result)
        self.applied = True

    def _run_control_step_fluid_mix(self, prosumer):
        """Uniform tank step with FluidMix input/output; optional SOC from temperature."""
        self._init_fluid_state_from_element(prosumer)
        
        # Store initial temperature for discharge output calculation
        initial_temperature = self._temperature if self._temperature is not None and not np.isnan(self._temperature) else None
        
        # Get demand information
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_demand_kg_per_s = np.sum(mdot_demand_tab_kg_per_s)

        # Get incoming flow information
        mdot_received_kg_per_s = self._mdot_received_kg_per_s
        t_received_in_c = self._t_received_in_c

        rerun = True
        while rerun:
            # Get current tank state
            current_temp = self._temperature

            capacity_kg = float(self._get_element_param(prosumer, "capacity_kg"))

            (soc_out, t_tank_c,
             q_ch_kw, q_discharge_kw, q_delivered_kw,
             mdot_charge_kg_per_s, t_charge_in_c, t_charge_out_c,
             mdot_discharge_kg_per_s, t_discharge_in_c, t_discharge_out_c) = _calculate_heat_storage(prosumer,
                                                                                                     mdot_demand_kg_per_s,
                                                                                                     t_received_in_c,
                                                                                                     t_demand_out_c,
                                                                                                     t_demand_in_c,
                                                                                                     t_discharge_out_c,
                                                                                                     mdot_received_kg_per_s,
                                                                                                     t_charge_out,
                                                                                                     current_temp,
                                                                                                     capacity_kg)

            self._temperature = t_tank_c

            # Build result for responders using merit order mass flow distribution
            # Use merit order to distribute the delivered mass flow (from base class)
            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_delivered_kg_per_s,
                                                                   mdot_demand_tab_kg_per_s)

            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_delivered_kg_per_s < mdot_demand_kg_per_s:
                # If the stratified heat storage is not able to deliver the required mass flow,
                # recalculate the condenser input temperature, considering that all the downstream elements will be
                # still return the same temperature, even if the mass flow delivered to them by the Stratified Heat Storage is lower
                t_return_tab_c = self.get_treturn_tab_c(prosumer)
                if abs(mdot_delivered_kg_per_s) > 1e-8:
                    t_return_demand_new_c = np.sum(result_mdot_tab_kg_per_s * t_return_tab_c) / mdot_delivered_kg_per_s
                else:
                    t_return_demand_new_c = t_demand_in_c
                if abs(t_return_demand_new_c - t_demand_in_c) > 1:
                    # If this recalculation changes the condenser input temperature, rerun the calculation
                    # with the new temperature
                    t_demand_in_c = t_return_demand_new_c
                    rerun = True

        result = np.array([[soc_out, self._temperature,
                            q_ch_kw, q_discharge_kw, q_delivered_kw,
                            mdot_charge_kg_per_s, t_charge_in_c, t_charge_out_c,
                            mdot_discharge_kg_per_s, t_discharge_in_c, t_discharge_out_c]])
        
        self.last_result = {
            "soc": soc_out,
            "t_tank_c": self._temperature,
            "q_ch_kw": q_ch_kw,
            "q_dch_kw": q_discharge_kw,
            "q_delivered_kw": q_delivered_kw,
            "mdot_ch_kg_per_s": mdot_charge_kg_per_s,
            "t_ch_in_c": t_charge_in_c,
            "t_ch_out_c": t_charge_out_c,
            "mdot_dch_kg_per_s": mdot_discharge_kg_per_s,
            "t_dch_in_c": t_discharge_in_c,
            "t_dch_out_c": t_discharge_out_c,
        }

        # Build result_fluid_mix for each responder
        result_fluid_mix = []
        for i, mdot_kg_per_s in enumerate(result_mdot_tab_kg_per_s):
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: self._temperature,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        t_received_out_c = t_charge_out_c

        # Finalize if conditions are met
        if (np.isnan(self.t_keep_return_c) or mdot_received_kg_per_s == 0 or
                abs(t_received_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C or
                len(self._get_mapped_initiators_on_same_level(prosumer)) == 0):
            # If the actual output temperature is the same as the promised one, the storage is correctly applied
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_out_c = np.nan
            self.t_previous_in_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            self._temperature = initial_temperature
            self._unapply_initiators(prosumer)
            self.t_previous_out_c = t_received_out_c
            self.t_previous_in_c = t_received_in_c
            self.mdot_previous_in_kg_per_s = mdot_delivered_kg_per_s
            self.input_mass_flow_with_temp = {
                FluidMixMapping.TEMPERATURE_KEY: np.nan,
                FluidMixMapping.MASS_FLOW_KEY: np.nan,
            }
