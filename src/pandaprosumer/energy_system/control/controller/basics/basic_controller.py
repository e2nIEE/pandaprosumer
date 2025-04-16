import numpy as np
import pandas as pd

from pandapower.control.basic_controller import Controller

try:
    from pandaplan.core import pplog
except:
    import logging as pplog

logger = pplog.getLogger(__name__)


class BasicEnergySystemController(Controller):

    @classmethod
    def name(cls):
        return "basic_energy_system_controller"

    def __init__(self, prosumer, basic_energy_system_object, data_source=None,
                 order=-1, level=-1, scale_factor=1., in_service=True, index=None, name=None, **kwargs):
        super(BasicEnergySystemController, self).__init__(prosumer=prosumer,
                                                          basic_prosumer_object=basic_energy_system_object,
                                                          scale_factor=scale_factor,
                                                          in_service=in_service, data_source=data_source,
                                                          order=order, level=level, index=index,
                                                          net=prosumer, **kwargs)

        self.obj = basic_energy_system_object
        if np.iterable(self.obj):
            self.period_index = self.obj[0].period_index
            self.start = prosumer.period.at[self.obj[0].period_index, 'start']
            self.end = prosumer.period.at[self.obj[0].period_index, 'end']
            self.resol = int(prosumer.period.at[self.obj[0].period_index, 'resolution_s'])
            self.result_columns = self.obj[0].result_columns
        else:
            self.period_index = self.obj.period_index
            self.start = prosumer.period.at[self.obj.period_index, 'start']
            self.end = prosumer.period.at[self.obj.period_index, 'end']
            self.resol = int(prosumer.period.at[self.obj.period_index, 'resolution_s'])
            self.result_columns = self.obj.result_columns

        self.dur = pd.date_range(self.start, self.end, freq='%ss' % self.resol)

        self.name = name
