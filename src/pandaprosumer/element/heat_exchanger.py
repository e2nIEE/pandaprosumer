from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class HeatExchangerElementData:
    """
    Data class for HeatExchangerElementData.

    The heat exchanger is implemented from KS conservation and logarithmic mean temperature difference (LMTD)

    In the heat exchanger element some nominal temperatures and mass flows are specified.
    The resulting return temperature on the primary side is calculated from this state,
    then the primary mass flow is deducted.

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = "heat_exchanger"
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),

        ('t_1_in_nom_c', 'f8'),
        ('t_1_out_nom_c', 'f8'),
        ('t_2_in_nom_c', 'f8'),
        ('t_2_out_nom_c', 'f8'),
        ('mdot_2_nom_kg_per_s', 'f8'),
        ('delta_t_hot_default_c', 'f8'),
        ('max_q_kw', 'f8'),
        ('min_delta_t_1_c', 'f8'),
        ('primary_fluid', 'str'),
        ('secondary_fluid', 'str'),

        ('in_service', bool)
    ])
