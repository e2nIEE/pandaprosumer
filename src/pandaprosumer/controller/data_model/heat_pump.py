from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class HeatPumpControllerData:
    """
    Data class for heat pump controller.

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
        
        **t_evap_in_c** - The feed temperature from the heating network [°C]
        
    result_columns : List[str]
        List of result column names.

        **q_cond_kw** - The provided power at the heat pump condenser [kW]

        **p_comp_kw** - The compressor consumed electrical power [kW]

        **q_evap_kw** - The extracted power at the heat pump evaporator [kW]

        **cop** - The operating Coefficient Of Performance []
        
        **mdot_cond_kg_per_s** - The mass flow rate at the condenser of the heat pump [kg/s]
        
        **t_cond_in_c** - The input temperature at the condenser of the heat pump (return pipe) [°C]
        
        **t_cond_out_c** - The output temperature at the condenser of the heat pump (feed pipe) [°C]
                
        **mdot_evap_kg_per_s** - The mass flow rate at the evaporator of the heat pump [kg/s]
        
        **t_evap_in_c** - The input temperature at the evaporator of the heat pump (feed pipe) [°C]
        
        **t_evap_out_c** - The output temperature at the evaporator of the heat pump (return pipe) [°C]
    """
    element_index: List[int]
    element_name: str = 'heat_pump'
    period_index: int = None
    input_columns: List[str] = field(
        default_factory=lambda: ["t_evap_in_c"])
    result_columns: List[str] = field(
        default_factory=lambda: ['q_cond_kw', 'p_comp_kw', 'q_evap_kw', 'cop',
                                 'mdot_cond_kg_per_s', 't_cond_in_c', 't_cond_out_c',
                                 'mdot_evap_kg_per_s', 't_evap_in_c', 't_evap_out_c'])
