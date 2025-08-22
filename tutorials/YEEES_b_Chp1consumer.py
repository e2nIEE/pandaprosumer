"""
YEEES: Aleja shopping centre

Component & configuration testing

Model: 1 source + 1 consumer

CHP ---- HEAT DEMAND

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
size_kw = 700
altitude_m = 0
fuel = 'ng'
name = 'example_chp'


# TIME PERIOD
start = '2020-01-01 00:00:00'
end = '2020-01-02 00:00:00'
time_resolution_s = 900         # 15 min
frequency = '15min'


# HEAT DEMAND
demand_data = pd.read_excel('data/input_chp.xlsx')
dur = pd.date_range(start, end, freq=frequency, tz='utc')
demand_data.index = dur
demand_input = DFData(demand_data)


# CREATING ELEMENTS
prosumer = create_empty_prosumer_container()
period = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')

# const profile controller
input_columns = ['q_demand_kw', 'cycle', 't_intake_k']
output_columns = ['q_demand_cp_kw', 'cycle_cp', 't_intake_cp_k']
cp_index = create_controlled_const_profile(prosumer, input_columns, output_columns, demand_input, period, level=1, order=0)

# ice chp controller
ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=1, order=1)

# heat demand controller
heat_demand_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=1, order=2)


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
    order = 0)

# mapping: ice chp --> heat demand
GenericMapping(
    prosumer,                                              
    initiator_id = ice_chp_index,                                             
    initiator_column = "p_th_out_kw",
    responder_id = heat_demand_index,                                           
    responder_column = "q_received_kw",
    order = 0
)

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
print("ICE CHP RESULTS: \n")
print(prosumer.time_series.data_source.loc[0].df.head())

# (5) Consumer time series 
print("\n")
print("CONSUMER DATA: \n")
print(prosumer.time_series.data_source.loc[1].df.head())

# (6) Input data plot
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

# (7) ICE CHP power out plot
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

# (8) Heat demand plot
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


