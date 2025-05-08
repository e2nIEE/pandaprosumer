import copy

import pandas as pd
from numpy import dtype

from pandapower.auxiliary import ADict
from pandaprosumer import __version__

import logging

logger = logging.getLogger(__name__)


class pandaprosumerContainer(ADict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if isinstance(args[0], self.__class__):
            prosumer = args[0]
            self.clear()
            self.update(**prosumer.deepcopy())

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
        return r


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
        "check_order": "bool"}
    return default_structure
