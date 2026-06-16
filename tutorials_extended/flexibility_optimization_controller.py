import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_heat_demand, \
    create_controlled_booster_heat_pump, create_controlled_ice_chp, create_controlled_heat_storage, create_controlled_optimtization)
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

prosumer = create_empty_prosumer_container(check_order=False)

start = '2020-01-01 00:00:00'
end = '2020-01-08 23:59:59'
time_resolution = 3600      # 60 min
frequency = '60min'

t_day = np.arange(0, 24, 1)  # 24 Werte (1h Schritte)

L_day = (100 * np.exp(-((t_day - 8) ** 2) / (2 * 1.5 ** 2))
       + 100 * np.exp(-((t_day - 18) ** 2) / (2 * 1.5 ** 2)))

G_PV_day = 100 * np.maximum(0, np.sin(np.pi / 12 * (t_day - 6)))

flex_day = L_day - G_PV_day

n_days = 8

L = np.tile(L_day, n_days)
G_PV = np.tile(G_PV_day, n_days)
flex = np.tile(flex_day, n_days)



project_root = Path.cwd().parent if Path.cwd().name in ["tutorials", "tutorials_extended"] else Path.cwd()
data_file = project_root / "tutorials_extended" / "data" / "aleja_heat_demand_model_data.xlsx"
time_series_data = pd.read_excel(data_file)

time_series_data["flex_demand_kw"] = flex
time_series_data["t_sink_k"] = 350
time_series_data["cycle"] = 1

dur = pd.date_range(start=start, end=end, freq=frequency, tz='utc')
time_series_data.index = dur
time_series_input_bhp = DFData(time_series_data)
period = create_period(prosumer, time_resolution, start, end, 'utc', 'default')

time_series_data.head()

input_params = ['mode', 't_source_k', 'q_demand_kw', 'cycle', 't_intake_k',
                    "flex_demand_kw", "p_el_bhp", "p_el_chp", "t_amb_k", "t_sink_k"]
result_params = ['mode_cp', 't_source_cp_k', 'q_demand_cp_kw', 'cycle_cp', 't_intake_cp_k',
                     "flex_demand_cp_kw", "p_el_bhp_cp", "p_el_chp_cp", "t_amb_k_cp", "t_sink_k_cp"]

cp_index = create_controlled_const_profile(
        prosumer, input_params, result_params, time_series_input_bhp, period, level=0)

bhp_type = 'water-water2'
bhp_name = 'example_bhp'
max_thermal_power_kw = 1000

bhp_index = create_controlled_booster_heat_pump(prosumer,
                                                hp_type=bhp_type,
                                                name=bhp_name,
                                                q_max_kw=max_thermal_power_kw,
                                                level=2,
                                                order=0)

bhp_index_cop_calc = create_controlled_booster_heat_pump(prosumer,
                                                hp_type=bhp_type,
                                                name=bhp_name,
                                                q_max_kw=max_thermal_power_kw,
                                                level=1,
                                                order=0)

name = 'example_chp'
size_kw = 700
fuel = 'ng'
altitude_m = 0

ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=2, order=1)

q_capacity_kwh = 200000

heat_storage_index = create_controlled_heat_storage(prosumer, q_capacity_kwh, level=2, order=2)

heat_demand_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=2, order=3)

optimization_index = create_controlled_optimtization(prosumer, level=1, order=1)

GenericMapping(prosumer,
        initiator_id=cp_index,
        initiator_column=["t_source_cp_k", "mode_cp","p_el_bhp_cp", "t_amb_k_cp", "t_sink_k_cp"],
        responder_id=bhp_index,
        responder_column=["t_source_k", "mode", "p_received_kw", "t_amb_k", "t_sink_k"],
    )

GenericMapping(
        prosumer,
        initiator_id=cp_index,
        initiator_column=["cycle_cp", "t_intake_cp_k", "p_el_chp_cp"],
        responder_id=ice_chp_index,
        responder_column=["cycle", "t_intake_k", "p_requested_kw"],
    )



GenericMapping(prosumer,
        initiator_id=cp_index,
        initiator_column="q_demand_cp_kw",
        responder_id=heat_demand_index,
        responder_column="q_demand_kw",
    )

GenericMapping(prosumer,
                initiator_id=bhp_index,
                initiator_column="q_floor",
                responder_id=heat_storage_index,
                responder_column="q_received_kw",
)

GenericMapping(
    prosumer,
    initiator_id=ice_chp_index,
    initiator_column="p_th_out_kw",
    responder_id=heat_storage_index,
    responder_column="q_received_kw",
)


GenericMapping(
    prosumer,
    initiator_id=heat_storage_index,
    initiator_column="q_delivered_kw",
    responder_id=heat_demand_index,
    responder_column="q_received_kw",
)

GenericMapping(prosumer,
        initiator_id=cp_index,
        initiator_column=["t_source_cp_k", "mode_cp","p_el_bhp_cp", "t_amb_k_cp", "t_sink_k_cp"],
        responder_id=bhp_index_cop_calc,
        responder_column=["t_source_k", "mode", "p_received_kw", "t_amb_k", "t_sink_k"],
    )

GenericMapping(prosumer,
        initiator_id=cp_index,
        initiator_column=["q_demand_cp_kw", "flex_demand_cp_kw"],
        responder_id=optimization_index,
        responder_column=["q_demand_kw", "p_flex_kw"],
    )

GenericMapping(prosumer,
        initiator_id=bhp_index_cop_calc,
        initiator_column=["cop_floor"],
        responder_id=optimization_index,
        responder_column=["cop_bhp"],
    )

GenericMapping(prosumer,
        initiator_id=optimization_index,
        initiator_column=["p_el_bhp_in"],
        responder_id=bhp_index,
        responder_column=["p_received_kw"],
    )

GenericMapping(prosumer,
        initiator_id=optimization_index,
        initiator_column=["p_el_chp_out"],
        responder_id=ice_chp_index,
        responder_column=["p_requested_kw"],
    )

run_timeseries(prosumer, period, verbose=True)

res_bhp, res_chp, res_storage, res_heat_demand = [
    prosumer.time_series.data_source.iloc[i].df for i in range(2, 6)
]

res_df = pd.DataFrame({
    "chp_p_el": res_chp["p_el_out_kw"],
    "bhp_p_el": -res_bhp["p_el_floor"],
    "chp_q_th": res_chp["p_th_out_kw"],
    "bhp_q_th": res_bhp["q_floor"],
    "flex": flex,
    "p_el_balance": res_chp["p_el_out_kw"] - res_bhp["p_el_floor"] - flex,
    "p_el_sum": res_chp["p_el_out_kw"] - res_bhp["p_el_floor"],
    "q_th_sum": res_chp["p_th_out_kw"] + res_bhp["q_floor"],
    "q_delivered_storage": res_storage["q_delivered_kw"],
    "soc": res_storage["soc"] * 100,
    "q_received_demand": res_heat_demand["q_received_kw"],
}, index=res_chp.index)

fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

ax[0].plot(res_df.index, res_df["chp_p_el"], label="CHP electric generation")
ax[0].plot(res_df.index, res_df["bhp_p_el"], label="BHP electric consumption")
ax[0].plot(res_df.index, res_df["p_el_sum"], label="Electric balance CHP & BHP", linewidth=3, color="grey")
ax[0].plot(res_df.index, res_df["flex"], label="Flexibility demand", color="red", linewidth=1, linestyle="--")
ax[0].set_ylabel("Electrical power (kW)", fontsize=12)
ax[0].legend(fontsize=10, loc="lower left")

ax[1].plot(res_df.index, res_df["chp_q_th"], label="CHP thermal generation")
ax[1].plot(res_df.index, res_df["bhp_q_th"], label="BHP thermal generation")
ax[1].plot(res_df.index, res_df["q_delivered_storage"], label="Thermal output storage", linewidth=3, color="grey")
ax[1].plot(res_df.index, res_df["q_received_demand"], label="Heat demand", color="red", linewidth=1, linestyle="--")
ax[1].set_ylabel("Thermal power (kW)", fontsize=12)
ax[1].legend(fontsize=10)

ax2 = ax[1].twinx()
ax2.plot(res_df.index, res_df["soc"], linestyle=':', label="SOC", color="green", linewidth=1.5)
ax2.set_ylabel("State of Charge (%)", fontsize=12, color="green")


lines1, labels1 = ax[1].get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax[1].legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=10)

hour_fmt = mdates.DateFormatter("%H")   # %H = Stunde (00–23)
ax[1].xaxis.set_major_formatter(hour_fmt)
ax[1].set_xlabel("Time (h)", fontsize=12)

plt.xticks(fontsize=11)   # x-Achse Tick-Beschriftungen größer
plt.yticks(fontsize=11)   # y-Achse Tick-Beschriftungen größer

# Plot fertig zeichnen
plt.draw()

plt.show()
