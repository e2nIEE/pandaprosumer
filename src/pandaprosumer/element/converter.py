from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class ConverterElementData:
    """
    Data class for HeatDemandElement.

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = 'converter'
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('cp_water', 'f8'),
        ('in_service', 'bool')
    ])