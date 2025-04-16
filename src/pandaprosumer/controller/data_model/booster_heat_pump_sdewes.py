from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types

@enforce_types
@dataclass
class BoosterHeatPumpControllerData:
    """
    Data class for heat pump controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    input_columns : List[str]
        List of input column names. Inputs are: t_source, demand, mode, q_received_kw, p_received_kw.
    result_columns : List[str]
        List of result column names. Results are: cop_floor, cop_radiator, p_el_floor, p_el_radiator, q_remain, q_floor, q_radiator.
    period_index : int, optional
        Index of the period, default is None.
    element_name : str
        Name of the element.
    """
    element_index: List[int]
    period_index: int = None
    element_name: str = 'booster_heat_pump'
    input_columns: List[str] = field(default_factory=lambda: ["t_source_k", 'demand', 'mode', 'q_received_kw', 'p_received_kw'])
    result_columns: List[str] = field(default_factory=lambda: ['cop', 'q_kw', 'q_remain_kw', 'p_el_kw'])
    
