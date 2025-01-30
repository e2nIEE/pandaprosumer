from dataclasses import dataclass
from dataclasses import field
from typing import List

from numpy import dtype

from pandaprosumer.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class Location:
    name: str = 'location'
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('long_deg', 'f8'),
        ('lat_deg', 'f8'),
        ('elevation', 'f8'),
        ('state', dtype(object)),
        ('country', dtype(object))])
