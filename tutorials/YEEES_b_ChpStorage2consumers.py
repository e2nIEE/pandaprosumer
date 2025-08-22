"""
YEEES: Aleja shopping centre

Component & configuration testing

Model: 1 source + storage + 2 consumers 

                   ___HEAT DEMAND 1
                  /
CHP---STORAGE----|
                 \____HEAT DEMAND 2

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
pandaprosumer_directory = os.path.join(parent_directory, "src")
sys.path.append(pandaprosumer_directory)


# CHP PARAMETER VALUES (STATIC INPUT DATA)
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
demand_data = pd.read_excel('data/input_chp_2consumers.xlsx')
dur = pd.date_range(start, end, freq=frequency, tz='utc')
demand_data.index = dur
demand_input = DFData(demand_data)


# CREATING ELEMENTS
prosumer = create_empty_prosumer_container()
period_id = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')


# const profile controller
input_columns = ['q_demand1_kw', 'q_demand2_kw', 'cycle', 't_intake_k']
result_columns = ['q_demand1_cp_kw', 'q_demand2_cp_kw', 'cycle_cp', 't_intake_cp_k']
cp_index = create_controlled_const_profile(prosumer, input_columns, result_columns, demand_input, period_id, level=0, order=0)

# ice chp controller
ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=2, order=0)

# storage controller
heat_storage_index = create_controlled_heat_storage(prosumer, q_capacity_kwh, level=2, order=1)

# heat demand 1 controller
heat_demand1_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=2, order=2)

# heat demand 2 controller
heat_demand2_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=2, order=3)


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

# mapping: ice chp --> storage
GenericMapping(
    prosumer,
    initiator_id = ice_chp_index,
    initiator_column = "p_th_out_kw",
    responder_id = heat_storage_index,
    responder_column = "q_received_kw",
    order = 0)

# mapping: storage --> heat demand 1
GenericMapping(
    prosumer,
    initiator_id = heat_storage_index,
    initiator_column = "q_delivered_kw",
    responder_id = heat_demand1_index,
    responder_column = "q_received_kw",
    order = 1)

# mapping: storage --> heat demand 2
GenericMapping(
    prosumer,
    initiator_id = heat_storage_index,
    initiator_column = "q_delivered_kw",
    responder_id = heat_demand2_index,
    responder_column = "q_received_kw",
    order = 2)

# mapping: const profile --> heat demand 1
GenericMapping(
    prosumer,                                                  
    initiator_id = cp_index,                                               
    initiator_column = "q_demand1_cp_kw",
    responder_id = heat_demand1_index,                                                
    responder_column = "q_demand_kw",
    order = 1)

# mapping: const profile --> heat demand 2
GenericMapping(
    prosumer,                                                  
    initiator_id = cp_index,                                               
    initiator_column = "q_demand2_cp_kw",
    responder_id = heat_demand2_index,                                                
    responder_column = "q_demand_kw",
    order = 2)


# CALCULATIONS
run_timeseries(prosumer, period_id, True)


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
print("ICE CHP: \n")
print(prosumer.time_series.data_source.loc[0].df.head())

# (5) Storage time series 
print("\n")
print("STORAGE: \n")
print(prosumer.time_series.data_source.loc[1].df.head())

# (6) Consumer 1 time series 
print("\n")
print("CONSUMER 1: \n")
print(prosumer.time_series.data_source.loc[2].df.head())

# (7) Consumer 2 time series 
print("\n")
print("CONSUMER 2: \n")
print(prosumer.time_series.data_source.loc[3].df.head())

# (8) Input data plot
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

# (9) ICE CHP power out plot
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

# (10) Storage state of charge plot
prosumer.time_series.data_source.loc[1].df.soc.plot()
plt.title("STORAGE: SOC")
plt.xlabel("t [hh:mm]")
plt.ylabel("SOC [-]")
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

# (11) Heat demand 1 plot
prosumer.time_series.data_source.loc[2].df.q_received_kw.plot()
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

# (12) Heat demand 2 plot
prosumer.time_series.data_source.loc[3].df.q_received_kw.plot()
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


