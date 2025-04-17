import pandas as pd

from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_period

from pandaprosumer.tests.data_sources import FROM_CLAUDIA


def define_and_get_period_and_data_source(prosumer, resol=3600, file=FROM_CLAUDIA):
    data = pd.read_excel(file)
    start = '2020-01-01 00:00:00'
    end = pd.Timestamp(start) + len(data)*pd.Timedelta(f"00:00:{resol}")-pd.Timedelta("00:00:01")
    dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
    data.index = dur
    data_source = DFData(data)
    period = create_period(prosumer,
                           resol,
                           start,
                           end,
                           'utc',
                           'default')
    return period, data_source
