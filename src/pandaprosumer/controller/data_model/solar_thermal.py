from dataclasses import dataclass
from dataclasses import field
from typing import List, Callable

from pandaprosumer.element.element_toolbox import enforce_types

@enforce_types
@dataclass

class SolarThermalControllerData:
    """Define format of I/O of a thermal controller in SenergyNets"""
    # come from pandapower/pandapipes

    # an instance of a Mapping, which is a bridge between two controllers
    # assigned_object: List[object]

    # which specific instance(s) of the assigned object (e.g. the row in prosumer.storage) does this controller watch in
    # order to dictate the behaviour of this heat pump
    element_index: List[int]

    # element_variable is the name of a property on the assigned_object which will be read during every time step and recorded into the
    # component dataframe ("component" refers to the actual component type, e.g. "heat_pump"). another controller can
    # watch this value and perform its own logic based on its current state
    # basically, it is the dynamic state variable which lives at the same level as the static instance variables
    # element_variable: str

    # @tecnalia: change here the input time series according to your needs
    # names of input time series
    # profile_name_beam_solar_radiation_w_m2: List[str]
    # profile_name_diffuse_solar_radiation_w_m2: List[str]
    # profile_name_ground_solar_radiation_w_m2: List[str]
    # profile_name_radiation_incidence_angle_deg: List[str]
    # profile_name_ambient_temperature_C: List[str]
    # profile_name_inlet_mass_flow_rate_kg_h: List[str]
    # profile_name_inlet_temperature_C: List[str]

    input_columns: List[str] = field(
        default_factory=lambda: [
            "beam_solar_radiation_w_m2",
            "diffuse_solar_radiation_w_m2",
            "ground_solar_radiation_w_m2",
            "radiation_incidence_angle_deg",
            "ambient_temperature_C",
            "inlet_mass_flow_rate_kg_h",
            "inlet_temperature_C",
        ]
    )

    # Get written into prosumer.time_series after simulation

    result_columns: List[str] = field(
        default_factory=lambda: [
            "outlet_temperature_C",
            "outlet_flow_rate_kg_h",
            "energy_gain_W", #faltan unidades
        ]
    )

    # Generic stuff
    period_index: int = None
    location_index: int = None
    element: str = "solar_thermal"
    element_name: str = "solar_thermal"