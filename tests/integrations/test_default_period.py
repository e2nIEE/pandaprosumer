from pandaprosumer.run_time_series import *
from pandaprosumer import create_controlled_const_profile
from pandaprosumer.create import create_empty_prosumer_container
from ..data_sources import FROM_CLAUDIA

def _define_and_get_data_source():
    data = pd.read_excel(FROM_CLAUDIA)
    start_time = pd.Timestamp("2020-01-01 00:00:00", tz="UTC")
    data["period"] = pd.date_range(start=start_time, periods=len(data), freq="H")
    data_source = DFData(data)
    return data_source

class TestDefaultPeriod:
    def test_create(self):
        input_columns = ["Tin_cond", "Tout_cond", "Mass-flow-cond", "Tin,evap"]
        result_columns = ["Tin_cond", "Tout_cond", "Mass-flow-cond", "Tin,evap"]
        prosumer = create_empty_prosumer_container()
        data_source = _define_and_get_data_source()
        create_controlled_const_profile(prosumer, input_columns, result_columns, data_source)
        run_timeseries(prosumer)
        assert hasattr(prosumer, "period")