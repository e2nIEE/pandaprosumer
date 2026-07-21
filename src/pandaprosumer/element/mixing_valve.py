from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class MixingValveElementData:
    """
    Data class for MixingValveElementData.

    A 3-way mixing valve between a hot producer and a demand wishing a lower
    feed temperature. It recirculates cold return fluid into the supply so the
    responders receive their wished feed temperature, conserving mass and
    energy exactly (constant-cp mixing rule).

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = "mixing_valve"
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),

        ('t_in_nom_c', 'f8'),
        ('overflow_strategy', 'str'),

        ('in_service', bool)
    ])
