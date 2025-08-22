"""
ALEJA

CHILLER - STORAGE - DEMAND

"""

import sys
import os
import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container
from pandaprosumer.create import create_period
from pandaprosumer.create_controlled import create_controlled_const_profile
from pandaprosumer.create_controlled import create_controlled_chiller, create_controlled_heat_demand, create_controlled_heat_storage
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# FILE FOLDER
current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
pandaprosumer_directory = os.path.join(parent_directory, "src")
sys.path.append(pandaprosumer_directory)


# CHILLER PARAMETER VALUES (STATIC INPUT DATA)
chiller_params = {
    "cp_water": 4.18,      # water specific heat capacity [kJ/kgK]
    "t_sh": 5.0,           # superheating temperature [°C]
    "t_sc": 2.0,           # supercooling temperature [°C]
    "pp_cond": 5.0,        # condenser pinch point [delta °C]
    "pp_evap": 5.0,        # evaporator pinch point [delta °C]
    "plf_cc": 0.9,         # Cd coefficient
    "w_evap_pump": 200.0,  # evaporator pump power [kJ/h] 
    "w_cond_pump": 200.0,  # condenser pump power [kJ/h]
    "eng_eff": 1.0,        # motor efficiency 
    "n_ref": "R410A",      # refrigerant type
    "in_service": True,
    "index": None,
    "name": "compressor_chiller"
}


# STORAGE PARAMETER VALUES (STATIC INPUT DATA)
q_capacity_kwh = 200000   #kWh


# TIME PERIOD
start = '2020-01-01 00:00:00'
end = '2020-01-01 23:59:59'
time_resolution_s = 3600


# HEAT DEMAND
demand_data = pd.read_excel('data/example_chiller_2.xlsx')
dur = pd.date_range(start, end, freq=f'{time_resolution_s}s', tz='UTC')
demand_data.index = dur
demand_input = DFData(demand_data)


# CREATING ELEMENTS
prosumer = create_empty_prosumer_container()
period_id = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')


# const profile controller
input_columns = ["Set Point Temperature T_set [K]", "Evaporator inlet temperature T_in_ev [K]", "Condenser inlet temperature T_in_cond [K]",
                       "Condenser temperature increase Dt_cond [K]", "Cooling demand Q_load [kJ/h]", "Isentropic efficiency N_is [-]",
                       "Maximum chiller power Q_max [kJ/h]", "Control signal Ctrl [-]"]

result_columns=["t_set_pt_const_profile_in_c", "t_evap_in_const_profile_in_c", "t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c",
                        "q_chiller_demand_const_profile_kw", "n_is_const_profile", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"]


cp_controller_index = create_controlled_const_profile(prosumer, input_columns, result_columns, demand_input, period_id, level=0, order=0)

# chiller controller
chiller_controller_index = create_controlled_chiller(prosumer, period=period_id, level=0, order = 1, **chiller_params) 

# storage controller
storage_controller_index = create_controlled_heat_storage(prosumer, q_capacity_kwh, level = 0, order=2)

# heat demand controller
hd_controller_index = create_controlled_heat_demand(prosumer, period=period_id, level=0, order = 3, scaling=1.0)


# CONNECTING ELEMENTS
# mapping: const profile --> chiller
GenericMapping(prosumer,
               initiator_id=cp_controller_index,
               initiator_column=["t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c", "t_evap_in_const_profile_in_c", "n_is_const_profile",
                                 "t_set_pt_const_profile_in_c", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"],
               responder_id=chiller_controller_index,
               responder_column= ["t_in_cond_c", "dt_cond_c", "t_in_ev_c", "n_is", "t_set_pt_c", "q_max_kw", "ctrl"],
               order=0)

# mapping: chiller --> storage
GenericMapping(prosumer,
               initiator_id=chiller_controller_index,
               initiator_column=["q_cond_kw"],
               responder_id=storage_controller_index,
               responder_column=["q_received_kw"],
               order=0)

# mapping: storage --> heat demand
GenericMapping(prosumer,
               initiator_id=storage_controller_index,
               initiator_column=["q_delivered_kw"],
               responder_id=hd_controller_index,
               responder_column=["q_received_kw"],
               order=0)

# mapping: const profile --> heat demand
GenericMapping(prosumer,
               initiator_id=cp_controller_index,
               initiator_column=["q_chiller_demand_const_profile_kw"],
               responder_id=hd_controller_index,
               responder_column=["q_demand_kw"],
               order=0)


# CALCULATIONS
run_timeseries(prosumer, period_id, verbose = True)

chiller_results_all = prosumer.time_series.data_source.loc[0].df
storage_results_all = prosumer.time_series.data_source.loc[1].df
demand_results_all = prosumer.time_series.data_source.loc[2].df


# PRINTING & PLOTTING
# (1) Demand:
print("\n")
print("DEMAND DATA: \n")
print(demand_data.head())

# (2) Chiller results:
print("\n")
print("CHILLER RESULTS: \n")
print(chiller_results_all)

# (3) Storage results:
print("\n")
print("STORAGE RESULTS: \n")
print(storage_results_all)

# (4) Demand results:
print("\n")
print("DEMAND RESULTS: \n")
print(demand_results_all)    

# (5) Chiller condenser heat flow:
chiller_results_all.q_cond_kw.plot()
plt.title("CHILLER: q_cond_kw")
plt.xlabel("t [hh:mm]")
plt.ylabel("q_cond [kW]")
plt.show()

# (6) Storage - state of charge:
storage_results_all.soc.plot()
plt.title("STORAGE: soc")
plt.xlabel("t [hh:mm]")
plt.ylabel("SOC [%/100]")
plt.show()

# (7) Storage - heat flow out:
storage_results_all.q_delivered_kw.plot()
plt.title("STORAGE: q_delivered_kw")
plt.xlabel("Time [hh:mm]")
plt.ylabel("q_delivered [kW]")
plt.show()

# (8) Demand - heat flow in:
demand_results_all.q_received_kw.plot()
plt.title("DEMAND: q_received_kw")
plt.xlabel("t [hh:mm]")
plt.ylabel("q_delivered [kW]")
plt.show()

# (9) Demand - set point & inlet temperatures:
column_name1 = 'Set Point Temperature T_set [K]'    
column_name2 = 'Evaporator inlet temperature T_in_ev [K]'  
plt.plot(demand_data.index, demand_data[column_name1], label=column_name1)
plt.plot(demand_data.index, demand_data[column_name2], label=column_name2)
plt.legend()
plt.xlabel("t [hh:mm]")
plt.ylabel("T [K]")
plt.title("EVAPORATOR TEMPERATURES")
#plt.grid(True)
plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=1))  
plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))  # Format the date
plt.xticks(rotation=90) 
plt.tight_layout()
plt.show()

# (10) Chiller compressor power in:
chiller_results_all.w_in_tot_kw.plot()
plt.title("CHILLER: w_in_tot_kw")
plt.xlabel("t [hh:mm]")
plt.ylabel("w_in_tot [kW]")
plt.show() 

# (11) Demand - set point & inlet temperatures:
column_name3 = 'Cooling demand Q_load [kJ/h]'    
plt.plot(demand_data.index, demand_data[column_name3], label=column_name3)
plt.xlabel("t [hh:mm]")
plt.ylabel("Q_load [K]")
plt.title("COOLING DEMAND")
plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=1))  
plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))  # Format the date
plt.xticks(rotation=90) 
plt.tight_layout()
plt.show()   
