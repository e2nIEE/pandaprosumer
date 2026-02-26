from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class HeatStorageElementData:
    """
    Data class for HeatStorageElement.

    Attributes
    ----------
    name : str
        Name of the element.
    input : List[tuple]
        List of input attributes and their data types.
    """
    name: str = "heat_storage"
    input: List[tuple] = field(default_factory=lambda: [
        # Necessary properties
        ('name', dtype(object)),
        ('in_service', bool),

        # Power-only mode (GenericMapping)
        ('q_capacity_kwh', 'f8'),

        # Optional: FluidMix / uniform tank mode
        ('capacity_kg', 'f8'),       # Tank fluid mass [kg]; if set, enables FluidMixMapping
        ('init_temperature_c', 'f8'),  # Initial uniform tank temperature [°C]
        ('min_temp_c', 'f8'),       # Min temperature for SOC from T (optional)
        ('max_temp_c', 'f8'),       # Max temperature for SOC from T (optional)
        ('u_w_per_m2k', 'f8'),      # Wall U-value [W/(m²·K)]
        ('area_wall_m2', 'f8'),     # Wall area [m²]
        ('t_ext_c', 'f8'),         # Ambient temperature for losses [°C]
    ])
