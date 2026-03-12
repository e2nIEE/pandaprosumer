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
                            mdot_received_kg_per_s, t_charge_out_c,
                            current_temp, capacity_kg,
                            min_temp_c, max_temp_c, resol_s):
    cp_j_per_kgk = prosumer.get_cp_fluid_j_per_kgk(
        [v for v in [current_temp, t_received_in_c, t_demand_in_c] if not np.isnan(v)]
    )

    has_incoming_flow = (
        not (np.isnan(mdot_received_kg_per_s) or np.isnan(t_received_in_c))
        and mdot_received_kg_per_s > 0
    )
    has_demand = (
        mdot_demand_kg_per_s > 0
        and not np.isnan(t_demand_out_c)
        and not np.isnan(t_demand_in_c)
        and t_demand_out_c > t_demand_in_c
    )
    can_discharge = current_temp > t_demand_in_c + 1e-9

    mdot_bypass_kg_per_s = 0.0
    mdot_charge_kg_per_s = 0.0
    mdot_discharge_kg_per_s = 0.0

    q_bypass_kw = 0.0
    q_charge_kw = 0.0
    q_discharge_kw = 0.0

    t_received_out_c = current_temp
    t_delivered_out_c = current_temp
    t_tank_c = current_temp

    if has_demand:
        q_demand_kw = mdot_demand_kg_per_s * cp_j_per_kgk * (t_demand_out_c - t_demand_in_c) / 1e3
    else:
        q_demand_kw = 0.0

    q_bypass_available_kw = 0.0
    if has_incoming_flow and t_received_in_c > t_demand_in_c:
        q_bypass_available_kw = mdot_received_kg_per_s * cp_j_per_kgk * (t_received_in_c - t_demand_in_c) / 1e3

    if has_demand and q_bypass_available_kw > 0:
        q_bypass_kw = min(q_demand_kw, q_bypass_available_kw)
        mdot_bypass_kg_per_s = q_bypass_kw * 1e3 / (
            cp_j_per_kgk * max(t_received_in_c - t_demand_in_c, 1e-9)
        )

    if has_incoming_flow:
        remaining_received_mdot_kg_per_s = max(0.0, mdot_received_kg_per_s - mdot_bypass_kg_per_s)
    else:
        remaining_received_mdot_kg_per_s = 0.0

    q_missing_kw = max(0.0, q_demand_kw - q_bypass_kw)
    if q_missing_kw > 0 and can_discharge:
        q_discharge_max_kw = mdot_demand_kg_per_s * cp_j_per_kgk * (current_temp - t_demand_in_c) / 1e3
        q_discharge_kw = min(q_missing_kw, max(0.0, q_discharge_max_kw))
        mdot_discharge_kg_per_s = q_discharge_kw * 1e3 / (cp_j_per_kgk * max(current_temp - t_demand_in_c, 1e-9))

    if remaining_received_mdot_kg_per_s > 0 and t_received_in_c > current_temp + 1e-9:
        mdot_charge_kg_per_s = remaining_received_mdot_kg_per_s
        q_charge_kw = mdot_charge_kg_per_s * cp_j_per_kgk * (t_received_in_c - current_temp) / 1e3

    net_energy_kj = (q_charge_kw - q_discharge_kw) * resol_s
    if capacity_kg > 0:
        delta_t_c = net_energy_kj / (capacity_kg * cp_j_per_kgk / 1e3)
        t_tank_c = current_temp + delta_t_c
        if min_temp_c is not None and max_temp_c is not None and max_temp_c > min_temp_c:
            warnings.warn(
                f"In prosumer {prosumer.name} - HeatStorageController: Applying temperature limits to new "
                f"tank temperature {t_tank_c:.2f}°C (min: {min_temp_c}°C, max: {max_temp_c}°C)",
                RuntimeWarning)
            t_tank_c = float(np.clip(t_tank_c, min_temp_c, max_temp_c))

    mdot_delivered_kg_per_s = mdot_bypass_kg_per_s + mdot_discharge_kg_per_s
    q_delivered_kw = q_bypass_kw + q_discharge_kw

    if mdot_delivered_kg_per_s > 0:
        t_delivered_out_c = (
            mdot_bypass_kg_per_s * t_received_in_c +
            mdot_discharge_kg_per_s * current_temp
        ) / mdot_delivered_kg_per_s
    else:
        t_delivered_out_c = current_temp

    if has_incoming_flow:
        returned_mdot_kg_per_s = mdot_bypass_kg_per_s + mdot_charge_kg_per_s
        if returned_mdot_kg_per_s > 0:
            t_received_out_c = (
                mdot_bypass_kg_per_s * t_demand_in_c +
                mdot_charge_kg_per_s * current_temp
            ) / returned_mdot_kg_per_s
        else:
            t_received_out_c = current_temp

    soc_out = np.nan
    if min_temp_c is not None and max_temp_c is not None and max_temp_c > min_temp_c:
        soc_out = (t_tank_c - min_temp_c) / (max_temp_c - min_temp_c)
        if not 0. < soc_out < 1.:
            warnings.warn(f"In prosumer {prosumer.name} - Heat storage : Applying soc limit on soc {soc_out}")
            soc_out = float(np.clip(soc_out, 0.0, 1.0))

    # Use appropriate default values for temperatures when there's no flow
    # Note: t_tank_c here is the temperature after mixing but before heat losses
    # For output temperatures, we should use the final temperature after heat losses
    # final_tank_temp = t_tank_c  # This will be updated after heat losses in the caller
    # t_charge_in_c = t_received_in_c if has_incoming_flow else final_tank_temp
    # t_charge_out_c = final_tank_temp if mdot_charge_kg_per_s > 0 else final_tank_temp
    # t_discharge_in_c = t_demand_in_c if has_demand else final_tank_temp
    # t_discharge_out_c = final_tank_temp if mdot_discharge_kg_per_s > 0 else final_tank_temp

    # return (
    #     soc_out, t_tank_c,
    #     q_charge_kw, q_discharge_kw, q_delivered_kw,
    #     mdot_delivered_kg_per_s, t_delivered_out_c, t_received_out_c,
    #     mdot_charge_kg_per_s, t_charge_in_c, t_charge_out_c,
    #     mdot_discharge_kg_per_s, t_discharge_in_c, t_discharge_out_c
    # )
    return (
        soc_out, t_tank_c,
        q_charge_kw, q_discharge_kw, q_delivered_kw,
        mdot_delivered_kg_per_s, t_delivered_out_c, t_received_out_c,
        mdot_charge_kg_per_s, t_received_in_c, t_charge_out_c,
        mdot_discharge_kg_per_s, t_demand_in_c, current_temp
    )

class HeatStorageController(BasicProsumerController):
    """
    Controller for heat storage systems.

    Can be used with GenericMapping (power only) or FluidMixMapping (temperature and
    mass flows, uniform tank model). Optional min_temp_c and max_temp_c allow
    computing SOC from tank temperature when using FluidMixMapping.
    """

    def name_class(self):
        return "heat_storage_controller"

    def __init__(self, prosumer, heat_storage_object, order, level, init_soc=np.nan,
                 t_tank_init_c=None, in_service=True, index=None, **kwargs):
        """
        Initializes the HeatStorageController.

        :param prosumer: The prosumer object
        :param heat_storage_object: The heat storage object
        :param order: The order of the controller
        :param level: The level of the controller
        :param init_soc: Initial state of charge (power-only mode or fallback)
        :param t_tank_init_c: Initial uniform tank temperature [°C] for FluidMix mode (from element if None)
        :param in_service: The in-service status of the controller
        :param index: The index of the controller
        :param kwargs: Additional keyword arguments
        """
        super().__init__(prosumer, heat_storage_object, order=order, level=level,
                         in_service=in_service, index=index, **kwargs)
        if init_soc and t_tank_init_c and not np.isnan(init_soc) and not np.isnan(t_tank_init_c):
            raise ValueError("When creating Heat Storage:Cannot set both init_soc and t_tank_init_c.")

        self._temperature = float(t_tank_init_c) if t_tank_init_c is not None and not np.isnan(t_tank_init_c) else None
        
        if self._temperature and self._get_element_param(prosumer, "min_temp_c")  and self._get_element_param(prosumer, "max_temp_c"):
            self._soc = self._soc_from_temperature(prosumer)
        elif not init_soc or (init_soc and not np.isnan(init_soc)):
            self._soc = float(init_soc)
        else:
            self._soc = 0.
        self.last_soc = self._soc
            
        self.t_previous_out_c = np.nan
        self.t_previous_in_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

    def _use_fluid_mix_mode(self, prosumer):
        """True if tank is not receiving power via GenericMapping input."""
        return np.isnan(self._get_input('q_received_kw'))

    def _init_fluid_state_from_element(self, prosumer):
        """Initialize uniform tank temperature from element if not already set."""
        # Only (re)initialize when we don't yet have a valid internal temperature.
        needs_init = (
            self._temperature is None
            or (isinstance(self._temperature, float) and np.isnan(self._temperature))
        )
        if needs_init:
            init_t = self._get_element_param(prosumer, "t_tank_init_c")
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

    def _temperature_from_soc(self, prosumer, soc):
        """Compute tank temperature from SOC using element min_temp_c / max_temp_c if set."""
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
        return float(min_t) + soc * delta

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
        if capacity_kg > 0:
            delta_t_c = (q_loss_w * self.resol) / (capacity_kg * cp_j_per_kgk)
            self._temperature -= delta_t_c

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
                if not (min_t <= new_temp <= max_t ):
                    warnings.warn(f"In prosumer {prosumer.name} at timestep {self.time} - HeatStorageController "
                                f"{self.name}: Applying temperature limits to new tank temperature"
                                f" {new_temp:.2f}°C (min: {min_t}°C, max: {max_t}°C)", RuntimeWarning)
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
            responder_q_to_received_kw =  responder.q_to_receive_kw(prosumer)
            if np.isnan(responder_q_to_received_kw):
                warnings.warn(f"In prosumer {prosumer.name} for timestep {self.time} in controller {self.name}: q_to_received is nan for responder {responder.name}", RuntimeWarning)
            q_to_deliver_kw += responder_q_to_received_kw
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

        # Fallback values if limits are not defined
        if max_tank_temp_c is None or np.isnan(max_tank_temp_c):
            max_tank_temp_c = 80.0
        if min_tank_temp_c is None or np.isnan(min_tank_temp_c):
            min_tank_temp_c = 40.0

        # Charging target temperature
        t_charge_in_c = max_tank_temp_c

        # If there is no demand, we ask for t_charge_in_c.
        # Otherwise, we prioritize the demand temperature if it's higher than the current tank temperature
        # but limited by the maximum tank temperature.
        if t_demand_out_c < 1e-6 or mdot_demand_kg_per_s < 1e-6:
            t_required_in_c = t_charge_in_c
        else:
            t_required_in_c = max(t_demand_out_c, t_charge_in_c)

        # The return temperature from the tank for charging is the current tank temperature
        t_charge_out_c = self._temperature if self._temperature is not None and not np.isnan(self._temperature) else min_tank_temp_c

        # Check if charging is needed
        # We use energy capacity for a uniform tank
        e_capacity_kwh = self._get_element_param(prosumer, "e_capacity_kwh")
        soc = self._soc_from_temperature(prosumer)
        if soc is None or np.isnan(soc):
            soc = 0.0

        remaining_capacity_kwh = (1 - soc) * e_capacity_kwh

        # If the storage is full (or almost full) and there is a demand, only ask for the demand
        max_remaining_cap = self._get_element_param(prosumer, "max_remaining_capacity_kwh")
        if max_remaining_cap is None or np.isnan(max_remaining_cap):
            max_remaining_cap = 1.0 # default from create_controlled.py

        if mdot_demand_kg_per_s > 0 and remaining_capacity_kwh < max_remaining_cap:
            return t_demand_out_c, t_demand_in_c, mdot_demand_kg_per_s

        # For charging, we ask to fill the tank to max_tank_temp_c
        # Mass flow required to change tank temperature from t_charge_out_c to t_required_in_c
        # in one timestep
        cp_j_per_kgk = self.get_cp_fluid_j_per_kgk(prosumer, [t_required_in_c, t_charge_out_c])

        # If tank is already at or above target, no charging mass flow
        if t_required_in_c > t_charge_out_c + 1e-6:
            # Energy needed in Joules: m * cp * deltaT
            e_needed_ch_kwh = remaining_capacity_kwh
            # Power in Watts: Energy / resol_s
            power_needed_w = e_needed_ch_kwh / (self.resol / 3600) * 1000
            # Mass flow: Power / (cp * (t_feed - t_return))
            # Here t_feed = t_required_in_c, t_return = t_charge_out_c
            mdot_charge_kg_per_s = power_needed_w / (cp_j_per_kgk * (t_required_in_c - t_charge_out_c))
            # Simplified: mdot_charge = capacity_kg / self.resol (replace the whole tank volume in one timestep)
            # mdot_charge_kg_per_s = capacity_kg / self.resol
        else:
            mdot_charge_kg_per_s = 0.0

        mdot_required_kg_per_s = mdot_demand_kg_per_s + mdot_charge_kg_per_s

        if mdot_required_kg_per_s == 0:
            t_required_out_c = t_charge_out_c
        else:
            t_required_out_c = (mdot_demand_kg_per_s * t_demand_in_c + mdot_charge_kg_per_s * t_charge_out_c) / mdot_required_kg_per_s

        # Handle iteration convergence if previous values are available
        #if hasattr(self, 't_previous_out_c') and not np.isnan(self.t_previous_out_c) and mdot_required_kg_per_s > 0:
            # Adjust mass flow based on previous iteration to help convergence
            # This logic is similar to stratified storage
            #if abs(self.t_previous_out_c - t_required_out_c) > 1e-3:
                # If we have a mismatch, we might need to adjust mdot_charge to meet the required T_out
                # But for uniform tank, T_out is usually just the tank temperature (plus bypass)
            #    pass
        if not np.isnan(self.t_previous_out_c):
            mdot_charge_kg_per_s = mdot_demand_kg_per_s * (t_demand_in_c - t_required_out_c) / (t_required_out_c - t_charge_out_c)
            return self.t_previous_in_c, self.t_previous_out_c, mdot_charge_kg_per_s

        return t_required_in_c, t_required_out_c, mdot_required_kg_per_s

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
        capacity_kwh = self._get_element_param(prosumer, "e_capacity_kwh")

        dt_h = self.resol / 3600

        # Inputs
        q_received_kw = float(self._get_input("q_received_kw"))
        demand_kw = float(q_to_deliver_kw)

        # Current storage energy
        e_storage_kwh = self._soc * capacity_kwh

        # -------------------------------------------------
        # 1. Direct supply from source to demand
        # -------------------------------------------------

        q_direct_kw = min(q_received_kw, max(demand_kw, 0.0))

        remaining_demand_kw = max(0.0, demand_kw - q_direct_kw)

        # -------------------------------------------------
        # 2. Storage discharge
        # -------------------------------------------------

        max_discharge_kw = e_storage_kwh / dt_h
        q_dch_kw = min(remaining_demand_kw, max_discharge_kw)

        # -------------------------------------------------
        # 3. Storage charging
        # -------------------------------------------------

        remaining_input_kw = q_received_kw - q_direct_kw

        free_capacity_kwh = capacity_kwh - e_storage_kwh
        max_charge_kw = free_capacity_kwh / dt_h

        q_ch_kw = min(max(0.0, remaining_input_kw), max_charge_kw)

        # -------------------------------------------------
        # 4. Check for energy overflow (no dumping allowed)
        # -------------------------------------------------

        if remaining_input_kw > max_charge_kw + 1e-9:
            excess_kw = remaining_input_kw - max_charge_kw
            raise ValueError(
                f"Excess energy detected: {excess_kw:.3f} kW cannot be delivered "
                f"or stored (storage full). Controller {self.name}, "
                f"prosumer {prosumer.name}, timestep {self.time}"
            )

        # -------------------------------------------------
        # 5. Delivered power
        # -------------------------------------------------

        q_delivered_kw = q_direct_kw + q_dch_kw

        # -------------------------------------------------
        # 6. Update storage energy
        # -------------------------------------------------

        delta_e_kwh = (q_ch_kw - q_dch_kw) * dt_h
        e_storage_kwh += delta_e_kwh

        # Numerical safety clamp
        e_storage_kwh = max(0.0, min(capacity_kwh, e_storage_kwh))

        self._soc = e_storage_kwh / capacity_kwh

        assert 0 <= self._soc <= 1, (
            f"SOC = {self._soc} invalid for controller {self.name} "
            f"in prosumer {prosumer.name} at timestep {self.time}"
        )

        # -------------------------------------------------
        # 7. Temperature update
        # -------------------------------------------------

        self._temperature = self._temperature_from_soc(prosumer, self._soc)
        t_tank_c = self._temperature if self._temperature is not None else 40.0

        # -------------------------------------------------
        # 8. Power-only mode thermal outputs
        # -------------------------------------------------

        mdot_charge_kg_per_s = 0.0
        mdot_discharge_kg_per_s = 0.0

        t_charge_in_c = t_tank_c
        t_charge_out_c = t_tank_c
        t_discharge_in_c = t_tank_c
        t_discharge_out_c = t_tank_c

        # -------------------------------------------------
        # 9. Result vector
        # -------------------------------------------------

        result = np.array([[ 
            self._soc,
            t_tank_c,
            q_ch_kw,
            q_dch_kw,
            q_delivered_kw,
            mdot_charge_kg_per_s,
            t_charge_in_c,
            t_charge_out_c,
            mdot_discharge_kg_per_s,
            t_discharge_in_c,
            t_discharge_out_c
        ]])
        self.last_result = {"soc": self._soc, "t_tank_c": t_tank_c, "q_ch_kw": q_ch_kw, "q_dch_kw": q_dch_kw, "q_delivered_kw": q_delivered_kw, "mdot_ch_kg_per_s": mdot_charge_kg_per_s,
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
        current_temp = self._temperature
        
        min_temp_c = self._get_element_param(prosumer, "min_temp_c")
        max_temp_c = self._get_element_param(prosumer, "max_temp_c")

        rerun = True
        while rerun:
            capacity_kg = float(self._get_element_param(prosumer, "capacity_kg"))

            (soc_out, t_tank_c,
             q_ch_kw, q_discharge_kw, q_delivered_kw,
             mdot_delivered_kg_per_s, t_delivered_out_c, t_received_out_c,
             mdot_charge_kg_per_s, t_charge_in_c, t_charge_out_c,
             mdot_discharge_kg_per_s, t_discharge_in_c, t_discharge_out_c) = _calculate_heat_storage(
                prosumer,
                mdot_demand_kg_per_s,
                t_received_in_c,
                t_demand_out_c,
                t_demand_in_c,
                initial_temperature if initial_temperature is not None else current_temp,
                mdot_received_kg_per_s,
                current_temp,
                current_temp,
                capacity_kg,
                min_temp_c,
                max_temp_c,
                self.resol,
            )

            self._temperature = t_tank_c
            self._calculate_heat_losses(prosumer)

            # Update temperature values to use final temperature after heat losses when there's no flow
            # has_incoming_flow = not (np.isnan(mdot_received_kg_per_s) or np.isnan(t_received_in_c)) and mdot_received_kg_per_s > 0
            # if not has_incoming_flow and mdot_demand_kg_per_s == 0:
            #     t_charge_in_c = self._temperature
            #     t_charge_out_c = self._temperature
            #     t_discharge_in_c = self._temperature
            #     t_discharge_out_c = self._temperature

            soc_fluid = self._soc_from_temperature(prosumer)
            if soc_fluid is not None and not np.isnan(soc_fluid):
                soc_out = soc_fluid
                self._soc = soc_fluid
            elif not np.isnan(soc_out):
                self._soc = soc_out

            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(
                prosumer,
                mdot_delivered_kg_per_s,
                mdot_demand_tab_kg_per_s
            )

            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_delivered_kg_per_s < mdot_demand_kg_per_s:
                t_return_tab_c = self.get_treturn_tab_c(prosumer)
                if abs(mdot_delivered_kg_per_s) > 1e-8:
                    t_return_demand_new_c = np.sum(result_mdot_tab_kg_per_s * t_return_tab_c) / mdot_delivered_kg_per_s
                else:
                    t_return_demand_new_c = t_demand_in_c
                if abs(t_return_demand_new_c - t_demand_in_c) > 1:
                    t_demand_in_c = t_return_demand_new_c
                    rerun = True

        result = np.array([[float(self._soc), self._temperature,
                            q_ch_kw, q_discharge_kw, q_delivered_kw,
                            mdot_charge_kg_per_s, t_charge_in_c, t_charge_out_c,
                            mdot_discharge_kg_per_s, t_discharge_in_c, t_discharge_out_c]])

        self.last_result = {
            "soc": float(self._soc),
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

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({
                FluidMixMapping.TEMPERATURE_KEY: t_delivered_out_c,
                FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s
            })

        if (np.isnan(self.t_keep_return_c) or mdot_received_kg_per_s == 0 or
                abs(t_received_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C or
                len(self._get_mapped_initiators_on_same_level(prosumer)) == 0):
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_out_c = np.nan
            self.t_previous_in_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
        else:
            self._temperature = initial_temperature
            self._unapply_initiators(prosumer)
            self.t_previous_out_c = t_received_out_c
            self.t_previous_in_c = t_received_in_c
            self.mdot_previous_in_kg_per_s = mdot_delivered_kg_per_s
            self.input_mass_flow_with_temp = {
                FluidMixMapping.TEMPERATURE_KEY: np.nan,
                FluidMixMapping.MASS_FLOW_KEY: np.nan,
            }
            