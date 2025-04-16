from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class HeatPumpElementData:
    """
    Data class for HeatPumpElement.

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = "heat_pump"
    input: List[tuple] = field(default_factory=lambda: [
        # Necessary properties
        ('name', dtype(object)),

        # Instance properties
        ('delta_t_evap_c', 'f8'),
        ('carnot_efficiency', 'f8'),
        ('pinch_c', 'f8'),
        ('delta_t_hot_default_c', 'f8'),
        ('max_p_comp_kw', 'f8'),
        ('min_p_comp_kw', 'f8'),
        ('max_t_cond_out_c', 'f8'),
        ('max_cop', 'f8'),
        ('cond_fluid', 'str'),
        ('evap_fluid', 'str'),

        # ToDo: Take into account 'in_service' for every models
        ('in_service', bool)
    ])
