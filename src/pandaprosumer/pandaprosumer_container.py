import copy
import os

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


def save_prosumer_results(prosumer, res_folder):
    """
    Save the results of a prosumer simulation to CSV files.
    
    Args:
        prosumer: The prosumer container object
        res_folder: The base folder path where results will be saved
    """
    # for prosumer in energy_system.prosumer.values():
    for i, ts in prosumer.time_series.iterrows():
        try:
            folder_path = os.path.join(res_folder, "prosumers", prosumer.name, f"res_{ts.element}")
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
            
            # Handle both dict-like access and attribute access for ts['name']
            try:
                series_name = ts['name'] if hasattr(ts, '__getitem__') else ts.name
            except (AttributeError, KeyError):
                series_name = f"series_{i}"
            
            output_file = os.path.join(folder_path, f"{series_name}.csv")
            ts.data_source.df.to_csv(output_file)
        except Exception as e:
            logger.warning(f"Prosumer `{prosumer.name}`: Skipping writing results for"
                          f" {ts.element}_{int(ts.element_index)}_{getattr(ts, 'name', 'unknown')}. Reason: {str(e)}")


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
