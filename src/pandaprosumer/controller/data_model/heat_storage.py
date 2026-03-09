from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class HeatStorageControllerData:
    """
    Data class for heat storage controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    input_columns : List[str]
        List of input column names.
    result_columns : List[str]
        List of result column names.
    period_index : int, optional
        Index of the period, default is None.
    element_name : str
        Name of the element.
    """
    element_index: List[int]
    element_name: str = 'heat_storage'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: ["q_received_kw"])
    result_columns: List[str] = field(default_factory=lambda: ["soc", "t_tank_c", "q_ch_kw", "q_dch_kw", "mdot_ch_kg_per_s", "t_ch_in_c", "t_ch_out_c", "mdot_dch_kg_per_s", "t_dch_in_c", "t_dch_out_c"])
