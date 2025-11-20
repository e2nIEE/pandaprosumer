from dataclasses import dataclass, field
from typing import List

from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class MduChpControllerData:
    """
    Controller data structure for MDU CHP.

    Attributes
    ----------
    element_index : List[int]
        List of element indices
    period_index : int, optional
        Index of the period (default: None)
    element_name : str
        Name of the element (default: 'mdu_chp')
    input_columns : List[str]
        Input column names: Size, Return water temperature, Supply water temperature, Heat demand
    result_columns : List[str]
        Result column names: q_fuel_mw (fuel input in MW), p_el_mw (electrical output in MW)
    """
    element_index: List[int]
    period_index: int = None
    element_name: str = 'mdu_chp'
    input_columns: List[str] = field(default_factory=lambda: [
        'Size', 
        'Return water temperature', 
        'Supply water temperature', 
        'Heat demand'
    ])
    result_columns: List[str] = field(default_factory=lambda: ['q_fuel_mw', 'p_el_mw'])

