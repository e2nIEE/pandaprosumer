import pandas as pd
from numba.cuda import profile_start
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_heat_demand, \
    create_controlled_booster_heat_pump, create_controlled_ice_chp, create_controlled_chiller,
                                             create_controlled_heat_storage, create_controlled_supervisor)
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
import numpy as np

flex =  np.linspace(-200, 200, 96)


# # CSV-Datei einlesen
# dummy_data = pd.read_csv("C:\\Users\\carl\\Downloads\\strompreis.csv",
#                           parse_dates=["Datetime"],
#                           index_col="Datetime" )
#
# dummy_data.drop(columns="Stromhandelsbilanz", inplace=True)
#
# dummy_data.rename(columns={"Strompreis": "Strompreis EUR/MWh"}, inplace=True)
#
# dummy_data["Strompreis EUR/MWh"] += 100 # €/MWh :Kosten für Stronmsteuer, Netzentgelte etc. Auf den Börsenpreis addiert.
#
# dummy_data["Gaspreis EUR/MWh"] = 70
#
# n_sections = 12
# n = len(dummy_data)
#
# # Zufallswerte für jede Sektion
# random_values = np.random.randint(-500, 501, size=n_sections)
#
# # Spalte erstellen: np.repeat, dann ggf. Rest auffüllen
# section_size = n // n_sections
# repeated_values = np.repeat(random_values, section_size)
#
# # Restzeilen auffüllen, falls nötig
# rest = n - len(repeated_values)
# if rest > 0:
#     repeated_values = np.concatenate([repeated_values, np.full(rest, random_values[-1])])
#
# dummy_data["Flexibility Demand kW"] = repeated_values
#
# print(dummy_data)

prosumer = create_empty_prosumer_container()


"""BHP"""
bhp_type = 'water-water1'
bhp_name = 'example_bhp'

"""CHP"""
name = 'example_chp'
size_kw = 700
fuel = 'ng'
altitude_m = 0

"""Storage"""
q_capacity_kwh = 10000

start = '2020-01-01 00:00:00'
end = '2020-01-01 23:59:59'
time_resolution = 900        # 15 min
frequency = '15min'

scaling = [0, 0.2, 0.4, 0.6, 0.8, 1]

time_series_data = pd.read_excel('data/heat_demand_input_chp_bhp.xlsx')
time_series_data["c_electricity_eur_per_mw"] = np.random.randint(100, 251, size=len(time_series_data))
time_series_data["c_gas_eur_per_mw"] = 70
time_series_data["flex_demand_kw"] = flex
time_series_data["p_el_bhp"] = 0
time_series_data["p_el_chp"] = 0
time_series_data["mode"] = 2
time_series_data["cycle"] = 1



# supervisor_index = create_controlled_supervisor(prosumer, input_columns=["c_electricity_eur_per_mw", "c_gas_eur_per_mw"],
#                                                 period=period, level=1, order=0)
# supervisor_object = prosumer.controller.iloc[supervisor_index].object





p_balance = pd.DataFrame()

dur = pd.date_range(start=start, end=end, freq=frequency, tz='utc')
time_series_data.index = dur
time_series_input_bhp = DFData(time_series_data)
period = create_period(prosumer, time_resolution, start, end, 'utc', 'default')

print(time_series_data.head())
input_params = ['mode', 't_source_k', 'q_demand_kw', 'cycle', 't_intake_k',
                    "c_electricity_eur_per_mw", "c_gas_eur_per_mw", "flex_demand_kw", "p_el_bhp", "p_el_chp"]
result_params = ['mode_cp', 't_source_cp_k', 'q_demand_cp_kw', 'cycle_cp', 't_intake_cp_k',
                     "c_electricity_cp_eur_per_mw", "c_gas_cp_eur_per_mw", "flex_demand_cp_kw", "p_el_bhp_cp", "p_el_chp_cp"]

cp_index = create_controlled_const_profile(
        prosumer, input_params, result_params, time_series_input_bhp, period, level=0)

bhp_index = create_controlled_booster_heat_pump(prosumer, bhp_type, bhp_name, level=2, order=0)

ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=2, order=1)

heat_storage_index = create_controlled_heat_storage(prosumer, q_capacity_kwh,level = 2,order=2)

heat_demand_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=2, order=3)


GenericMapping(prosumer,
        initiator_id=cp_index,
        initiator_column=["t_source_cp_k", "mode_cp","p_el_bhp_cp"],
        responder_id=bhp_index,
        responder_column=["t_source_k", "mode", "p_received_kw"],
    )
#GENERAL CONTROLLER ---> ICE CHP
GenericMapping(
        prosumer,
        initiator_id=cp_index,
        initiator_column=["cycle_cp", "t_intake_cp_k", "p_el_chp_cp"],
        responder_id=ice_chp_index,
        responder_column=["cycle", "t_intake_k", "p_requested_kw"],
    )

#General Controller -> Heat Demand
GenericMapping(prosumer,
        initiator_id=cp_index,
        initiator_column="q_demand_cp_kw",
        responder_id=heat_demand_index,
        responder_column="q_demand_kw",
    )

    # GenericMapping(
    #     prosumer,
    #     initiator_id=cp_index,
    #     initiator_column=["c_electricity_cp_eur_per_mw", "c_gas_cp_eur_per_mw"],
    #     responder_id=supervisor_index,
    #     responder_column=["c_electricity_eur_per_mw", "c_gas_eur_per_mw"],
    # )


#BHP -> Heat Demand
GenericMapping(prosumer,
                initiator_id=bhp_index,
                initiator_column="q_floor",
                responder_id=heat_storage_index,
                responder_column="q_received_kw",
                order=0,
)

# ICE CHP ---> HEAT DEMAND (consumer)
GenericMapping(
    prosumer,
    initiator_id=ice_chp_index,
    initiator_column="p_th_out_kw",
    responder_id=heat_storage_index,
    responder_column="q_received_kw",
    order=1,
)

#BHP -> Heat Demand
# GenericMapping(prosumer,
#                     initiator_id=bhp_index,
#                     initiator_column="q_floor",
#                     responder_id=heat_demand_index,
#                     responder_column="q_received_kw",
#                     order=1,
#     )
#
# # ICE CHP ---> HEAT DEMAND (consumer)
# GenericMapping(
#         prosumer,
#         initiator_id=ice_chp_index,
#         initiator_column="p_th_out_kw",
#         responder_id=heat_demand_index,
#         responder_column="q_received_kw",
#         order=0,
#     )

GenericMapping(
    prosumer,
    initiator_id=heat_storage_index,
    initiator_column="q_delivered_kw",
    responder_id=heat_demand_index,
    responder_column="q_received_kw",
)




run_timeseries(prosumer, period, True)


res_chp = prosumer.time_series.data_source.iloc[1].df
chp_p_el_out_kw = res_chp['p_el_out_kw']
chp_p_th_out_kw = res_chp['p_th_out_kw']


res_bhp = prosumer.time_series.data_source.iloc[0].df
bhp_p_el_in_kw = res_bhp['p_el_floor'] #or radiator?


p_el_balance = chp_p_el_out_kw - bhp_p_el_in_kw + flex

df = pd.DataFrame({
    "chp_p_el": chp_p_el_out_kw.values,
    "bhp_p_el": bhp_p_el_in_kw.values,
    "flex": flex,
    "p_el_balance": p_el_balance.values
}, index=res_chp.index)  # falls du den Zeitindex behalten willst
print(df)