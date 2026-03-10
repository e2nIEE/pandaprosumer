import copy

import pandas as pd
from collections.abc import Iterable
import numpy as np
from numpy import dtype, mean

from pandapower.auxiliary import ADict
from pandaprosumer import __version__, CELSIUS_TO_K

import logging

logger = logging.getLogger(__name__)


class pandaprosumerContainer(ADict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if isinstance(args[0], self.__class__):
            prosumer = args[0]
            self.clear()
            self.update(**prosumer.deepcopy())

        self.rerun = False

    def deepcopy(self):
        return copy.deepcopy(self)

    def __repr__(self):  # pragma: no cover
        r = "Following constraints are included:"
        par = []
        excl_list = ['time_series', 'appliances']
        for tb in list(self.keys()):
            if isinstance(self[tb], pd.DataFrame) and len(self[tb]) > 0 and not tb in excl_list:
                par.append(tb)
        for tb in par:
            r += "\n   - %s (%s entries)" % (tb, len(self[tb]))
        # r += "\nFollowintg appliances are considered:"
        # r += "\n   - %s (%s entries)" % ('appliances', len(self['appliances']))
        r += "\nFollowing time_series are generated:"
        r += "\n   - %s (%s entries)" % ('time_series', len(self['time_series']))
        r += "\nFollowing mappings are generated:"
        r += "\n   - %s (%s entries)" % ('mapping', len(self['mapping']))
        r += "\nFollowing Rules are generated:"
        r += "\n   - %s (%s entries)" % ('rules', len(self['rules']))
        return r

    def get_cp_fluid_j_per_kgk(self, t_c):
        """
        Get the heat capacity [J/(kg·K)] of the prosumer's fluid for a temperature t_c [°C].
        Default to 4180.0 [J/(kg·K)] if no valid fluid is defined in the prosumer.
        If t_c is a list of temperature, use the average of the temperatures.
        Use the pandapipes fluid library.

        :param t_c (float | list[float]): Fluid temperature [°C]
        :return: float
        """
        if isinstance(t_c, Iterable):
            t_c = np.mean(t_c)
        fluid = getattr(self, "fluid", None)
        if fluid is not None and hasattr(fluid, "get_heat_capacity"):
            cp_j_per_kgk = fluid.get_heat_capacity(CELSIUS_TO_K + t_c)
        else:
            cp_j_per_kgk = 4180.0  # default water [J/(kg·K)]
        if np.isnan(cp_j_per_kgk) or cp_j_per_kgk <= 0:
            cp_j_per_kgk = 4180.0
        return cp_j_per_kgk


def get_default_prosumer_container_structure():
    default_structure = {
        "name": "",
        "version": __version__,
        "comp_list": [],
        "controller": [('object', dtype(object)),
                       ('in_service', "bool"),
                       ('order', dtype(object)),
                       ('level', dtype(object))],
        "mapping": [('object', dtype(object)),
                    ('initiator', dtype(object)),
                    ('responder', dtype(object)),
                    ('order', dtype(object))],
        "rules": [("object", dtype(object)),
                  ("controlled_columns", dtype(object)),
                  ("operator", dtype(object)),
                  ("threshold_value", dtype(float)),
                  ("controller_index", dtype(object)),
                  ("attribute", dtype(object)),
                  ("new_value", dtype(object)),
                  ("value_if_false", dtype(object)),
                  ("logical_operator", dtype(object)),
                  ("linked_rules", dtype(list))],
        "check_order": "bool"}
    return default_structure
