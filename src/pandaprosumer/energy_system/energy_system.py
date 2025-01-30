# Copyright (c) 2020-2022 by Fraunhofer Institute for Energy Economics
# and Energy System Technology (IEE), Kassel. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.

import copy

import pandas as pd
from numpy import dtype
import numpy as np
from pandapower import pandapowerNet
from pandapower.auxiliary import ADict

from pandapipes import __version__
from pandapipes import pandapipesNet

from pandaprosumer.pandaprosumer_container import pandaprosumerContainer, get_default_prosumer_container_structure

try:
    import pandaplan.core.pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)



class EnergySystem(ADict):
    """
        A 'EnergySyste,' is a frame for different pandapipes & pandapower nets, pandaprosumer and coupling controllers.

        Usually, a energy system is a multi energy system which one net per energy carrier and several prosumers.
        The coupled simulation can be run with
        pandaprosumer.energy_system.control.run_control_energy_system.run_control()
        The nets are stored with a unique key in a dictionary in energy_system['nets'].
        The prosumers are stored with a unique key in a dictionary in energy_system['prosumer']
        Superior controllers are stored in energy_system['controller'].
        """

    def __init__(self, *args, **kwargs):
        """

        :param args: item of the ADict
        :type args: variable
        :param kwargs: item of the ADict with corresponding name
        :type kwargs: dict
        """
        super().__init__(*args, **kwargs)
        if isinstance(args[0], self.__class__):
            net = args[0]
            self.clear()
            self.update(**net.deepcopy())

        self['controller'] = pd.DataFrame(np.zeros(0, dtype=self['controller']), index=[])

    def deepcopy(self):
        return copy.deepcopy(self)

    def __repr__(self):  # pragma: no cover
        """
        defines the representation of the energy system in the console

        :return: representation
        :rtype: str
        """

        r = "This energy system includes following nets:"
        for cat in self.nets:
            if isinstance(self['nets'][cat], pandapowerNet):
                r += "\n   - %s (%s pandapowerNet)" % (cat, 1)
            elif isinstance(self['nets'][cat], pandapipesNet):
                r += "\n   - %s (%s pandapipesNet)" % (cat, 1)
            else:
                r += "\n   - %s (%s nets)" % (cat, len(self['nets'][cat]))

        r += "\nThis energy system includes following prosumers:"
        for cat in self.prosumer:
            if isinstance(self['prosumer'][cat], pandaprosumerContainer):
                r += "\n   - %s (%s pandaprosumer)" %(cat, 1)
            else:
                r += "\n   - %s (%s prosumer)" % (cat, len(self['prosumer'][cat]))

        par = []
        for tb in list(self.keys()):
            if isinstance(self[tb], pd.DataFrame) and len(self[tb]) > 0:
                par.append(tb)
            elif tb == 'std_types':
                par.append(tb)
        if par:
            r += "\nFollowing constraints are included:"
            for tb in par:
                r += "\n   - %s (%s elements)" % (tb, len(self[tb]))
        return r


def get_default_energy_system_structure():
    """
    Return the default structure of an empty energy system with categories and data types.

    :return: default structure of an empty energy system
    :rtype: dict
    """
    default_energy_system_structure = {
        # structure data
        # f8, u4 etc. are probably referencing numba or numpy data types
        "name": "",
        "comp_list": [],
        "version": __version__,
        "nets": dict(),
        "prosumer": dict(),
        "controller": [('object', dtype(object)),
                       ('in_service', "bool"),
                       ('order', dtype(object)),
                       ('level', dtype(object)),
                       ('initial_run', 'bool'),
                       ('recycle', 'bool')]}
    return default_energy_system_structure



