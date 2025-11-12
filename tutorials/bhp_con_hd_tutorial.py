import sys
import os
import pandas as pd
import matplotlib.pyplot as plt

repo_root = os.path.abspath(os.path.join(os.getcwd(), os.pardir))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_ice_chp,
                                             create_controlled_heat_storage, create_controlled_heat_demand,
                                             create_controlled_stratified_heat_storage, create_controlled_heat_pump,
                                             create_controlled_booster_heat_pump,create_controlled_converter)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries

import importlib
import pandaprosumer.controller.models.stratified_heat_storage as shs_mod
importlib.reload(shs_mod)


current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
sys.path.append(parent_directory)


start = '2020-01-01 00:00:00'
end = '2020-01-01 23:59:59'
time_resolution_s = 900        # 15 min
frequency = '15min'

bhp_type = 'water-water1'
bhp_name = 'example_bhp'

demand_data = pd.read_excel('data/input_bhp.xlsx')
demand_data['t_feed_demand_c'] = 60
demand_data['t_return_demand_c'] = 20
demand_data["mode"] = 3
demand_data["t_supply_c"] = 70

demand_data["q_demand_kw"] *= 5

dur = pd.date_range(start=start, end=end, freq=frequency, tz='utc')
demand_data.index = dur
demand_input = DFData(demand_data)

print(demand_data.head())

prosumer = create_empty_prosumer_container()

period = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')

input_params = ['mode', 't_source_k', 'q_demand_kw', "t_feed_demand_c", "t_return_demand_c", "t_supply_c"]
result_params = ['mode_cp', 't_source_cp_k', 'q_demand_cp_kw', "t_feed_demand_cp_c", "t_return_demand_cp_c", "t_supply_cp_c"]

cp_index = create_controlled_const_profile(
    prosumer, input_params, result_params, demand_input, period)

bhp_index = create_controlled_booster_heat_pump(prosumer, bhp_type, bhp_name,level=1,order=0)

gen_to_fluidmix_index = create_controlled_converter(prosumer, name='converter', level=1, order=1)

heat_demand_index = create_controlled_heat_demand(prosumer, name= 'heat_demand', scaling=1.0,level=1,order=3)

GenericMapping(
    prosumer,
    initiator_id=cp_index,
    initiator_column=["mode_cp","t_source_cp_k"],
    responder_id=bhp_index,
    responder_column=["mode", "t_source_k"],
)

GenericMapping(
    prosumer,
    initiator_id=cp_index,
    initiator_column=["t_supply_cp_c"],
    responder_id=gen_to_fluidmix_index,
    responder_column=["t_supply_c"],
)

GenericMapping(
    prosumer,
    initiator_id=cp_index,
    initiator_column=["q_demand_cp_kw", "t_feed_demand_cp_c", "t_return_demand_cp_c"],
    responder_id=heat_demand_index,
    responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
)


GenericMapping(
    prosumer,
    initiator_id=bhp_index,
    initiator_column="q_floor",
    responder_id=gen_to_fluidmix_index,
    responder_column="q_received_kw",
)


FluidMixMapping(
    prosumer,
    initiator_id=gen_to_fluidmix_index,
    responder_id=heat_demand_index,
)

run_timeseries(prosumer, period, True)

res_df = prosumer.time_series.copy()
res_df.set_index('name', inplace=True)

# Erstes Plot-Fenster und erste Y-Achse (linke Seite)
fig, ax1 = plt.subplots()

# Plots auf der ersten Achse (Leistung in kW)
#res_df.data_source.loc['tank_heat_storage'].df.q_discharge_kw.plot(ax=ax1, legend=True, label='q_discharge_kw')
# res_df.data_source.loc['tank_heat_storage'].df.q_delivered_kw.plot(ax=ax1, legend=True, label='q_delivered_kw')
res_df.data_source.loc['example_bhp'].df.q_floor.plot(ax=ax1, legend=True, label='q_floor', linestyle=':')
res_df.data_source.loc['heat_demand'].df.q_received_kw.plot(ax=ax1, legend=True, label='q_received_kw', linestyle='--')
res_df.data_source.loc['heat_demand'].df.q_uncovered_kw.plot(ax=ax1, legend=True, label='q_uncovered_kw', linestyle='--')

ax1.set_ylabel("Thermal power (kW)")
ax1.set_title("Heat Storage")

# Zweite Achse (rechte Seite)
# ax2 = ax1.twinx()
# res_df.data_source.loc['tank_heat_storage'].df.e_stored_kwh.plot(ax=ax2, legend=True, color='black', label='e_stored_kwh', linestyle='-')
# ax2.set_ylabel("Stored energy (kWh)")

# Legenden zusammenführen (optional)
# lines_1, labels_1 = ax1.get_legend_handles_labels()
# lines_2, labels_2 = ax2.get_legend_handles_labels()
# ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')

plt.show()

