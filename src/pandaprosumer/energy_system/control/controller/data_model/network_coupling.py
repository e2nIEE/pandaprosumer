from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class NetworkCouplingData:
    element_index: List[int]
    element_name: str = 'network_coupling'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: [])
    result_columns: List[str] = field(default_factory=lambda: [])
