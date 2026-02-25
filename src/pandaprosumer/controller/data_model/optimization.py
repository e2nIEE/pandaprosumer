from dataclasses import dataclass, field
from typing import List, Dict
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class OptimizationControllerData:
    """
    Data class for Optimization controller.

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

    """
    element_index: List[int]
    element_name: str = 'optimization'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: ["q_demand_kw",
                                                              "p_flex_kw",
                                                              "p_pv_in_kw",
                                                              "cop_bhp"])
    result_columns: List[str] = field(default_factory=lambda: ["p_el_bhp_in",
                                                               "p_el_chp_out"])