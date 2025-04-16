from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class HeatExchangerControllerData:
    """
    Data class for simple counter-flow heat exchanger controller.

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

        **t_feedin_c** - The feed temperature from the heating network [°C]

    result_columns : List[str]
        List of result column names.

        **mdot_1_kg_per_s** - The mass flow rate at the primary side of the heat exchanger [kg/s]

        **t_1_in_c** - The feed input temperature at the primary side of the heat exchanger [°C]

        **t_1_out_c** - The return output temperature at the primary side of the heat exchanger [°C]

        **mdot_2_kg_per_s** - The mass flow rate at the secondary side of the heat exchanger [kg/s]

        **t_2_in_c** - The return input temperature at the secondary side of the heat exchanger [°C]

        **t_2_out_c** - The feed output temperature at the secondary side of the heat exchanger [°C]
    """
    element_index: List[int]
    element_name: str = 'heat_exchanger'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: ["t_feed_in_c"])
    result_columns: List[str] = field(
        default_factory=lambda: ["mdot_1_kg_per_s", "t_1_in_c", "t_1_out_c",
                                 "mdot_2_kg_per_s", "t_2_in_c", "t_2_out_c"])
