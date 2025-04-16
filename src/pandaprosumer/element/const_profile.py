from dataclasses import dataclass, field
from typing import List

from numpy import dtype

from pandaprosumer.element.element_toolbox import enforce_types

@enforce_types
@dataclass
class ConstProfileElementData:
    """
    Data class for constant profile element.

    Attributes
    ----------
    name : str
        Name of the element.
    input : List[tuple]
        List of input attributes and their data types.
    """
    name: str = "const_profile"
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('profile_name', dtype(object)),
        ('scaling', 'f8'),
        ('in_service', 'bool')
    ])
