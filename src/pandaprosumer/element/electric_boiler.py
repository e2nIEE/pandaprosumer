from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class ElectricBoilerElementData:
    """
    Data class for ElectricBoilerElement.

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = "electric_boiler"
    input: List[tuple] = field(default_factory=lambda: [
        # Necessary properties
        ('name', dtype(object)),

        # Instance properties
        ('max_p_kw', 'f8'),
        ('efficiency_percent', 'f8'),

        ('in_service', bool)
    ])
