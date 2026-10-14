from dataclasses import dataclass, field
from typing import List

from numpy import dtype

from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class BatteryStorageElementData:
    """
    Static battery storage parameters.

    Parameters
    ----------
    name : object
        Name of the battery storage unit.
    in_service : bool
        Whether the battery is active in the simulation.
    e_capacity_kwh : float
        Battery energy capacity in kWh.
    p_charge_max_kw : float
        Maximum charging power in kW.
    p_discharge_max_kw : float
        Maximum discharging power in kW.
    eta_charge : float
        Charging efficiency in the range (0, 1].
    eta_discharge : float
        Discharging efficiency in the range (0, 1].
    soc_min : float
        Minimum allowed state of charge.
    soc_max : float
        Maximum allowed state of charge.
    self_discharge_per_hour : float
        Fractional energy loss per hour.
    """
    name: str = "battery_storage"

    input: List[tuple] = field(
        default_factory=lambda: [
            ("name", dtype(object)),
            ("in_service", bool),

            ("e_capacity_kwh", "f8"),
            ("p_charge_max_kw", "f8"),
            ("p_discharge_max_kw", "f8"),
            ("eta_charge", "f8"),
            ("eta_discharge", "f8"),
            ("soc_min", "f8"),
            ("soc_max", "f8"),
            ("self_discharge_per_hour", "f8")
        ]
    )