from dataclasses import dataclass
from dataclasses import field
from typing import List

from numpy import dtype

from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class SolarThermalElementData:
    """Define format of the parameters of a solar thermal component in SenergyNets.
    """
    name: str = "solar_thermal"
    input: List[tuple] = field(default_factory=lambda: [

        # Necessary properties
        ('name', dtype(object)),
        ('in_service', bool),

        # @tecnalia: TODO: clean this up according to the "datasheet" values defined before
        # Instance properties
        ("collector_area", "f8"),
        ("optical_efficiency", "f8"),
        ("thermal_losses", "f8"),
        ("second_thermal_losses", "f8"),
        ("incidence_angle", "f8"),
        ("flow_rate", "f8"),
        ("test_specific_heat", "f8"),
        ("use_specific_heat", "f8"),
        ("number_collectors", "int"),
        ("series", "int"),
        ("piping_length", "f8"),
        ("piping_diameter", "f8"),
        ("piping_thickness", "f8"),
        ("piping_conductivity", "f8"),
        ("collector_slope", "f8"),
        ("collector_azimut", "f8")

    ])