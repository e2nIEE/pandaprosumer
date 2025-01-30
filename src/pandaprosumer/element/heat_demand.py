from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer2.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class HeatDemandElementData:
    """
    Data class for HeatDemandElement.

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = 'heat_demand'
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('scaling', 'f8'),
        ('t_in_set_c', 'f8'),
        ('t_out_set_c', 'f8'),
        ('in_service', 'bool')
    ])
