"""
Module containing the HeatStorageController class.

The heat storage controller supports two connection modes:
- **GenericMapping**: power-only interface (q_received_kw input; soc, q_delivered_kw output).
- **FluidMixMapping**: temperature and mass-flow interface (uniform tank model; optional
  min_temp_c / max_temp_c to derive SOC from tank temperature).
"""

import numpy as np
import pandas as pd

from pandaprosumer import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


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
        """Initialize uniform tank temperature from element or keep existing."""
        init_t = self._get_element_param(prosumer, "init_temperature_c")
        if init_t is not None and not (isinstance(init_t, float) and np.isnan(init_t)):
            self._temperature = float(init_t)
        if self._temperature is None:
            self._temperature = 40.0  # default fallback

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

    def _calculate_heat_losses(self, prosumer):
        """Update internal temperature for wall heat losses."""
        u = self._get_element_param(prosumer, "u_w_per_m2k") or 0
        area = self._get_element_param(prosumer, "area_wall_m2") or 0
        t_ext = self._get_element_param(prosumer, "t_ext_c")
        if t_ext is None or (isinstance(t_ext, float) and np.isnan(t_ext)):
            t_ext = 25.0
        t_ext = float(t_ext)
        capacity_kg = float(self._get_element_param(prosumer, "capacity_kg"))
        q_loss_w = u * area * (self._temperature - t_ext)
        fluid = getattr(prosumer, "fluid", None)
        if fluid is not None and hasattr(fluid, "get_heat_capacity"):
            cp_j_per_kgk = fluid.get_heat_capacity(CELSIUS_TO_K + self._temperature)
        else:
            cp_j_per_kgk = 4180.0  # default water [J/(kg·K)]
        if np.isnan(cp_j_per_kgk) or cp_j_per_kgk <= 0:
            cp_j_per_kgk = 4180.0
        loss_w_per_k = cp_j_per_kgk * self.resol * capacity_kg
        if loss_w_per_k > 0:
            t_loss_c = q_loss_w / loss_w_per_k
            self._temperature -= t_loss_c

    def _calculate_uniform_tank_step(self, prosumer, mdot_kg_per_s, t_in_c):
        """
        One timestep of uniform tank: heat losses then mixing.
        Returns (q_delivered_kw, mdot_delivered_kg_per_s, t_out_c, new_temperature).
        """
        self._calculate_heat_losses(prosumer)
        t_out_c = self._temperature
        capacity_kg = float(self._get_element_param(prosumer, "capacity_kg"))
        m_received_kg = mdot_kg_per_s * self.resol
        self._temperature = (
            (capacity_kg - m_received_kg) * self._temperature + m_received_kg * t_in_c
        ) / capacity_kg
        fluid = getattr(prosumer, "fluid", None)
        if fluid is not None and hasattr(fluid, "get_heat_capacity"):
            cp_kj_per_kgk = fluid.get_heat_capacity(CELSIUS_TO_K + self._temperature) / 1000
        else:
            cp_kj_per_kgk = 4.18  # default water [kJ/(kg·K)]
        if np.isnan(cp_kj_per_kgk) or cp_kj_per_kgk <= 0:
            cp_kj_per_kgk = 4.18
        q_delivered_kw = mdot_kg_per_s * (t_out_c - t_in_c) * cp_kj_per_kgk
        return q_delivered_kw, mdot_kg_per_s, t_out_c, self._temperature

    def q_to_receive_kw(self, prosumer):
        """
        Heat to receive in kW (used in GenericMapping / power-only mode).
        """
        _q_capacity_kwh = self._get_element_param(prosumer, "q_capacity_kwh")
        fill_level_kwh = min(self._soc, 1) * _q_capacity_kwh
        q_to_receive_kw = (_q_capacity_kwh - fill_level_kwh) * 3600 / self.resol
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
            if self._use_fluid_mix_mode(prosumer):
                self._init_fluid_state_from_element(prosumer)
                self._calculate_heat_losses(prosumer)
                soc_fluid = self._soc_from_temperature(prosumer)
                soc = soc_fluid if soc_fluid is not None else self._soc
                result = np.array([[soc, 0.0]])
                result_fluid = [{FluidMixMapping.TEMPERATURE_KEY: self._temperature,
                                 FluidMixMapping.MASS_FLOW_KEY: 0.0}]
                self.finalize(prosumer, result, result_fluid_mix=result_fluid)
            else:
                self.finalize(prosumer, np.array([[self._soc, 0.0]]))
            self.applied = True
            return

        super().control_step(prosumer)

        # FluidMix mode: uniform tank with temperature and mass flows
        if self._use_fluid_mix_mode(prosumer):
            self._run_control_step_fluid_mix(prosumer)
            return

        # Power-only mode (GenericMapping)
        self._run_control_step_power_only(prosumer)

    def _run_control_step_power_only(self, prosumer):
        """Power-only balance (q_received_kw -> soc, q_delivered_kw)."""
        q_to_deliver_kw = self.q_to_deliver_kw(prosumer)
        _q_capacity_kwh = self._get_element_param(prosumer, "q_capacity_kwh")
        e_received_kwh = self._get_input("q_received_kw") * self.resol / 3600
        potential_kwh = self._soc * _q_capacity_kwh + e_received_kwh
        demand_kwh = q_to_deliver_kw * self.resol / 3600
        if demand_kwh > potential_kwh:
            demand_kwh = potential_kwh
        if not isinstance(demand_kwh, np.ndarray) and demand_kwh == 0:
            demand_kwh = np.array([0.0]) / self.resol / 3600
        fill_level_kwh = potential_kwh - demand_kwh

        excess_energy_kwh = max(0, fill_level_kwh - _q_capacity_kwh)
        if excess_energy_kwh > 0:
            raise ValueError(
                f"Excess energy detected: {excess_energy_kwh} kWh exceeds the maximum capacity."
            )

        self._soc = float(np.asarray(fill_level_kwh).flat[0]) / _q_capacity_kwh
        demand_kw = float(np.asarray(demand_kwh).flat[0]) / (self.resol / 3600)
        assert 0 <= self._soc <= 1, (
            f"SOC = {self._soc} invalid for controller {self.name} in prosumer {prosumer.name} "
            f"at timestep {self.time}"
        )
        result = np.array([[float(self._soc), demand_kw]])
        self.last_result = {"soc": self._soc, "demand_kw": demand_kw}
        self.finalize(prosumer, result)
        self.applied = True

    def _run_control_step_fluid_mix(self, prosumer):
        """Uniform tank step with FluidMix input/output; optional SOC from temperature."""
        self._init_fluid_state_from_element(prosumer)

        if not self._are_initiators_converged(prosumer):
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {
                FluidMixMapping.TEMPERATURE_KEY: np.nan,
                FluidMixMapping.MASS_FLOW_KEY: np.nan,
            }
            # Still finalize with no delivery so downstream (e.g. heat demand) get valid input
            self._calculate_heat_losses(prosumer)
            t_out = self._temperature if (self._temperature is not None and not np.isnan(self._temperature)) else 40.0
            result_fluid = [{FluidMixMapping.TEMPERATURE_KEY: float(t_out), FluidMixMapping.MASS_FLOW_KEY: 0.0}]
            soc_fluid = self._soc_from_temperature(prosumer)
            soc = soc_fluid if soc_fluid is not None else self._soc
            soc = float(soc) if not np.isnan(soc) else 0.0
            self.finalize(prosumer, np.array([[soc, 0.0]]), result_fluid_mix=result_fluid)
            self.applied = True
            return

        mdot = self._mdot_received_kg_per_s
        t_in = self._t_received_in_c
        if np.isnan(mdot) or np.isnan(t_in):
            self._calculate_heat_losses(prosumer)
            q_delivered_kw = 0.0
            t_out = self._temperature if (self._temperature is not None and not np.isnan(self._temperature)) else 40.0
            result_fluid = [{FluidMixMapping.TEMPERATURE_KEY: float(t_out),
                             FluidMixMapping.MASS_FLOW_KEY: 0.0}]
            soc_fluid = self._soc_from_temperature(prosumer)
            soc = soc_fluid if soc_fluid is not None else self._soc
            soc = float(soc) if not np.isnan(soc) else 0.0
            result = np.array([[soc, q_delivered_kw]])
            self.finalize(prosumer, result, result_fluid_mix=result_fluid)
            self.applied = True
            return

        q_delivered_kw, mdot_delivered, t_out_c, new_t = self._calculate_uniform_tank_step(
            prosumer, mdot, t_in
        )
        self._temperature = new_t

        soc_fluid = self._soc_from_temperature(prosumer)
        if soc_fluid is not None and not np.isnan(soc_fluid):
            self._soc = soc_fluid
        soc_out = float(self._soc) if not np.isnan(self._soc) else 0.0
        q_delivered_kw = float(np.asarray(q_delivered_kw).flat[0])
        if np.isnan(q_delivered_kw):
            q_delivered_kw = 0.0
        self.last_result = {
            "soc": soc_out,
            "demand_kw": q_delivered_kw,
            "temperature": self._temperature,
            "mdot_kg_per_s": mdot_delivered,
        }
        result = np.array([[soc_out, q_delivered_kw]])
        result_fluid = [{FluidMixMapping.TEMPERATURE_KEY: float(t_out_c),
                         FluidMixMapping.MASS_FLOW_KEY: float(mdot_delivered)}]

        if np.isnan(result).any():
            self.input_mass_flow_with_temp = {
                FluidMixMapping.TEMPERATURE_KEY: np.nan,
                FluidMixMapping.MASS_FLOW_KEY: np.nan,
            }
            return

        if (np.isnan(self.t_keep_return_c) or mdot_delivered == 0 or
                abs(t_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C or
                len(self._get_mapped_initiators_on_same_level(prosumer)) == 0):
            self.finalize(prosumer, result, result_fluid_mix=result_fluid)
            self.applied = True
            self.t_previous_out_c = np.nan
            self.t_previous_in_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
        else:
            self._unapply_initiators(prosumer)
            self.t_previous_out_c = t_out_c
            self.t_previous_in_c = t_in
            self.mdot_previous_in_kg_per_s = mdot_delivered
            self.input_mass_flow_with_temp = {
                FluidMixMapping.TEMPERATURE_KEY: np.nan,
                FluidMixMapping.MASS_FLOW_KEY: np.nan,
            }
