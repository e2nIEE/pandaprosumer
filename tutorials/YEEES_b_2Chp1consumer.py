"""
YEEES: Aleja shopping centre

Component & configuration testing

Model: 2 sources + 1 consumer

CHP 1____
        |
        -----HEAT DEMAND
        |
CHP 2__|

"""

import sys
import os
import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container
from pandaprosumer.create import create_period
from pandaprosumer.create_controlled import create_controlled_const_profile
from pandaprosumer.create_controlled import create_controlled_ice_chp
#from pandaprosumer.create_controlled import create_controlled_heat_storage
from pandaprosumer.create_controlled import create_controlled_heat_demand
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
import matplotlib.pyplot as plt


# FILE FOLDER
current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
pandaprosumer_directory = os.path.join(parent_directory, "src")
sys.path.append(pandaprosumer_directory)


# CHP PARAMETER VALUES (STATIC INPUT DATA)
# CHP 1
size1_kw = 350
altitude1_m = 0
fuel1 = 'ng'
name1 = 'chp_1'

# CHP 2
size2_kw = 1400
altitude2_m = 0
fuel2 = 'ng'
name2 = 'chp_2'


# TIME PERIOD
start = '2020-01-01 00:00:00'
end = '2020-01-02 00:00:00'
time_resolution_s = 900         # 15 min
frequency = '15min'


# HEAT DEMAND
demand_data = pd.read_excel('data/input_2chp_1consumer.xlsx')
dur = pd.date_range(start, end, freq=frequency, tz='utc')
demand_data.index = dur
demand_input = DFData(demand_data)


# CREATING ELEMENTS
prosumer = create_empty_prosumer_container()
period = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')

# const profile controller
input_columns = ['q_demand_kw', 'cycle1', 'cycle2', 't_intake1_k', 't_intake2_k']
output_columns = ['q_demand_cp_kw', 'cycle1_cp', 'cycle2_cp', 't_intake1_cp_k', 't_intake2_cp_k']
cp_index = create_controlled_const_profile(prosumer, input_columns, output_columns, demand_input, period, level=0, order=0)

# ice chp 1 controller
ice_chp1_index = create_controlled_ice_chp(prosumer, size1_kw, fuel1, altitude1_m, name1, level=0, order=1)

# ice chp 2 controller
ice_chp2_index = create_controlled_ice_chp(prosumer, size2_kw, fuel2, altitude2_m, name2, level=0, order=2)

# heat demand controller
heat_demand_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=0, order=3)


# CONNECTING ELEMENTS
# mapping: const profile --> ice chp 1
GenericMapping(
    prosumer,
    initiator_id = cp_index,
    initiator_column = "cycle1_cp",
    responder_id = ice_chp1_index,
    responder_column = "cycle",
    order = 0)

GenericMapping(
    prosumer,
    initiator_id = cp_index,
    initiator_column = "t_intake1_cp_k",
    responder_id = ice_chp1_index,
    responder_column = "t_intake_k",
    order = 0)

# mapping: const profile --> ice chp 2
GenericMapping(
    prosumer,
    initiator_id = cp_index,
    initiator_column = "cycle2_cp",
    responder_id = ice_chp2_index,
    responder_column = "cycle",
    order = 1)

GenericMapping(
    prosumer,
    initiator_id = cp_index,
    initiator_column = "t_intake2_cp_k",
    responder_id = ice_chp2_index,
    responder_column = "t_intake_k",
    order = 1)

# mapping: ice chp 1 --> heat demand
GenericMapping(
    prosumer,                                              
    initiator_id = ice_chp1_index,                                             
    initiator_column = "p_th_out_kw",
    responder_id = heat_demand_index,                                           
    responder_column = "q_received_kw",
    order = 0)

# mapping: ice chp 2 --> heat demand
GenericMapping(
    prosumer,                                              
    initiator_id = ice_chp2_index,                                             
    initiator_column = "p_th_out_kw",
    responder_id = heat_demand_index,                                           
    responder_column = "q_received_kw",
    order = 2)

# mapping: const profile --> heat demand
GenericMapping(
    prosumer,                                                  
    initiator_id = cp_index,                                               
    initiator_column = "q_demand_cp_kw",
    responder_id = heat_demand_index,                                                
    responder_column = "q_demand_kw",
    order = 0)


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
print("ICE CHP 1 RESULTS: \n")
print(prosumer.time_series.data_source.loc[0].df.head())

# (5) ICE CHP time series 
print("\n")
print("ICE CHP 2 RESULTS: \n")
print(prosumer.time_series.data_source.loc[1].df.head())

# (6) Consumer time series 
print("\n")
print("CONSUMER DATA: \n")
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

# (8) ICE CHP 1 power out plot
prosumer.time_series.data_source.loc[0].df.p_th_out_kw.plot()
plt.title("ICE CHP 1: p_th_out_kw")
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

# (9) ICE CHP 2 power out plot
prosumer.time_series.data_source.loc[1].df.p_th_out_kw.plot()
plt.title("ICE CHP 2: p_th_out_kw")
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

# (10) Heat demand plot
prosumer.time_series.data_source.loc[2].df.q_received_kw.plot()
plt.title("HEAT DEMAND: q_received_kw")
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


