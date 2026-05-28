from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class StratifiedHeatStorageControllerData:
    """
    Data class for stratified heat storage controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    element_name : str
        Name of the element.
    period_index : int, optional
        Index of the period, default is None.
    input_columns : List[str]
        List of input column names.

    result_columns : List[str]
        List of result column names. Four flows are reported (received, charge,
        discharge, delivered); each as (mdot, t_in, t_out, q):

        **mdot_received_kg_per_s / t_received_in_c / t_received_out_c / q_received_kw** -
        Fluid received from upstream initiators (e.g. a heat pump) and the heat absorbed
        from that fluid by the storage [kg/s, °C, °C, kW].

        **mdot_charge_kg_per_s / t_charge_in_c / t_charge_out_c / q_charge_kw** -
        Portion of the received fluid that charges the storage (rest is bypass to
        delivered). ``t_charge_in_c`` is the storage inlet temperature (same as
        ``t_received_in_c``), ``t_charge_out_c`` is the bottom-of-storage extraction
        temperature [kg/s, °C, °C, kW].

        **mdot_discharge_kg_per_s / t_discharge_in_c / t_discharge_out_c / q_discharge_kw** -
        Fluid pulled from the top of the storage to satisfy demand. ``t_discharge_in_c``
        is the return temperature from downstream, ``t_discharge_out_c`` is the top
        layer temperature [kg/s, °C, °C, kW].

        **mdot_delivered_kg_per_s / t_delivered_in_c / t_delivered_out_c / q_delivered_kw** -
        Total fluid sent to downstream demand (discharge + bypass mixed). ``t_delivered_in_c``
        is the return temperature from downstream [kg/s, °C, °C, kW].

        **e_stored_kwh** - The total stored heat energy in the storage above the element
         minimum usefully temperature compared to the initial state [kWh]

    """
    element_index: List[int]
    element_name: str = 'stratified_heat_storage'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: [])
    result_columns: List[str] = field(default_factory=lambda: [
        "mdot_received_kg_per_s", "t_received_in_c", "t_received_out_c", "q_received_kw",
        "mdot_charge_kg_per_s", "t_charge_in_c", "t_charge_out_c", "q_charge_kw",
        "mdot_discharge_kg_per_s", "t_discharge_in_c", "t_discharge_out_c", "q_discharge_kw",
        "mdot_delivered_kg_per_s", "t_delivered_in_c", "t_delivered_out_c", "q_delivered_kw",
        "e_stored_kwh",
    ])
