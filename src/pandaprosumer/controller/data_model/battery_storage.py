from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class BatteryStorageControllerData:

    """
    Controller data for the battery storage

    Parameters
    ----------
    element_index : list[int]
        Index of the associated battery storage element.
    element_name : str
        Name of the battery storage element table.
    period_index : int, optional
        Index of the simulation period.

    Inputs
    ------
    p_requested_kw : float
        Requested signed battery power in kW. Positive values represent
        discharging and negative values represent charging.

    Results
    -------
    soc : float
        Battery state of charge after the timestep.
    p_storage_kw : float
        Actual signed battery power in kW.
    p_charge_kw : float
        Actual charging power in kW.
    p_discharge_kw : float
        Actual discharging power in kW.
    p_charge_available_kw : float
        Maximum feasible charging power in kW.
    p_discharge_available_kw : float
        Maximum feasible discharging power in kW.
    e_stored_kwh : float
        Stored battery energy in kWh.
    p_request_unmet_kw : float
        Difference between requested and actual battery power in kW.
    """

    element_index: List[int]
    element_name: str = "battery_storage"
    period_index: int = None

    input_columns: List[str] = field(
        default_factory=lambda: ["p_requested_kw"]
    )

    result_columns: List[str] = field(
        default_factory=lambda: [
            "soc",
            "p_storage_kw",
            "p_charge_kw",
            "p_discharge_kw",
            "p_charge_available_kw",
            "p_discharge_available_kw",
            "e_stored_kwh",
            "p_request_unmet_kw"
        ]
    )