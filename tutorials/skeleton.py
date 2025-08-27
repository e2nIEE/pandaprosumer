import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import create_controlled_const_profile, create_controlled_heat_demand, \
    create_controlled_booster_heat_pump, create_controlled_ice_chp, create_controlled_chiller
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
import numpy as np

combinations = {1:[0,100,50],2:[50,50,0], 3:[100,0,50]} #bhp, chp, chiller

flex =  np.linspace(-200, 200, 96)

bhp_prosumer = create_empty_prosumer_container()


"""BHP"""
bhp_type = 'water-water1'
bhp_name = 'example_bhp'

start = '2020-01-01 00:00:00'
end = '2020-01-01 23:59:59'
time_resolution = 900        # 15 min
frequency = '15min'

time_series_data = pd.read_excel('data/heat_demand_input_chp_bhp.xlsx')

dur = pd.date_range(start=start, end=end, freq=frequency, tz='utc')
time_series_data.index = dur
time_series_input_bhp = DFData(time_series_data)


period = create_period(bhp_prosumer, time_resolution, start, end, 'utc', 'default')
input_params = ['mode', 't_source_k', 'q_demand_kw']
result_params = ['mode_cp', 't_source_cp_k', 'q_demand_cp_kw']

cp_index = create_controlled_const_profile(
    bhp_prosumer, input_params, result_params, time_series_input_bhp, period)
bhp_index = create_controlled_booster_heat_pump(bhp_prosumer, bhp_type, bhp_name, level = 1 )
heat_demand_index = create_controlled_heat_demand(bhp_prosumer, scaling=1.0, level = 1, order =1)



GenericMapping(bhp_prosumer,
                   initiator_id=cp_index,
                   initiator_column="t_source_cp_k",
                   responder_id=bhp_index,
                   responder_column="t_source_k",
)
GenericMapping(bhp_prosumer,
                   initiator_id=cp_index,
                   initiator_column="mode_cp",
                   responder_id=bhp_index,
                   responder_column="mode",
)

#BHP -> Heat Demand
GenericMapping(bhp_prosumer,
                   initiator_id=bhp_index,
                   initiator_column="q_floor",
                   responder_id=heat_demand_index,
                   responder_column="q_received_kw",
)

#General Controller -> Heat Demand
GenericMapping(bhp_prosumer,
                   initiator_id=cp_index,
                   initiator_column="q_demand_cp_kw",
                   responder_id=heat_demand_index,
                   responder_column="q_demand_kw",
)


"""CHP"""
name = 'example_chp'
size_kw = 500
fuel = 'ng'
altitude_m = 0

time_series_data = pd.read_excel('data/heat_demand_input_chp_bhp.xlsx')

duration = pd.date_range(start, end, freq=frequency, tz='utc')
time_series_data.index = duration
time_series_input_chp = DFData(time_series_data)


ice_chp_prosumer = create_empty_prosumer_container()
period = create_period(ice_chp_prosumer, time_resolution, start, end, 'utc', 'default')

input_params = ['q_demand_kw', 'cycle', 't_intake_k']
output_params = ['q_demand_cp_kw', 'cycle_cp', 't_intake_cp_k']

cp_index = create_controlled_const_profile(
    ice_chp_prosumer, input_params, output_params, time_series_input_chp, period)

ice_chp_index = create_controlled_ice_chp(ice_chp_prosumer, size_kw, fuel, altitude_m, name, level=1)
heat_demand_index = create_controlled_heat_demand(ice_chp_prosumer, scaling=1.0,level=1,order=1)


#GENERAL CONTROLLER ---> ICE CHP
GenericMapping(
    ice_chp_prosumer,
    initiator_id=cp_index,
    initiator_column="cycle_cp",
    responder_id=ice_chp_index,
    responder_column="cycle"
)
GenericMapping(
    ice_chp_prosumer,
    initiator_id=cp_index,
    initiator_column="t_intake_cp_k",
    responder_id=ice_chp_index,
    responder_column="t_intake_k"
)

# ICE CHP ---> HEAT DEMAND (consumer)
GenericMapping(
    ice_chp_prosumer,
    initiator_id=ice_chp_index,
    initiator_column="p_th_out_kw",
    responder_id=heat_demand_index,
    responder_column="q_received_kw"
)
#GENERAL CONTROLLER ---> HEAT DEMAND (consumer)
GenericMapping(
    ice_chp_prosumer,
    initiator_id=cp_index,
    initiator_column="q_demand_cp_kw",
    responder_id=heat_demand_index,
    responder_column="q_demand_kw"
)


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

demand_data = pd.read_excel('data/input_demand_chiller.xlsx')
# Generate UTC-aware datetime index
dur = pd.date_range(start, end, freq=f'{time_resolution}s', tz='UTC')
demand_data.index = dur
time_series_input_chiller = DFData(demand_data)

prosumer = create_empty_prosumer_container()
period = create_period(prosumer, time_resolution, start, end, 'utc', 'default')
input_columns = ["Set Point Temperature T_set [K]", "Evaporator inlet temperature T_in_ev [K]", "Condenser inlet temperature T_in_cond [K]",
                       "Condenser temperature increase Dt_cond [K]", "Cooling demand Q_load [kJ/h]", "Isentropic efficiency N_is [-]",
                       "Maximum chiller power Q_max [kJ/h]", "Control signal Ctrl [-]"]
result_columns=["t_set_pt_const_profile_in_c", "t_evap_in_const_profile_in_c", "t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c",
                        "q_chiller_demand_const_profile_kw", "n_is_const_profile", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"]

cp_controller_index = create_controlled_const_profile(prosumer, input_columns, result_columns, time_series_input_chiller, period, level=0, order=0)
chiller_controller_index = create_controlled_chiller(prosumer, period=period, level=0, order = 1, **chiller_params)
hd_controller_index = create_controlled_heat_demand(prosumer, period=period, level=0, order = 2,scaling=1.0)
#CONST PROFILE CONTROLLER ---> CHILLER:
GenericMapping(prosumer,
               initiator_id=cp_controller_index,
               initiator_column=["t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c", "t_evap_in_const_profile_in_c", "n_is_const_profile",
                                 "t_set_pt_const_profile_in_c", "q_max_deliverable_const_profile_kw", "ctrl_signal_const_profile"],
               responder_id=chiller_controller_index,
               responder_column= ["t_in_cond_c", "dt_cond_c", "t_in_ev_c", "n_is", "t_set_pt_c", "q_max_kw", "ctrl"],
               order=0)
#CONST PROFILE CONTROLLER ---> HEAT DEMAND
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


og_time_series_input_chiller = time_series_input_chiller.df['Cooling demand Q_load [kJ/h]']
og_time_series_input_bhp = time_series_input_bhp.df.q_demand_kw
og_time_series_input_chp = time_series_input_chp.df.q_demand_kw

p_balance = []
for i in combinations:
    #Just cutting the demand by percentages
    bhp_scaling = combinations[i][0]
    chp_scaling = combinations[i][1]
    chill_scaling = combinations[i][2]

    time_series_input_bhp.df.q_demand_kw = bhp_scaling * og_time_series_input_bhp
    time_series_input_chp.df.q_demand_kw = chp_scaling * og_time_series_input_chp
    time_series_input_chiller.df['Cooling demand Q_load [kJ/h]'] = chp_scaling * og_time_series_input_chiller


    run_timeseries(ice_chp_prosumer, period, True)
    res_chp = ice_chp_prosumer.time_series.data_source.iloc[0].df
    chp_p_el_out_kw = res_chp['p_el_out_kw']
    chp_p_th_out_kw = res_chp['p_th_out_kw']

    run_timeseries(bhp_prosumer, period, True)
    res_bhp = bhp_prosumer.time_series.data_source.iloc[0].df
    bhp_p_el_in_kw = res_bhp['p_el_floor'] #or radiator?

    run_timeseries(prosumer, period, verbose=True)
    res_chiller = prosumer.time_series.data_source.iloc[0].df
    chiller_p_el_in_kw = res_chiller['w_in_tot_kw'] #correct?


    p_el_balance = chp_p_el_out_kw - bhp_p_el_in_kw -chiller_p_el_in_kw - flex
    p_balance.append(p_el_balance)