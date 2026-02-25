from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class OptimizationElementData:
    """
    Data class for OptimizationElement.

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = 'optimization'
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('storage_capacity_kwh', 'f8'),
        ('q_bhp_max', 'f8'),
        ('chp_map', 'O'),
        ('in_service', 'bool')
    ])