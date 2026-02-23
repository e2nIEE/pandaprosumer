from dataclasses import dataclass, field
from numpy import dtype
from typing import List

from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class MduChpElementData:
    """
    Element data structure for MDU CHP unit.
    
    Attributes
    ----------
    name : str
        Name of the MDU CHP unit (default: "mdu_chp")
    input : List[tuple]
        List of input parameter definitions: name, size, in_service
    """
    name: str = "mdu_chp"

    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('size', 'f8'),
        ('in_service', 'bool')
    ])
