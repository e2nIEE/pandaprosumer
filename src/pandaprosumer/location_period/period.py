from dataclasses import dataclass
from dataclasses import field
from typing import List

from numpy import dtype

from pandaprosumer.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class Period:
    name: str = 'period'
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('start', dtype(object)),
        ('end', dtype(object)),
        ('resolution_s', 'f8'),
        ('timezone', dtype(object))])
