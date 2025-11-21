"""
ALEJA

CHILLER - DEMAND

"""

import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData
import sys
import os


# FILE FOLDER
current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
pandaprosumer_directory = os.path.join(parent_directory, "src")
sys.path.append(pandaprosumer_directory)


from pandaprosumer.create import create_empty_prosumer_container
from pandaprosumer.create import create_period
from pandaprosumer.create_controlled import create_controlled_const_profile
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.create_controlled import create_controlled_chiller, create_controlled_heat_demand
from pandaprosumer.run_time_series import run_timeseries
import matplotlib.pyplot as plt


# CHILLER PARAMETER VALUES (STATIC INPUT DATA)
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
    "name": "sn_chiller"
}


# TIME PERIOD
start = '2020-01-01 00:00:00'
end = '2020-01-01 01:59:59'
resol = 3600


# CREATING ELEMENTS
chiller_prosumer = create_empty_prosumer_container()
period_id = create_period(chiller_prosumer, resol, start, end, 'utc', 'default')

# heat demand
demand_data = pd.read_excel('data/senergy_nets_example_chiller.xlsx')
dur = pd.date_range(start, end, freq=f'{resol}s', tz='UTC')
demand_data.index = dur
demand_input = DFData(demand_data)
##print(demand_data.head())

# const profile controller
input_columns = ["Set Point Temperature T_set [K]", "Evaporator inlet temperature T_in_ev [K]", "Condenser inlet temperature T_in_cond [K]",
                       "Condenser temperature increase Dt_cond [K]", "Cooling demand Q_load [kJ/h]", "Isentropic efficiency N_is [-]",
                       "Maximum chiller power Q_max [kJ/h]", "Control signal Ctrl [-]"]

result_columns=["t_set_pt_const_profile_in_c", "t_evap_in_const_profile_in_c", "t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c",
                        "q_chiller_demand_const_profile_kw", "n_is_const_profile", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"]

cp_controller_index = create_controlled_const_profile(chiller_prosumer, input_columns, result_columns, period_id, demand_input, level=0, order=0)

# chiller controller
chiller_controller_index = create_controlled_chiller(chiller_prosumer, period=period_id, level=0, order = 1, **chiller_params) 

# heat demand controller
hd_controller_index = create_controlled_heat_demand(chiller_prosumer, period=period_id, level=0, order = 2, scaling=1.0)


# CONNECTING ELEMENTS
# mapping: const profile --> chiller
GenericMapping(chiller_prosumer,
               initiator_id=cp_controller_index,
               initiator_column=["t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c", "t_evap_in_const_profile_in_c", "n_is_const_profile",
                                 "t_set_pt_const_profile_in_c", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"],
               responder_id=chiller_controller_index,
               responder_column= ["t_in_cond_c", "dt_cond_c", "t_in_ev_c", "n_is", "t_set_pt_c", "q_max_kw", "ctrl"],
               order=0)

# mapping: const profile --> heat demand
GenericMapping(chiller_prosumer,
               initiator_id=cp_controller_index,
               initiator_column=["q_chiller_demand_const_profile_kw"],
               responder_id=hd_controller_index,
               responder_column=["q_demand_kw"],
               order=0)

# mapping: chiller --> heat demand
GenericMapping(chiller_prosumer,
               initiator_id=chiller_controller_index,
               initiator_column=["q_cond_kw"],
               responder_id=hd_controller_index,
               responder_column=["q_received_kw"],
               order=0)


# CALCULATIONS
run_timeseries(chiller_prosumer, period_id, verbose=True)

print(chiller_prosumer.time_series.data_source.loc[0].df)

# PLOTTING
demand_data.plot()
plt.show()

chiller_prosumer.time_series.data_source.loc[0].df.q_evap_kw.plot()
plt.show()




