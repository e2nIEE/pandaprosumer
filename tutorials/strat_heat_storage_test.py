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
                                             create_controlled_stratified_heat_storage, create_controlled_heat_pump)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries

import importlib
import pandaprosumer.controller.models.stratified_heat_storage as shs_mod
importlib.reload(shs_mod)


current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
sys.path.append(parent_directory)

size_kw = 700
name = 'example_chp'
altitude_m = 0
fuel = 'ng'

shs_params = {"tank_height_m": 15.,
              "tank_internal_radius_m": 0.564,
              "tank_external_radius_m": 0.664,
              "insulation_thickness_m": .1,
              "n_layers": 100,
              "min_useful_temp_c": 80,
              "t_ext_c": 20,
              "max_dt_s": 1,
              "t_discharge_out_tol_c": 1,
              "name":'tank_heat_storage'}

start = '2020-01-01 00:00:00'
end = '2020-01-01 23:59:59'
time_resolution_s = 900         # 15 min
frequency = '15min'

demand_data = pd.read_excel('data/hp_data.xlsx')
chp_data = pd.read_excel('data/input_chp.xlsx')
chp_data = chp_data.iloc[:-1]

dur = pd.date_range(start=start, end=end, freq='900s',tz='utc')
demand_data.index = dur
chp_data.index = dur
demand_data['t_intake_k'] = chp_data['t_intake_k']
demand_data['cycle'] = chp_data['cycle']
demand_input = DFData(demand_data)


chp_prosumer = create_empty_prosumer_container()

period = create_period(chp_prosumer, time_resolution_s, start, end, 'utc', 'default')
print(period)

cp_input_columns = ["t_air", "demand_power", "t_feed_demand_c", "t_return_demand_c", 'cycle', 't_intake_k']
cp_result_columns = ["t_evap_in_c", "qdemand_kw", "t_feed_demand_c", "t_return_demand_c", 'cycle_cp', 't_intake_cp_k']

cp_index = create_controlled_const_profile(
    chp_prosumer, cp_input_columns, cp_result_columns, demand_input, period, level=0, order=0)

ice_chp_index = create_controlled_ice_chp(chp_prosumer, size_kw, fuel, altitude_m,level=1,order=0, name='chp' )

shs_controller_index = create_controlled_stratified_heat_storage(chp_prosumer, period=period,
                                                                 level=1, order=1, **shs_params)
heat_demand_index = create_controlled_heat_demand(chp_prosumer, name= 'heat_demand', scaling=1.0,level=1,order=2)


GenericMapping(
    chp_prosumer,
    initiator_id=cp_index,
    initiator_column=["cycle_cp","t_intake_cp_k"],
    responder_id=ice_chp_index,
    responder_column=["cycle", "t_intake_k"],
    order = 0
)

GenericMapping(
    chp_prosumer,
    initiator_id=ice_chp_index,
    initiator_column="p_th_out_kw",
    responder_id=shs_controller_index,
    responder_column="q_requested_limit",
    order=2,
)

FluidMixMapping(chp_prosumer,
                initiator_id=shs_controller_index,
                responder_id=heat_demand_index,
                order=0,
)


GenericMapping(
    chp_prosumer,
    initiator_id=cp_index,
    initiator_column=["qdemand_kw", "t_feed_demand_c", "t_return_demand_c"],
    responder_id=heat_demand_index,
    responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
    order=1
)

run_timeseries(chp_prosumer, period, True)

chp_prosumer.time_series.data_source.loc[0].df.head(30)
chp_prosumer.time_series.data_source.loc[1].df.head(30)
chp_prosumer.time_series.data_source.loc[2].df.head(30)