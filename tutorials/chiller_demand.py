#!/usr/bin/env python
# coding: utf-8

# # PANDAPROSUMER EXAMPLE: HEAT PUMP WITH HEAT STRATIFIED STORAGE

# ## DESCRIPTION:
# This example describes how to create a single heat pump element in pandaprosumer and connect it to a heat stratified storage unit which is then connected to a single consumer (heat demand). The demand and source temperature data is read from an Excel file and stored in pandas dataframe. It includes the information about the power required by the consumer and source temperature at each time step.
# 
# 
# ![title](img/hp_shs_hd.png)

# ## Glossary:
# - Network: A configuration of connected energy generators and energy consumers
# - Element: A single energy generator or a single energy consumer
# - Controller: The logic of an element that defines its behaviour and its limits
# - Prosumer/Container: A pandaprosumer data structure that holds data related to elements and their controllers.
# - Const Profile Controller: The initial controller in the network that interacts with other element controllers; it also manages external data via time series.
# - Map / mapping: A connection between two controllers that specifies what information is exchanged between the corresponding elements.

# ## Network design philosophy:
# In pandaprosumer, a system's component is represented by a network element. Each element is assigned a container and its own element controller. A container is a structure that contains the component's configuration data (static input data), which can include information that will not change in the analysis such as size, nominal power, efficiency, etc. The behaviour of an element is governed by its controller. Connections between elements are defined in maps, which couple output parameters of one controller to the input parameter of a controller of a connected element. The network is managed by a controller called ConstProfileController. This controller is connected to all element controllers and manages dynamic input data from external sources (e.g. Excel file). For each time step it distributes the dynamic input data to the relevant element controllers.

# # 1 - INPUT DATA:
# First let's import libraries required for data management.

# In[1]:


import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData


# Next we need to define properties of the heat pump which are treated as static input data, i.e. data (characteristics) that don't change during an analysis. In this case the properties for the heat pump are :
# 
# - `carnot_efficiency`: The efficiency of the heat pump relative to the Carnot cycle (dimensionless, between 0 and 1).
# - `pinch_c`: The pinch point temperature difference (°C), which represents the minimum temperature difference in the heat exchanger.
# - `delta_t_evap_c`: The temperature difference at the evaporator (°C).
# - `max_p_comp_kw`: The maximum compressor power (kW), which limits the heat pump's capacity.
# - `name`: A label identifying the heat pump.
# 
# 
# Next, we define the properties of the **stratified heat storage (SHS)**, which is used to store thermal energy. The SHS parameters include physical dimensions, insulation properties, and temperature constraints.
# 
# - `tank_height_m`: The height of the storage tank (meters).
# - `tank_internal_radius_m`: The internal radius of the tank (meters).
# - `tank_external_radius_m`: The external radius of the tank (meters).
# - `insulation_thickness_m`: The thickness of the tank's insulation (meters).
# - `n_layers`: The number of discrete layers used for thermal stratification.
# - `min_useful_temp_c`: The minimum temperature (°C) at which stored heat is considered useful.
# - `t_ext_c`: The external ambient temperature (°C).
# - `name`: A label for the heat storage system.
# 
#  While these arguments are generally optional, in our specific case they are required in order to fully configure the heat exchanger. Other optional arguments are also available for more advanced configurations.
# 
# 

# In[2]:


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







# We define the analysis time series.

# In[3]:


start = '2020-01-01 00:00:00'
end = '2020-01-01 01:59:59'
time_resolution_s = 3600


# Now we import our demand data and transform it into an appropriate DFData object. All data of an individual element is stored in a dedicated DFData object.

# In[4]:


import sys
import os

current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
sys.path.append(parent_directory)


# In[5]:


os.getcwd()
os.path.dirname(current_directory)


# In[6]:


start = '2020-01-01 00:00:00'
end = '2020-01-01 01:59:59'
resol =3600


# In[7]:


demand_data = pd.read_excel('data/senergy_nets_example_chiller.xlsx')
# Generate UTC-aware datetime index
dur = pd.date_range(start, end, freq=f'{resol}s', tz='UTC')

# Set the index
demand_data.index = dur

demand_input = DFData(demand_data)
print(demand_data.head())





from pandaprosumer.create import create_empty_prosumer_container

prosumer = create_empty_prosumer_container()



from pandaprosumer.create import create_period

period_id = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')





from pandaprosumer.create_controlled import create_controlled_const_profile

input_columns = ["Set Point Temperature T_set [K]", "Evaporator inlet temperature T_in_ev [K]", "Condenser inlet temperature T_in_cond [K]",
                       "Condenser temperature increase Dt_cond [K]", "Cooling demand Q_load [kJ/h]", "Isentropic efficiency N_is [-]",
                       "Maximum chiller power Q_max [kJ/h]", "Control signal Ctrl [-]"]
result_columns=["t_set_pt_const_profile_in_c", "t_evap_in_const_profile_in_c", "t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c",
                        "q_chiller_demand_const_profile_kw", "n_is_const_profile", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"]

cp_controller_index = create_controlled_const_profile(prosumer, input_columns, result_columns, period_id, demand_input, level=0, order=0)



from pandaprosumer.create_controlled import create_controlled_chiller, create_controlled_heat_demand

chiller_controller_index = create_controlled_chiller(prosumer, period=period_id, level=0, order = 1, **chiller_params) 
hd_controller_index = create_controlled_heat_demand(prosumer, period=period_id, level=0, order = 2,scaling=1.0)




from pandaprosumer.mapping import GenericMapping




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




from pandaprosumer.run_time_series import run_timeseries

run_timeseries(prosumer, period_id, verbose=True)
print(prosumer.time_series)


