from dataclasses import dataclass
from dataclasses import field
from typing import List

from numpy import dtype

from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class BoosterHeatPumpElementData:
    name: str = "booster_heat_pump"
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('hp_type', 'str'),
        ('in_service', bool)])
    