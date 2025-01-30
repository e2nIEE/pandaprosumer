from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer2.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class DryCoolerElementData:
    """
    Data class for DryCoolerElement.

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = "dry_cooler"
    input: List[tuple] = field(default_factory=lambda: [
        # Necessary properties
        ('name', dtype(object)),

        # Instance properties
        ('n_nom_rpm', 'f8'),
        ('p_fan_nom_kw', 'f8'),
        ('qair_nom_m3_per_h', 'f8'),
        ('t_air_in_nom_c', 'f8'),
        ('t_air_out_nom_c', 'f8'),
        ('t_fluid_in_nom_c', 'f8'),
        ('t_fluid_out_nom_c', 'f8'),
        ('fans_number', 'int'),
        ('adiabatic_mode', bool),
        ('phi_adiabatic_sat_percent', 'f8'),
        ('min_delta_t_air_c', 'f8'),

        ('in_service', bool)
    ])
