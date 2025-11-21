"""
ALEJA

CHILLER - DEMAND

"""

import sys
import os

# FILE FOLDER
current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
pandaprosumer_directory = os.path.join(parent_directory, "src")
sys.path.append(pandaprosumer_directory)

import pandas as pd

from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container
from pandaprosumer.create import create_period
from pandaprosumer.create_controlled import create_controlled_const_profile
from pandaprosumer.create_controlled import create_controlled_chiller, create_controlled_heat_demand
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries


chiller_params = {
    "cp_water": 4.18,
    "t_sh": 5.0,             
    "t_sc": 2.0,
    "pp_cond": 5.0,
    "pp_evap": 5.0,
    "plf_cc": 0.9,
    "w_evap_pump": 200.0,
    "w_cond_pump": 200.0,
    "eng_eff": 1.0,
    "n_ref": "R410A",
    "in_service": True,
    "index": None,
    "name": "compressor_chiller"
}


start = '2020-01-01 00:00:00'
end = '2020-01-01 01:59:59'
time_resolution_s = 3600


prosumer = create_empty_prosumer_container()

period_id = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')


demand_data = pd.read_excel('data/senergy_nets_example_chiller.xlsx')
# Generate UTC-aware datetime index
dur = pd.date_range(start, end, freq=f'{time_resolution_s}s', tz='UTC')
demand_data.index = dur
demand_input = DFData(demand_data)
print(demand_data.head())


input_columns = ["Set Point Temperature T_set [K]", "Evaporator inlet temperature T_in_ev [K]", "Condenser inlet temperature T_in_cond [K]",
                       "Condenser temperature increase Dt_cond [K]", "Cooling demand Q_load [kJ/h]", "Isentropic efficiency N_is [-]",
                       "Maximum chiller power Q_max [kJ/h]", "Control signal Ctrl [-]"]

result_columns=["t_set_pt_const_profile_in_c", "t_evap_in_const_profile_in_c", "t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c",
                        "q_chiller_demand_const_profile_kw", "n_is_const_profile", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"]

cp_controller_index = create_controlled_const_profile(prosumer, input_columns, result_columns, demand_input, period_id, level=0, order=0)



chiller_controller_index = create_controlled_chiller(prosumer, period=period_id, level=0, order = 1, **chiller_params) 
hd_controller_index = create_controlled_heat_demand(prosumer, period=period_id, level=0, order = 2,scaling=1.0)


prosumer.sn_chiller


prosumer.heat_demand


prosumer.controller


prosumer.controller.loc[1, 'object'].element_instance



GenericMapping(prosumer,
               initiator_id=cp_controller_index,
               initiator_column=["t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c", "t_evap_in_const_profile_in_c", "n_is_const_profile",
                                 "t_set_pt_const_profile_in_c", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"],
               responder_id=chiller_controller_index,
               responder_column= ["t_in_cond_c", "dt_cond_c", "t_in_ev_c", "n_is", "t_set_pt_c", "q_max_kw", "ctrl"],
               order=0)


GenericMapping(prosumer,
               initiator_id=cp_controller_index,
               initiator_column=["q_chiller_demand_const_profile_kw"],
               responder_id=hd_controller_index,
               responder_column=["q_demand_kw"],
               order=0)


GenericMapping(prosumer,
               initiator_id=chiller_controller_index,
               initiator_column=["q_cond_kw"],
               responder_id=hd_controller_index,
               responder_column=["q_received_kw"],
               order=0)


run_timeseries(prosumer, period_id, verbose=True)


prosumer.time_series


prosumer.time_series.data_source.loc[0].df.head(10)


prosumer.time_series.data_source.loc[1].df.head(10)

