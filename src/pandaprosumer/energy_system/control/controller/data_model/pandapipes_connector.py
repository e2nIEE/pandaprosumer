from dataclasses import dataclass, field
from typing import List
from pandaprosumer2.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class PandapipesConnectorControllerData:
    """
    Data class for PandapipesFeedConnector controller.

    Attributes
    ----------
    input_columns : List[str]
        List of input column names.
    result_columns : List[str]
        List of result column names.
    """
    period_index: int = None  # FixMe: Adding a period is convenient for debugging to get a timeseries
    input_columns: List[str] = field(default_factory=lambda: [])
    result_columns: List[str] = field(default_factory=lambda: ["mdot_delivered_kg_per_s", "mdot_bypass_kg_per_s",
                                                               "t_received_in_c", "t_return_out_c", "t_in_required_c"])
