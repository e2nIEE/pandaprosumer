from pandapower.timeseries.data_sources.frame_data import DFData
import pandas as pd
import matplotlib.pyplot as plt
from pandaprosumer.create import create_empty_prosumer_container, create_period, create_heat_demand
from pandaprosumer.create_controlled import create_controlled_const_profile, create_controlled_ice_chp, create_controlled_booster_heat_pump, create_controlled_heat_demand
from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping
chp_size = 700
chp_name = 'example_chp'
altitude = 388
fuel = 'ng'

hp_type = "water-water-sdewes"
hp_name1 = 'example_hp1'
hp_name2 = 'example_hp2'
#hp_name3 = 'example_hp3'

q_capacity_kwh = 300

start1 = '2023-08-01 00:00:00'
end1 = '2023-09-25 23:00:00'

start2 = '2023-02-01 00:00:00'
end2 = '2023-03-25 23:00:00'
time_resolution = 900*4

demand_data = pd.read_excel('example_data/input_data_chp_summer.xlsx', skiprows=2)
demand_data = demand_data.fillna(20.0)

dur = pd.date_range(start1, end1, freq="1h", tz='utc')
demand_data.index = dur
demand_input = DFData(demand_data)
prosumer = create_empty_prosumer_container()
period = create_period(prosumer, time_resolution, start1, end1, 'utc', 'default')

cp_input_columns = ['t_source_k', 'demand', 'mode', 'cycle', 'temperature_ice_chp_k']
cp_result_columns = ['t_source_k_c', 'demand_c', 'mode_c', 'cycle_c', 'temperature_ice_chp_k_c']


cp_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns, period, DFData(demand_input), 0, 0)
chp_parameters = {
    'chp_size': 700,
    'chp_name': 'example_chp',
    'altitude': 388,
    'fuel': 'ng'
}
chp_index = create_controlled_heat_demand(prosumer, period=period, level=1, order=0, **chp_parameters)

hp_parameters = {
    'hp_type': "water-water-sdewes",
    'hp_name1': 'example_hp1',
    'q_capacity_kwh': 300
}

