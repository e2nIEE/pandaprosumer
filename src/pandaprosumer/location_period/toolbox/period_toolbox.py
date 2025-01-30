import numpy as np
from datetime import date
import datetime as dt


def year_information(prosumer, period_index):
    start = prosumer['period'].at[period_index, 'start']
    end = prosumer['period'].at[period_index, 'end']
    resol = prosumer['period'].at[period_index, 'resolution_s']
    duration = np.arange(start, end, dtype='datetime64[%ss]' % str(int(resol)))
    dur_tuple = np.vectorize(date.timetuple)(duration.astype(dt))
    return dur_tuple