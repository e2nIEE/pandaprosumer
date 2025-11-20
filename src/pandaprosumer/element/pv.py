from dataclasses import dataclass
from dataclasses import field
from typing import List

from numpy import dtype

from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class SenergyNetsPvProductionComponentData:
    """Define format of the parameters of PV production in SenergyNets.
    """
    name: str = "sn_pv_production"
    input: List[tuple] = field(default_factory=lambda: [

        # Necessary properties
        ('name', dtype(object)),
        ('in_service', bool),

        # @tecnalia: TODO: clean this up according to the "datasheet" values defined before
        # Instance properties
        ("latitude", "f8"),
        ("longitude", "f8"),
        ("raddatabase", dtype(object)),
        ("surface_tilt", "f8"),
        ("surface_azimuth", "f8"),
        ("peakpower", "f8"),
        ("loss", "f8"),
        ("usehorizon", bool),
        ("userhorizon", dtype(object)),
        ("pvtechchoice", dtype(object)),
        ("mountingplace", dtype(object)),
        ("trackingtype", int),
        ("optimal_surface_tilt", bool),
        ("optimalangles", bool),
        ("outputformat", dtype(object)),
        ("url", dtype(object)),
        ("map_variables", bool),
        ("timeout", "f8")

    ])