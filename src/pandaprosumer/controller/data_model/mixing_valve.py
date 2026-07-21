from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class MixingValveControllerData:
    """
    Data class for the 3-way mixing valve controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    element_name : str
        Name of the element.
    period_index : int, optional
        Index of the period, default is None.
    input_columns : List[str]
        List of input column names (none: the received temperature and mass
        flow come from the upstream FluidMixMapping).
    result_columns : List[str]
        List of result column names.

        **q_delivered_kw** - Thermal power delivered to the responders [kW]

        **mdot_in_kg_per_s** - Hot-leg mass flow drawn from the producer [kg/s]

        **t_in_c** - Received supply temperature [°C]

        **mdot_recirc_kg_per_s** - Recirculated return mass flow [kg/s]

        **mdot_out_kg_per_s** - Mixed mass flow delivered downstream [kg/s]

        **t_out_c** - Mixed feed temperature delivered downstream [°C]

        **t_return_c** - Return temperature (identical toward producer and from responders) [°C]
    """
    element_index: List[int]
    element_name: str = 'mixing_valve'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: [])
    result_columns: List[str] = field(
        default_factory=lambda: ["q_delivered_kw",
                                 "mdot_in_kg_per_s", "t_in_c",
                                 "mdot_recirc_kg_per_s",
                                 "mdot_out_kg_per_s", "t_out_c", "t_return_c"])
