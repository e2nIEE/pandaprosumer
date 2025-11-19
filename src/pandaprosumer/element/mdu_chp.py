from dataclasses import dataclass
from dataclasses import field
from numpy import dtype
from typing import List

from pandaprosumer.element.element_toolbox import enforce_types

@enforce_types
@dataclass
class MduChpElementData():
    """
    Defines the static input data for the MDU CHP unit.

        :param name: name of the unit assigned when creating a new MDU CHP instance
        :param size: size of the MDU CHP defined as the nominal electrical power in kW
        :param in_service: defines if the MDU CHP is in the network or not
    """
    name: str = "mdu_chp"

    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('size', 'f8'),
        ('in_service', 'bool')
    ])
