from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class BaseControllerData:
    """
    Data class for base controller.
    Use as dummy controller for testing purposes.

    Attributes
    ----------
    result_columns : List[str]
        List of result column names.
    input_columns : List[str]
        List of input column names.
    """
    result_columns: List[str]
    input_columns: List[str]
