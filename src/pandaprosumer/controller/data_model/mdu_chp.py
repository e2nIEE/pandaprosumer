from dataclasses import dataclass
from dataclasses import field
from typing import List

from pandaprosumer.element.element_toolbox import enforce_types

@enforce_types
@dataclass
class MduChpControllerData:
    """
    Data class for MDU CHP controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    input_columns : List[str]
        List of input column names: Size, Return water temperature, Supply water temperature, Heat demand
    result_columns : List[str]
        List of result column names: q_fuel_mw, p_el_mw
    period_index : int, optional
        Index of the period, default is None.
    element_name : str
        Name of the element.
    """
    element_index: List[int]
    period_index: int = None
    element_name: str = 'mdu_chp'
    input_columns: List[str] = field(default_factory=lambda: ['Size', 'Return water temperature', 'Supply water temperature', 'Heat demand'])
    result_columns: List[str] = field(default_factory=lambda: ['q_fuel_mw', 'p_el_mw'])

