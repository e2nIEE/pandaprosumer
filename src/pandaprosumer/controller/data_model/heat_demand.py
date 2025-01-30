from dataclasses import dataclass, field
from typing import List, Dict
from pandaprosumer2.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class HeatDemandControllerData:
    """
    Data class for heat demand controller.

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

        Exactly 3 variables among q_demand_kw, mdot_demand_kg_per_s, t_feed_demand_c, t_return_demand_c
        have to be specified.

        t_feed_demand_c and t_return_demand_c will fall back to the element set values by default if not enough input
        variables are specified.

        **q_demand_kw** - Demand heat power [kW]

        **mdot_demand_kg_per_s** - Demand required mass flow [kg/s]

        **t_feed_demand_c** - Demand required feed temperature level [°C]

        **t_return_demand_c** - Demand required return temperature level [°C]

    result_columns : List[str]
        List of result column names.

        **q_uncovered_kw** - Uncovered heat power. Can be negative if the power provided is greater than the
        required power [kW]
    """
    element_index: List[int]
    element_name: str = 'heat_demand'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: ["q_demand_kw", "mdot_demand_kg_per_s",
                                                              "t_feed_demand_c", "t_return_demand_c"])
    result_columns: List[str] = field(default_factory=lambda: ["q_received_kw", "q_uncovered_kw",
                                                               "mdot_kg_per_s", "t_in_c", "t_out_c"])
