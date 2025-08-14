"""
ALEJA

1st step in the development of Branch 1
"""

import sys
import os
import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container
from pandaprosumer.create import create_period
from pandaprosumer.create_controlled import create_controlled_const_profile
from pandaprosumer.create_controlled import create_controlled_ice_chp
from pandaprosumer.create_controlled import create_controlled_heat_storage
from pandaprosumer.create_controlled import create_controlled_heat_demand
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
import matplotlib.pyplot as plt


# FILE FOLDER
current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
sys.path.append(parent_directory)


# CHP PARAMETER VALUES (STATIC INPUT DATA)
"""
chp_params = {
    "size_kw": 1400,
    "altitude_m": 0,
    "fuel": "ng",
    "name": "example_chp"
}
"""
size_kw = 1400
altitude_m = 0
fuel = 'ng'
name = 'example_chp'


# STORAGE PARAMETER VALUES (STATIC INPUT DATA)
q_capacity_kwh = 10000


# TIME PERIOD
start = '2020-01-01 00:00:00'
end = '2020-01-02 00:00:00'
time_resolution_s = 900         # 15 min
frequency = '15min'


# HEAT DEMAND
demand_data = pd.read_excel('input_chp_2consumers.xlsx')
dur = pd.date_range(start, end, freq=frequency, tz='utc')
demand_data.index = dur
demand_input = DFData(demand_data)


# CREATING ELEMENTS
prosumer = create_empty_prosumer_container()
period = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')

# const profile controller
input_columns = ['q_demand1_kw', 'q_demand2_kw', 'cycle', 't_intake_k']
output_columns = ['q_demand1_cp_kw', 'q_demand2_cp_kw', 'cycle_cp', 't_intake_cp_k']
cp_index = create_controlled_const_profile(prosumer, input_columns, output_columns, demand_input, period, level=0, order=0)

# ice chp controller
ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=1, order=0)

# heat deman 1 controller
heat_demand1_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=1, order=1)

# heat deman 2 controller
heat_demand2_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=1, order=2)


# CONNECTING ELEMENTS
# mapping: const profile --> ice chp
GenericMapping(
    prosumer,
    initiator_id = cp_index,
    initiator_column = "cycle_cp",
    responder_id = ice_chp_index,
    responder_column = "cycle",
    order = 0)

GenericMapping(
    prosumer,
    initiator_id = cp_index,
    initiator_column = "t_intake_cp_k",
    responder_id = ice_chp_index,
    responder_column = "t_intake_k",
    order = 1)

# mapping: ice chp --> heat demand 1
GenericMapping(
    prosumer,                                              
    initiator_id = ice_chp_index,                                             
    initiator_column = "p_th_out_kw",
    responder_id = heat_demand1_index,                                           
    responder_column = "q_received_kw",
    order = 0)


# mapping: ice chp --> heat demand 2
GenericMapping(
    prosumer,                                              
    initiator_id = ice_chp_index,                                             
    initiator_column = "p_th_out_kw",
    responder_id = heat_demand2_index,                                           
    responder_column = "q_received_kw",
    order = 1)

# mapping: const profile --> heat demand 1
GenericMapping(
    prosumer,                                                  
    initiator_id = cp_index,                                               
    initiator_column = "q_demand1_cp_kw",
    responder_id = heat_demand1_index,                                                
    responder_column = "q_demand_kw",
    order = 0)

# mapping: const profile --> heat demand 2
GenericMapping(
    prosumer,                                                  
    initiator_id = cp_index,                                               
    initiator_column = "q_demand2_cp_kw",
    responder_id = heat_demand2_index,                                                
    responder_column = "q_demand_kw",
    order = 1)


# CALCULATIONS
run_timeseries(prosumer, period, True)


# PRINTING & PLOTTING
# (1) Demand
print("\n")
print("DEMAND DATA: \n")
print(demand_data.head())

# (2) Heat demand elements 
print("\n")
print("HEAT DEMAND ELEMENTS: \n")
print(prosumer.heat_demand)

# (3) Heat demand elements 
print("\n")
print("CREATED TIME SERIES: \n")
print(prosumer.time_series)

# (4) ICE CHP time series 
print("\n")
print("ICE CHP RESULTS: \n")
print(prosumer.time_series.data_source.loc[0].df.head())

# (5) Consumer time series 
print("\n")
print("CONSUMER 1 DATA: \n")
print(prosumer.time_series.data_source.loc[1].df.head())

# (6) Consumer time series 
print("\n")
print("CONSUMER 2 DATA: \n")
print(prosumer.time_series.data_source.loc[2].df.head())

# (7) Input data plot
demand_data.plot()
plt.title("Input data")
plt.xlabel("t [hh:mm]")
plt.ylabel("q_demand_kw [kW]")
plt.grid(
    True,             # Show grid
    which='both',     # 'major', 'minor', 'both'
    axis='both',      # 'x', 'y', 'both'
    linestyle='--',   # Line style (e.g., '-', '--', ':', '-.')
    linewidth=0.5,    # Line width
    color='gray',     # Grid color
    alpha=0.7         # Transparency
    )
plt.show()

# (8) ICE CHP power out plot
prosumer.time_series.data_source.loc[0].df.p_th_out_kw.plot()
plt.title("ICE CHP: p_th_out_kw")
plt.xlabel("t [hh:mm]")
plt.ylabel("p_th_out [kW]")
plt.grid(
    True,             # Show grid
    which='both',     # 'major', 'minor', 'both'
    axis='both',      # 'x', 'y', 'both'
    linestyle='--',   # Line style (e.g., '-', '--', ':', '-.')
    linewidth=0.5,    # Line width
    color='gray',     # Grid color
    alpha=0.7         # Transparency
    )
plt.show()

# (9) Heat demand 1 plot
prosumer.time_series.data_source.loc[1].df.q_received_kw.plot()
plt.title("HEAT DEMAND 1: q_received_kw")
plt.xlabel("t [hh:mm]")
plt.ylabel("q_received [kW]")
plt.grid(
    True,             # Show grid
    which='both',     # 'major', 'minor', 'both'
    axis='both',      # 'x', 'y', 'both'
    linestyle='--',   # Line style (e.g., '-', '--', ':', '-.')
    linewidth=0.5,    # Line width
    color='gray',     # Grid color
    alpha=0.7         # Transparency
    )
plt.show()

# (10) Heat demand 2 plot
prosumer.time_series.data_source.loc[2].df.q_received_kw.plot()
plt.title("HEAT DEMAND 2: q_received_kw")
plt.xlabel("t [hh:mm]")
plt.ylabel("q_received [kW]")
plt.grid(
    True,             # Show grid
    which='both',     # 'major', 'minor', 'both'
    axis='both',      # 'x', 'y', 'both'
    linestyle='--',   # Line style (e.g., '-', '--', ':', '-.')
    linewidth=0.5,    # Line width
    color='gray',     # Grid color
    alpha=0.7         # Transparency
    )
plt.show()
