from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types

@enforce_types
@dataclass
class HeatStorageElementData:
    """
    Data class for HeatStorageElement.

    Attributes
    ----------
    name : str
        Name of the element.
    input : List[tuple]
        List of input attributes and their data types.
    """
    name: str = "heat_storage"
    input: List[tuple] = field(default_factory=lambda: [
        # Necessary properties
        ('name', dtype(object)),
        ('in_service', bool),

        # Instance properties
        ('q_capacity_kwh', 'f8')
    ])
