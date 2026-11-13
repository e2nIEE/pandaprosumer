"""
Module containing the UniformHeatStorageElementData class.
"""

from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class UniformHeatStorageElementData:
    """
    Data class for the uniform (fully mixed) heat storage element.

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types.
    """
    name: str = "uniform_heat_storage"
    input: List[tuple] = field(default_factory=lambda: [
        # Necessary properties
        ('name', dtype(object)),

        # Instance properties
        ('mass_kg', 'f8'),
        ('e_capacity_kwh', 'f8'),
        ('min_useful_temp_c', 'f8'),
        ('t_full_c', 'f8'),
        ('u_w_per_m2k', 'f8'),
        ('area_wall_m2', 'f8'),
        ('t_ext_c', 'f8'),
        ('max_remaining_capacity_kwh', 'f8'),
        ('t_discharge_out_tol_c', 'f8'),
        ('max_charge_mdot_kg_per_s', 'f8'),
        ('t_charge_target_c', 'f8'),

        ('in_service', bool)
    ])
