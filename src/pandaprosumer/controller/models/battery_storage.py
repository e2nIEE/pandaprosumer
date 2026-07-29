"""
Module containing the BatteryStorageController class.
"""
import numpy as np
import pandas as pd

from pandaprosumer.controller.base import BasicProsumerController


class BatteryStorageController(BasicProsumerController):
    """
    Controller for battery storage systems.

    Sign convention
    ---------------
    p_requested_kw > 0:
        Battery discharge

    p_requested_kw < 0:
        Battery charge
    """

    def name_class(self):
        return "battery_storage_controller"

    def __init__(self, prosumer, battery_storage_object, order, level, init_soc=0., in_service=True, index=None, **kwargs):
        
        """Initialize the BatteryStorageController"""
        
        super().__init__(prosumer, battery_storage_object, order=order, level=level, in_service=in_service, index=index, **kwargs)

        self._soc = float(init_soc)
        self.last_soc = float(init_soc)

        self.p_requested_kw = 0.0
        self.p_storage_kw = 0.0
        self.p_charge_kw = 0.0
        self.p_discharge_kw = 0.0
        self.p_charge_available_kw = 0.0
        self.p_discharge_available_kw = 0.0
        self.p_request_unmet_kw = 0.0

        self._validate_parameters(prosumer)

    @property
    def soc(self):
        """Return the current state of charge."""
        return self._soc

    @soc.setter
    def soc(self, value):
        self._soc = float(value)

    def _validate_parameters(self, prosumer):
        """Validate battery parameters and the initial SOC"""
        e_capacity_kwh = float(
            self._get_element_param(prosumer, "e_capacity_kwh")
        )
        p_charge_max_kw = float(
            self._get_element_param(prosumer, "p_charge_max_kw")
        )
        p_discharge_max_kw = float(
            self._get_element_param(prosumer, "p_discharge_max_kw")
        )
        eta_charge = float(
            self._get_element_param(prosumer, "eta_charge")
        )
        eta_discharge = float(
            self._get_element_param(prosumer, "eta_discharge")
        )
        soc_min = float(
            self._get_element_param(prosumer, "soc_min")
        )
        soc_max = float(
            self._get_element_param(prosumer, "soc_max")
        )
        self_discharge_per_hour = float(
            self._get_element_param(
                prosumer,
                "self_discharge_per_hour",
            )
        )

        if e_capacity_kwh <= 0.0:
            raise ValueError("e_capacity_kwh must be greater than zero.")
        if p_charge_max_kw < 0.0:
            raise ValueError("p_charge_max_kw must not be negative.")
        if p_discharge_max_kw < 0.0:
            raise ValueError("p_discharge_max_kw must not be negative.")
        if not 0.0 < eta_charge <= 1.0:
            raise ValueError("eta_charge must be within the range (0, 1].")
        if not 0.0 < eta_discharge <= 1.0:
            raise ValueError("eta_discharge must be within the range (0, 1].")
        if not 0.0 <= soc_min < soc_max <= 1.0:
            raise ValueError(
                "SOC limits must satisfy 0 <= soc_min < soc_max <= 1."
            )
        if not soc_min <= self._soc <= soc_max:
            raise ValueError(
                f"init_soc={self._soc} is outside the permitted "
                f"range [{soc_min}, {soc_max}]."
            )
        if self_discharge_per_hour < 0.0:
            raise ValueError(
                "self_discharge_per_hour must not be negative."
            )

    def _requested_power_kw(self):
        """Return the mapped signed battery requester power"""
        try:
            value = self._get_input("p_requested_kw")
        except (KeyError, AttributeError):
            value = self.p_requested_kw

        if value is None:
            return 0.0

        values = np.asarray(value).reshape(-1)
        if values.size == 0 or np.isnan(values[0]):
            return 0.0

        return float(values[0])

    def available_power_kw(self, prosumer):
        """Calculate feasible charge and discharge power for this timestep."""
        e_capacity_kwh = float(
            self._get_element_param(prosumer, "e_capacity_kwh")
        )
        p_charge_max_kw = float(
            self._get_element_param(prosumer, "p_charge_max_kw")
        )
        p_discharge_max_kw = float(
            self._get_element_param(prosumer, "p_discharge_max_kw")
        )
        eta_charge = float(
            self._get_element_param(prosumer, "eta_charge")
        )
        eta_discharge = float(
            self._get_element_param(prosumer, "eta_discharge")
        )
        soc_min = float(
            self._get_element_param(prosumer, "soc_min")
        )
        soc_max = float(
            self._get_element_param(prosumer, "soc_max")
        )
        self_discharge_per_hour = float(
            self._get_element_param(
                prosumer,
                "self_discharge_per_hour",
            )
        )

        dt_h = self.resol / 3600.0

        p_requested_post_self_disch = max(0.0, 1.0 - self_discharge_per_hour * dt_h)
        soc_after_loss = np.clip(self._soc * p_requested_post_self_disch, soc_min, soc_max)

        p_charge_soc_limit_kw = ((soc_max - soc_after_loss) * e_capacity_kwh / (eta_charge * dt_h))
        p_discharge_soc_limit_kw = (eta_discharge * (soc_after_loss - soc_min) * e_capacity_kwh / dt_h)

        p_charge_available_kw = max(0.0, min(p_charge_max_kw, p_charge_soc_limit_kw))
        p_discharge_available_kw = max(0.0, min(p_discharge_max_kw, p_discharge_soc_limit_kw))

        return p_charge_available_kw, p_discharge_available_kw

    def _save_state(self):
        """Backup state before a controller run."""
        self._backup_state = {
            "soc": self._soc,
            "last_soc": self.last_soc,
        }

    def _restore_state(self):
        """Restore state before an internal rerun."""
        if hasattr(self, "_backup_state"):
            self._soc = self._backup_state["soc"]
            self.last_soc = self._backup_state["last_soc"]

    def _update_soc(self, prosumer):
        """Update battery SOC using the accepted battery power."""
        e_capacity_kwh = float(
            self._get_element_param(prosumer, "e_capacity_kwh")
        )
        eta_charge = float(
            self._get_element_param(prosumer, "eta_charge")
        )
        eta_discharge = float(
            self._get_element_param(prosumer, "eta_discharge")
        )
        soc_min = float(
            self._get_element_param(prosumer, "soc_min")
        )
        soc_max = float(
            self._get_element_param(prosumer, "soc_max")
        )
        self_discharge_per_hour = float(
            self._get_element_param(
                prosumer,
                "self_discharge_per_hour",
            )
        )

        dt_h = self.resol / 3600.0
        stored_energy_kwh = self._soc * e_capacity_kwh
        stored_energy_kwh *= max(0.0, 1.0 - self_discharge_per_hour * dt_h)
        stored_energy_kwh += eta_charge * self.p_charge_kw * dt_h
        stored_energy_kwh -= (self.p_discharge_kw * dt_h / eta_discharge)

        calculated_soc = stored_energy_kwh / e_capacity_kwh
        self._soc = float(np.clip(calculated_soc, soc_min, soc_max))

    def control_step(self, prosumer):
        """Apply requested battery power and update the battery SOC."""
        if not prosumer.rerun:
            self._save_state()
        else:
            self._restore_state()

        element_table = getattr(prosumer, self.obj.element_name)
        element_index = self.obj.element_index[0]

        if not (self.in_service and element_table.iloc[element_index].in_service):
            self.p_requested_kw = 0.0
            self.p_storage_kw = 0.0
            self.p_charge_kw = 0.0
            self.p_discharge_kw = 0.0
            self.p_charge_available_kw = 0.0
            self.p_discharge_available_kw = 0.0
            self.p_request_unmet_kw = 0.0
            self._finalize_results(prosumer)
            self.applied = True
            return

        super().control_step(prosumer)

        self.last_soc = self._soc
        self.p_requested_kw = self._requested_power_kw()

        (self.p_charge_available_kw, self.p_discharge_available_kw) = self.available_power_kw(prosumer)

        self.p_storage_kw = float(np.clip(self.p_requested_kw, -self.p_charge_available_kw, self.p_discharge_available_kw))
        self.p_charge_kw = max(-self.p_storage_kw, 0.0)
        self.p_discharge_kw = max(self.p_storage_kw, 0.0)
        self.p_request_unmet_kw = (self.p_requested_kw - self.p_storage_kw)

        self._update_soc(prosumer)

        if not 0.0 <= self._soc <= 1.0:
            raise AssertionError(
                f"SOC = {self._soc} invalid for controller {self.name} "
                f"in prosumer {prosumer.name} at timestep {self.time}"
            )

        self._finalize_results(prosumer)
        self.applied = True

    def _finalize_results(self, prosumer):
        """Build the result array and call the pandaprosumer finalize method."""
        e_capacity_kwh = float(
            self._get_element_param(prosumer, "e_capacity_kwh")
        )
        e_stored_kwh = self._soc * e_capacity_kwh

        result = np.array(
            [
                pd.Series(self._soc),
                pd.Series(self.p_storage_kw),
                pd.Series(self.p_charge_kw),
                pd.Series(self.p_discharge_kw),
                pd.Series(self.p_charge_available_kw),
                pd.Series(self.p_discharge_available_kw),
                pd.Series(self.p_request_unmet_kw),
                pd.Series(e_stored_kwh)
            ]
        )

        self.last_result = {
            "soc": self._soc,
            "p_storage_kw": self.p_storage_kw,
            "p_charge_kw": self.p_charge_kw,
            "p_discharge_kw": self.p_discharge_kw,
            "p_charge_available_kw": self.p_charge_available_kw,
            "p_discharge_available_kw": self.p_discharge_available_kw,
            "p_request_unmet_kw": self.p_request_unmet_kw,
            "e_stored_kwh": e_stored_kwh
        }

        self.finalize(prosumer, result.T)

    def set_requested_power(self, p_requested_kw):
        """Set signed requested power directly."""
        self.p_requested_kw = float(p_requested_kw)