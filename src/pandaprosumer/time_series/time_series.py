from dataclasses import dataclass
from dataclasses import field
from typing import List

from numpy import dtype

from pandaprosumer.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class TimeSeries:
    name: str = 'time_series'
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),
        ('element', dtype(object)),
        ('element_index', 'u4'),
        ('period_index', 'u4'),
        ('data_source', dtype(object))])
