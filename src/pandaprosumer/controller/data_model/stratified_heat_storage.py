from dataclasses import dataclass, field
from typing import List
from pandaprosumer2.element.component_toolbox import enforce_types


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
        List of result column names.

        **mdot_discharge_kg_per_s** - The storage discharge mass flow [kg/s]

        **t_discharge_c** - The storage discharge temperature [°C]

        **q_delivered_kw** - The storage delivered power to the downstream elements [kW]

        **e_stored_kwh** - The total stored heat energy in the storage above the element
         minimum usefully temperature compared to the initial state [kWh]

    """
    element_index: List[int]
    element_name: str = 'stratified_heat_storage'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: [])
    result_columns: List[str] = field(default_factory=lambda: ['q_received_kw', 'q_delivered_kw', 'q_charge_kw', 'q_discharge_kw', 'e_stored_kwh',
                                                               'mdot_received_kg_per_s', 't_received_in_c', 't_received_out_c',
                                                               'mdot_delivered_kg_per_s', 't_demand_in_c', 't_delivered_out_c',
                                                               'mdot_charge_kg_per_s', 't_charge_out_c',
                                                               'mdot_discharge_kg_per_s', 't_discharge_out_c'])
