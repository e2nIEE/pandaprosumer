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
    element_index: List[int]
    period_index: int = None
    element_name: str = "sn_pv_production"


    input_columns: List[str] = field(
        default_factory=lambda: [
            "p_w",
            "poa_direct_w_m2",  # faltan unidades
            "poa_sky_diffuse_w_m2",
            "poa_ground_diffuse_w_m2",
            "solar_elevation_deg",
            "temp_air_c",
            "wind_speed_m_s",
            "solar_rad_reconstr_bool",
        ]
    )

    # Get written into prosumer.time_series after simulation

    result_columns: List[str] = field(
        default_factory=lambda: [
            "p_w",
            "poa_direct_w_m2", #faltan unidades
            "poa_sky_diffuse_w_m2",
            "poa_ground_diffuse_w_m2",
            "solar_elevation_deg",
            "temp_air_c",
            "wind_speed_m_s",
            "solar_rad_reconstr_bool",
        ]
    )

    # Generic stuff
    location_index: int = None

