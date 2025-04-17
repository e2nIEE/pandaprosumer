# Copyright (c) 2025 by Fraunhofer Institute for Energy Economics
# and Energy System Technology (IEE), Kassel. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.

try:
    import pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)
logger.setLevel(level=logging.WARNING)

import numpy as np
import pandas as pd

from pandapipes import pandapipesNet
from pandapower import pandapowerNet
from pandaprosumer.energy_system import EnergySystem
from pandaprosumer.energy_system import get_default_energy_system_structure

try:
    import pandaplan.core.pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)
logger.setLevel(level=logging.WARNING)


def create_empty_energy_system(name="my_energy_system"):
    """
    This function initializes the energy system datastructure.

    :param name: Name for the energy system
    :type name: string (default "my_energy_system")
    :return: EnergySystem with empty tables
    :rtype: EnergySystem

    :Example:
        >>> mn = create_empty_energy_system("my_first_energy_system")

    """
    energy_system = EnergySystem(get_default_energy_system_structure(), name=name)
    return energy_system


def add_pandaprosumer_to_energy_system(energy_system, pandaprosumer, pandaprosumer_name='my_prosumer', overwrite=False):
    """
    Add a pandaprosumer to the energy system structure.

    :param energy_system: energy system to which a pandaprosumer will be added
    :type energy_system: pandaprosumer.EnergySystem
    :param net: pandaprosumer that will be added to the energy system
    :type net: pandaprosumerContainer
    :param net_name: unique name for the added pandaprosumer
    :type net_name: str
    :default: 'my_prosumer'
    :param overwrite: whether a pandaprosumer should be overwritten if it has the same pandaprosumer_name
    :type overwrite: bool
    :return: pandaprosumer reference is added inplace to the energy system (in energy system['nets'])
    :rtype: None
    """

    if not overwrite and 'prosumer' in energy_system and pandaprosumer_name in energy_system['prosumer']:
        logger.warning("A prosumer with the name %s exists already in the energy system. If you want to "
                       "overwrite it, set 'overwrite' to True." % pandaprosumer_name)
        return
    elif not 'prosumer' in energy_system:
        energy_system.update({'prosumer': dict()})

    energy_system['prosumer'].update({pandaprosumer_name: pandaprosumer})


def add_net_to_energy_system(energy_system, net, net_name='my_network', overwrite=False):
    """
    Add a pandapipes or pandapower net to the energy system structure.

    :param energy_system: energy system to which a pandapipes/pandapower net will be added
    :type energy_system: pandaprosumer.EnergySystem
    :param net: pandapipes or pandapower net that will be added to the energy system
    :type net: pandapowerNet or pandapipesNet
    :param net_name: unique name for the added net, e.g. 'power', 'gas', or 'power_net1'
    :type net_name: str
    :default: 'my_network'
    :param overwrite: whether a net should be overwritten if it has the same net_name
    :type overwrite: bool
    :return: net reference is added inplace to the energy system (in energy_system['nets'])
    :rtype: None
    """
    if net_name in energy_system['nets'] and not overwrite:
        logger.warning("A net with the name %s exists already in the energy system. If you want to "
                       "overwrite it, set 'overwrite' to True." % net_name)
    else:
        energy_system['nets'][net_name] = net
