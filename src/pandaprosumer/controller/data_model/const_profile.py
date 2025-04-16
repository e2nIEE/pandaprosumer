from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class ConstProfileControllerData:
    """
    Data class for constant profile controller.

    Attributes
    ----------
    input_columns : List[str]
        List of input column names.
    result_columns : List[str]
        List of result column names.
    period_index : int, optional
        Index of the period, default is None.
    """
    input_columns: List[str]
    result_columns: List[str]
    period_index: int = None
