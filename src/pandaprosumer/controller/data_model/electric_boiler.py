from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class ElectricBoilerControllerData:
    """
    Data class for electric boiler controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    element_name : str
        Name of the element.
    period_index : int, optional
        Index of the period, default is None.
    input_columns : List[str]
        List of input column names.
        
    result_columns : List[str]
        List of result column names.

        **q_kw** - The provided heat power [kW]

        **mdot_kg_per_s** - The water mass flow rate through the boiler [kg/s]
        
        **t_in_c** - The temperature at the inlet of the electric boiler (cold return pipe) [°C]
        
        **t_out_c** - The temperature at the outlet of the electric boiler (hot feed pipe) [°C]

        **p_kw** - The boiler consumed electrical power [kW]


    """
    element_index: List[int]
    element_name: str = 'heat_pump'
    period_index: int = None
    input_columns: List[str] = field(
        default_factory=lambda: [])
    result_columns: List[str] = field(
        default_factory=lambda: ['q_kw', 'mdot_kg_per_s', 't_in_c', 't_out_c', 'p_kw'])
