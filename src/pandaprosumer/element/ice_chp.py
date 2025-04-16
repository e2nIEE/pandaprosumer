from dataclasses import dataclass
from dataclasses import field
from numpy import dtype
from typing import List

from pandaprosumer.element.element_toolbox import enforce_types

@enforce_types
@dataclass
class IceChpElementData():
    """
    Defines the static input data for the ICE CHP unit.

        :param name: name of the unit assigned when creating a new ICE CHP instance; has a default name
        :param size: size of the ICE CHP defined as the nominal electrical poweror in kW
        :param fuel: type of fuel used to run the ICE CHP (options: ng, sng1, sng2, sng3, sng4, sng5, sng6)
        :param altitude: the altitude above sea level of the ICE CHP installation in m
        :param in_service: defines if the ICE CHP is in the network or not
        """
    #
    name: str = "ice_chp"

    input: List = field(default_factory = lambda: [
        ('size', 'f8'),
        ('fuel', 'str'),
        ('altitude', 'f8'),
        ('in_service', 'bool'),
        ('name', dtype(object))
    ])
