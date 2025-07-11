import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData
import sys
import os
from pandaprosumer.create import create_empty_prosumer_container
from pandaprosumer.create import create_period
from pandaprosumer.create_controlled import create_controlled_const_profile
from pandaprosumer.create_controlled import create_controlled_heat_pump,create_controlled_stratified_heat_storage,create_controlled_heat_demand
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries


hp_params = {"carnot_efficiency": 0.5,
             "pinch_c": 0,
             "delta_t_evap_c": 5,
             "max_p_comp_kw": 200,
             "name":'air_water_heat_pump'}

shs_params = {"tank_height_m": 10.,
              "tank_internal_radius_m": 0.564,
              "tank_external_radius_m": 0.664,
              "insulation_thickness_m": .1,
              "n_layers": 100,
              "min_useful_temp_c": 80,
              "t_ext_c": 20,
              "max_dt_s": 1,
              "t_discharge_out_tol_c": 1,
              "name":'tank_heat_storage'}

hd_params = {"name": 'heat_consumer'}
#start = '2020-01-01 02:00:00'
start = '2020-01-01 00:00:00'
end = '2020-01-01 23:59:59'
time_resolution_s = 900

current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
sys.path.append(parent_directory)

demand_data = pd.read_excel('data/hp_data.xlsx')
demand_data['demand_power'][0] = 500

dur = pd.date_range(start=start, end=end, freq='900s',tz='utc')
demand_data.index = dur
demand_input = DFData(demand_data)
demand_input.df.head(10)

prosumer = create_empty_prosumer_container()


period_id = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')

cp_input_columns = ["t_air", "demand_power", "t_feed_demand_c", "t_return_demand_c"]
cp_result_columns = ["t_evap_in_c", "qdemand_kw", "t_feed_demand_c", "t_return_demand_c"]
cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                      demand_input, period_id, 0, 0)

hp_controller_index = create_controlled_heat_pump(prosumer, period=period_id, level=1, order=0, **hp_params)
shs_controller_index = create_controlled_stratified_heat_storage(prosumer, period=period_id, level=1, order=1, **shs_params)
hd_controller_index = create_controlled_heat_demand(prosumer, period=period_id, level=1, order = 2,**hd_params)

GenericMapping(prosumer,
               initiator_id=cp_controller_index,
               initiator_column="t_evap_in_c",
               responder_id=hp_controller_index,
               responder_column="t_evap_in_c",
               order=0)

GenericMapping(prosumer,
               initiator_id=cp_controller_index,
               initiator_column=["qdemand_kw", "t_feed_demand_c", "t_return_demand_c"],
               responder_id=hd_controller_index,
               responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
               order=1)

FluidMixMapping(prosumer,
                initiator_id=hp_controller_index,
                responder_id=shs_controller_index,
                order=0)

FluidMixMapping(prosumer,
                initiator_id=shs_controller_index,
                responder_id=hd_controller_index,
                order=0)



run_timeseries(prosumer, period_id, verbose=True)