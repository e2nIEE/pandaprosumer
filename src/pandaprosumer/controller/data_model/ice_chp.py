from dataclasses import dataclass
from dataclasses import field
from typing import List, Callable

from pandaprosumer.element.element_toolbox import enforce_types

@enforce_types
@dataclass
class IceChpControllerData:

    """
    Data class for ice chp controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    input_columns : List[str]
        List of input column names. Inputs are: cycle, temperature_ice_chp_k
    result_columns : List[str]
        List of result column names. Results are: p_in_kw, p_el_out_kw, p_th_out_kw, p_rad_out_kw, ice_chp_efficiency, mdot_fuel_in_kg_per_s, acc_m_fuel_in_kg, acc_co2_eq_kg_per_s, acc_co2_inst_kg, acc_nox_mg, acc_time_ice_chp_oper_s
    period_index : int, optional
        Index of the period, default is None.
    element_name : str
        Name of the element.
    """
    element_index: List[int]
    period_index: int = None
    element_name: str = 'ice_chp'
    input_columns: List[str] = field(default_factory=lambda: ['cycle', 'temperature_ice_chp_k'])
    result_columns: List[str] = field(default_factory=lambda: ['p_in_kw', 'p_el_out_kw', 'p_th_out_kw', 'p_rad_out_kw', 'ice_chp_efficiency', 'mdot_fuel_in_kg_per_s', 'acc_m_fuel_in_kg', 'acc_co2_eq_kg_per_s', 'acc_co2_inst_kg', 'acc_nox_mg', 'acc_time_ice_chp_oper_s'])
