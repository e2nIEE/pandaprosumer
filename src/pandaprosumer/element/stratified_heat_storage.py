from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.component_toolbox import enforce_types


@enforce_types
@dataclass
class StratifiedHeatStorageElementData:
    """
    Data class for StratifiedHeatStorageElementData.

    The stratified heat storage is implemented from *Untrau et al., A fast and accurate 1-dimensional model for dynamic
    simulation and optimization of a stratified thermal energy storage, 2023*

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types.
    """
    name: str = "stratified_heat_storage"
    input: List[tuple] = field(default_factory=lambda: [
        # Necessary properties
        ('name', dtype(object)),

        # Instance properties
        ('tank_height_m', 'f8'),
        ('tank_internal_radius_m', 'f8'),
        ('tank_external_radius_m', 'f8'),
        ('insulation_thickness_m', 'f8'),
        ('n_layers', 'int32'),
        ('min_useful_temp_c', 'f8'),
        ('k_fluid_w_per_mk', 'f8'),
        ('k_insu_w_per_mk', 'f8'),
        ('k_wall_w_per_mk', 'f8'),
        ('h_ext_w_per_m2k', 'f8'),
        ('t_ext_c', 'f8'),
        ('height_charge_in_m', 'f8'),
        ('height_charge_out_m', 'f8'),
        ('height_discharge_out_m', 'f8'),
        ('height_discharge_in_m', 'f8'),

        ('in_service', bool)
    ])
