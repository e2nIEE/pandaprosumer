from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class NetControllerData:
    """
    Data class for sink controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    element_name : str
        Name of the element.
    input_columns : List[str]
        List of input column names.
    result_columns : List[str]
        List of result column names.
    """
    element_index: List[int]
    element_name: str
    input_columns: List[str]
    result_columns: List[str]
