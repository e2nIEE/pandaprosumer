from dataclasses import dataclass, field
from typing import List
from pandaprosumer2.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class DryCoolerControllerData:
    """
    Data class for dry cooler controller.
    FixMe: n as array or same speed for all fans ?

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

        **mdot_fluid_kg_per_s** - Water required mass flow rate [kg/s]

        **t_in_c** - Water input required temperature [°C]

        **t_out_c** - Water output expected temperature [°C]

        **t_air_in_c** - input dry bulb temperature of the ambient air [°C]

        **phi_air_in_percent** - input relative humidity of the ambient air [°C]

    result_columns : List[str]
        List of result column names.

        **q_exchanged_kw** - Extracted heat power [kW]

        **p_fans_kw** - Electrical power consumed by the fans [kW]

        **n_rpm** - Fans rotational speed [rpm]

        **mdot_air_m3_per_h** - Air mass flow through the cooler [m3/h]
    """
    element_index: List[int]
    element_name: str = 'dry_cooler'
    period_index: int = None
    input_columns: List[str] = field(
        default_factory=lambda: ["mdot_fluid_kg_per_s", "t_in_c", "t_out_c", "t_air_in_c", "phi_air_in_percent"])
    result_columns: List[str] = field(
        default_factory=lambda: ['q_exchanged_kw', 'p_fans_kw', 'n_rpm', 'mdot_air_m3_per_h',
                                 'mdot_air_kg_per_s', 't_air_in_c', 't_air_out_c',
                                 'mdot_fluid_kg_per_s', 't_fluid_in_c', 't_fluid_out_c'])
