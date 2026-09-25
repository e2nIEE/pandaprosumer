import pandaprosumer as ppr
from pandapower.control.controller.const_control import ConstControl
from pandapower import get_element_index
import matplotlib.pyplot as plt
from create_nets import create_thermal_networks
from create_prosumer import *
from create_energy_system import _create_energy_system
import pandapipes as ppi
import pandas as pd
import numpy as np
import sys
import os
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.energy_system.timeseries.run_time_series_energy_system import \
run_timeseries as run_time_series_system
from pandapower.control.basic_controller import Controller
pd.set_option("display.max_columns", None)
pd.set_option("display.width", None)
pd.set_option("display.max_colwidth", None)

start = '2024-06-01 00:00:00'
time_resolution_s = 3600

current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
sys.path.append(parent_directory)

demand_data = pd.read_excel('data/cordoba_hospital_data.xlsx')

# First week
n_steps_week = int(7 * 24 * 3600 / time_resolution_s)  # 168 bei 1h-Auflösung
demand_data = demand_data.iloc[:n_steps_week]
# demand_data = demand_data.iloc[:72]

end = (
    pd.Timestamp(start)
    + len(demand_data) * pd.Timedelta(seconds=time_resolution_s)
    - pd.Timedelta(seconds=1)
)

dur = pd.date_range(
    start=start,
    end=end,
    freq=f'{time_resolution_s}s',
    tz='utc'
)

demand_data.index = dur
demand_data["t_flow_cold_c"] = 10
demand_data["t_return_cold_c"] = 15
demand_data["t_flow_hot_c"] = 78
demand_data["t_return_hot_c"] = 70
# Assumed domestic-hot-water temperatures
demand_data["t_dhw_cold_c"] = 15.0
demand_data["t_dhw_hot_c"] = 60.0

# Real ambient temperature from Excel
demand_data["t_ambient_c"] = (demand_data["T_amb(°C)"].astype(float))
# Increase condenser temperatures only when ambient exceeds 25°C
temperature_increase_c = np.maximum(demand_data["t_ambient_c"] - 25.0, 0.0)
# Water from chiller condenser to Dry Cooler
demand_data["dry_cooler_t_in_c"] = (35.0 + temperature_increase_c)
# Water from Dry Cooler back to chiller condenser
demand_data["dry_cooler_t_out_c"] = (30.0 + temperature_increase_c)
# Required by the controller; adiabatic mode remains disabled
demand_data["phi_air_in_percent"] = 50.0


# ---------------------------------------------------------
# Step 1: Calculate the available PV surplus
# ---------------------------------------------------------

# Temporary synthetic electrical base load of the hospital
hospital_base_load_kw = 500.0

# Make sure that the PV column is numeric
demand_data["pv_gen_kw"] = pd.to_numeric(
    demand_data["pv_gen (kW)"],
    errors="coerce"
).fillna(0.0)

# Temporary hospital electricity consumption
demand_data["hospital_electric_load_kw"] = hospital_base_load_kw




demand_input = DFData(demand_data)

net_cold, net_hot = create_thermal_networks()

prosumer_hd = create_prosumer_heat_demand(demand_input, time_resolution_s, start, end, net_hot=net_hot)
# prosumer_cd = create_prosumer_cooling_demand(demand_input, time_resolution_s, start, end, net_cold=net_cold)
(
    prosumer_dhw,
    dhw_storage_controller_index,
    dhw_demand_controller_index,
    dhw_network_demand_controller_index
) = create_prosumer_dhw_system(
    demand_input,
    time_resolution_s,
    start,
    end,
    net_hot=net_hot
)
prosumer_prod, hp_controller_index = create_prosumer_prod(demand_input, time_resolution_s, start, end, net_hot=net_hot, net_cold=net_cold) #, chiller_controller_index, dry_cooler_controller_index

# prosumer = [ prosumer_cd, prosumer_hd, prosumer_prod, prosumer_dhw]
prosumer = [prosumer_hd, prosumer_prod, prosumer_dhw]

energy_system = _create_energy_system([net_hot, net_cold],prosumer , name="test_energy_system")

from pandapower.timeseries import OutputWriter

sample_prosumer_period = prosumer_prod.period
ow_time_steps = pd.date_range(sample_prosumer_period.iloc[0]["start"], sample_prosumer_period.iloc[0]["end"],
                              freq='%ss' % int(sample_prosumer_period.iloc[0]["resolution_s"]),
                              tz=sample_prosumer_period.iloc[0]["timezone"])
ow_net_hot = OutputWriter(net_hot, ow_time_steps, log_variables=[
    ('res_circ_pump_pressure', 't_from_k'),
    ('res_circ_pump_pressure', 't_to_k'),
    ('res_circ_pump_pressure', 'mdot_from_kg_per_s'),
    ('res_heat_consumer', 't_from_k'),
    ('res_heat_consumer', 't_to_k'),
    ('res_heat_consumer', 'mdot_from_kg_per_s'),
    ('heat_consumer', 'qext_w'),
    ('res_pipe', 'v_mean_m_per_s'),
    ('res_pipe', 't_from_k'),
    ('res_pipe', 't_to_k')
])
ow_net_cold = OutputWriter(
    net_cold,
    ow_time_steps,
    log_variables=[
        ("res_circ_pump_pressure", "t_from_k"),
        ("res_circ_pump_pressure", "t_to_k"),
        ("res_circ_pump_pressure", "mdot_from_kg_per_s"),
        ("heat_exchanger", "qext_w"),
        ("flow_control", "controlled_mdot_kg_per_s")
    ]
)


period_index = 0
run_time_series_system(energy_system,
                       period_index=period_index, continue_on_divergence=False, verbose=True,
                       transient=True, dt=time_resolution_s, initial_run=True, mode="bidirectional")
#
# def get_component_results(prosumer, component_name):
#     component_row = prosumer.time_series.loc[
#         prosumer.time_series["name"] == component_name
#     ].iloc[0]
#
#     return component_row["data_source"].df
#
#
# # RESULTS OF THE NORMAL RUN
# hp_results = get_component_results(prosumer_prod, "hp_controller")
# chiller_results = get_component_results(prosumer_prod, "reversed_hp_controller")
# dry_cooler_results = get_component_results(prosumer_prod, "dry_cooler_controller")
# baseline_boiler_results = get_component_results(prosumer_prod, "gb_controller")
#
#
# # ELECTRICAL CONSUMPTION IN THE NORMAL RUN
# demand_data["hp_baseline_power_kw"] = (
#     hp_results["p_comp_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# demand_data["chiller_baseline_power_kw"] = (
#     chiller_results["p_comp_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# demand_data["dry_cooler_baseline_power_kw"] = (
#     dry_cooler_results["p_fans_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# demand_data["equipment_baseline_power_kw"] = (
#     demand_data["hp_baseline_power_kw"]
#     + demand_data["chiller_baseline_power_kw"]
#     + demand_data["dry_cooler_baseline_power_kw"]
# )
#
# demand_data["total_baseline_load_kw"] = (
#     demand_data["hospital_electric_load_kw"]
#     + demand_data["equipment_baseline_power_kw"]
# )
#
# # AVAILABLE PV SURPLUS
# demand_data["pv_surplus_kw"] = np.maximum(
#     demand_data["pv_gen_kw"]
#     - demand_data["total_baseline_load_kw"],
#     0.0
# )
#
# # PREPARE THE CONTROL PROFILES
# demand_data = prepare_winter_pv_control_profiles(
#     demand_data,
#     normal_temperature_c=78.0,
#     surplus_temperature_c=80.0,
#     normal_hp_limit_kw=100.0,
#     maximum_hp_limit_kw=350.0
# )
#
# # CREATE THE CONTROLLED SYSTEM
# controlled_demand_input = DFData(demand_data.copy())
#
# controlled_net_cold, controlled_net_hot = (create_thermal_networks())
#
# controlled_prosumer_hd = create_prosumer_heat_demand(
#     controlled_demand_input,
#     time_resolution_s,
#     start,
#     end,
#     level=4,
#     net_hot=controlled_net_hot
# )
#
# controlled_prosumer_cd = create_prosumer_cooling_demand(
#     controlled_demand_input,
#     time_resolution_s,
#     start,
#     end,
#     net_cold=controlled_net_cold
# )
#
# (
#     controlled_prosumer_dhw,
#     controlled_dhw_storage_index,
#     controlled_dhw_demand_index,
#     controlled_dhw_network_demand_index
# ) = create_prosumer_dhw_system(
#     controlled_demand_input,
#     time_resolution_s,
#     start,
#     end,
#     net_hot=controlled_net_hot
# )
#
# (
#     controlled_prosumer_prod,
#     controlled_hp_controller_index,
#     controlled_chiller_controller_index,
#     controlled_dry_cooler_controller_index
# ) = create_prosumer_prod(
#     controlled_demand_input,
#     time_resolution_s,
#     start,
#     end,
#     level=3,
#     net_hot=controlled_net_hot,
#     net_cold=controlled_net_cold
# )
#
#
# # Apply the hourly HP limit and hot-network temperature
# add_winter_pv_controllers(
#     prosumer_prod=controlled_prosumer_prod,
#     net_hot=controlled_net_hot,
#     data_source=controlled_demand_input,
#     hp_controller_index=controlled_hp_controller_index
# )
#
#
# # RUN THE CONTROLLED SYSTEM
# controlled_energy_system = _create_energy_system(
#     [
#         controlled_net_hot,
#         controlled_net_cold
#     ],
#     [
#         controlled_prosumer_cd,
#         controlled_prosumer_hd,
#         controlled_prosumer_prod,
#         controlled_prosumer_dhw
#     ],
#     name="controlled_winter_energy_system"
# )
#
# print("\nRunning controlled winter scenario...")
# run_time_series_system(
#     controlled_energy_system,
#     period_index=0,
#     continue_on_divergence=False,
#     verbose=True,
#     transient=True,
#     dt=time_resolution_s,
#     mode="bidirectional"
# )
#
#
# # READ THE CONTROLLED RESULTS
# controlled_hp_results = get_component_results(controlled_prosumer_prod, "hp_controller")
# controlled_chiller_results = get_component_results(controlled_prosumer_prod, "reversed_hp_controller")
# controlled_dry_cooler_results = get_component_results(controlled_prosumer_prod, "dry_cooler_controller")
# controlled_boiler_results = get_component_results(controlled_prosumer_prod, "gb_controller")
# controlled_dhw_results = get_component_results(controlled_prosumer_dhw, "dhw_demand_controller")
# controlled_dhw_network_results = get_component_results(controlled_prosumer_dhw, "dhw_network_demand_controller")
#
# # ELECTRICAL CONSUMPTION IN THE CONTROLLED RUN
# demand_data["hp_controlled_power_kw"] = (
#     controlled_hp_results["p_comp_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# demand_data["chiller_controlled_power_kw"] = (
#     controlled_chiller_results["p_comp_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# demand_data["dry_cooler_controlled_power_kw"] = (
#     controlled_dry_cooler_results["p_fans_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# demand_data["equipment_controlled_power_kw"] = (
#     demand_data["hp_controlled_power_kw"]
#     + demand_data["chiller_controlled_power_kw"]
#     + demand_data["dry_cooler_controlled_power_kw"]
# )
#
# demand_data["total_controlled_load_kw"] = (
#     demand_data["hospital_electric_load_kw"]
#     + demand_data["equipment_controlled_power_kw"]
# )
#
# demand_data["controlled_balance_kw"] = (
#     demand_data["pv_gen_kw"]
#     - demand_data["total_controlled_load_kw"]
# )
#
# demand_data["unused_pv_kw"] = np.maximum(
#     demand_data["controlled_balance_kw"], 0.0
# )
#
# demand_data["grid_import_kw"] = np.maximum(
#     -demand_data["controlled_balance_kw"], 0.0
# )
#
# # THERMAL RESULTS
# heating_demand_kw = demand_data["Heating demand (kW)"].fillna(0.0)
#
# controlled_dhw_request_kw = (
#     controlled_dhw_results["q_uncovered_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
#     .clip(lower=0.0)
# )
#
# controlled_dhw_received_kw = (
#     controlled_dhw_network_results["q_received_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
#     .clip(lower=0.0)
# )
#
# controlled_dhw_unmet_kw = (
#     controlled_dhw_network_results["q_uncovered_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
#     .clip(lower=0.0)
# )
#
# baseline_hp_heat_kw = (
#     hp_results["q_cond_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# controlled_hp_heat_kw = (
#     controlled_hp_results["q_cond_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# baseline_boiler_heat_kw = (
#     baseline_boiler_results["q_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# controlled_boiler_heat_kw = (
#     controlled_boiler_results["q_kw"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# # MASS FLOWS
# baseline_hp_mdot_kg_s = (
#     hp_results["mdot_cond_kg_per_s"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# controlled_hp_mdot_kg_s = (
#     controlled_hp_results["mdot_cond_kg_per_s"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# baseline_boiler_mdot_kg_s = (
#     baseline_boiler_results["mdot_kg_per_s"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# controlled_boiler_mdot_kg_s = (
#     controlled_boiler_results["mdot_kg_per_s"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# baseline_gas_mdot_kg_s = (
#     baseline_boiler_results["mdot_gas_kg_per_s"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
# controlled_gas_mdot_kg_s = (
#     controlled_boiler_results["mdot_gas_kg_per_s"]
#     .reindex(demand_data.index)
#     .fillna(0.0)
# )
#
#
# # TOTAL HEAT
# total_heat_demand_kw = heating_demand_kw + controlled_dhw_request_kw
# baseline_total_heat_production_kw = baseline_hp_heat_kw + baseline_boiler_heat_kw
# controlled_total_heat_production_kw = controlled_hp_heat_kw + controlled_boiler_heat_kw
#
# # OPERATING STATES
# surplus_mask = demand_data["pv_surplus_kw"] > 0.0
# previous_hour_surplus = demand_data["pv_surplus_kw"].shift(1).fillna(0.0)
#
# after_surplus_mask = (
#     (previous_hour_surplus > 0.0)
#     & (~surplus_mask)
# )
#
#
# # WEEKLY REPORT
# weekly_report = pd.DataFrame(index=demand_data.index)
#
# weekly_report["Betriebszustand"] = np.select(
#     [surplus_mask, after_surplus_mask],
#     ["PV-Überschuss", "Nach PV-Überschuss"],
#     default="Normalbetrieb"
# )
#
# weekly_report["Raumheizbedarf_kW"] = heating_demand_kw
# weekly_report["PV_Überschuss_vorher_kW"] = demand_data["pv_surplus_kw"]
# weekly_report["PV_Überschuss_nachher_kW"] = demand_data["unused_pv_kw"]
#
# weekly_report["WP_Rücklauf_normal_C"] = (
#     hp_results["t_cond_in_c"].reindex(demand_data.index)
# )
#
# weekly_report["WP_Vorlauf_normal_C"] = (
#     hp_results["t_cond_out_c"].reindex(demand_data.index)
# )
#
# weekly_report["WP_Rücklauf_geregelt_C"] = (
#     controlled_hp_results["t_cond_in_c"].reindex(demand_data.index)
# )
#
# weekly_report["WP_Vorlauf_geregelt_C"] = (
#     controlled_hp_results["t_cond_out_c"].reindex(demand_data.index)
# )
#
# weekly_report["WP_Strom_normal_kW"] = demand_data["hp_baseline_power_kw"]
# weekly_report["WP_Strom_geregelt_kW"] = demand_data["hp_controlled_power_kw"]
#
# weekly_report["Warmwasser_Netzbedarf_kW"] = controlled_dhw_request_kw
# weekly_report["Warmwasser_Netzlieferung_kW"] = controlled_dhw_received_kw
# weekly_report["Warmwasser_Restbedarf_kW"] = controlled_dhw_unmet_kw
#
# weekly_report["Gesamtwärmebedarf_kW"] = total_heat_demand_kw
#
# weekly_report["WP_Wärme_normal_kW"] = baseline_hp_heat_kw
# weekly_report["Kesselwärme_normal_kW"] = baseline_boiler_heat_kw
# weekly_report["Gesamterzeugung_normal_kW"] = baseline_total_heat_production_kw
#
# weekly_report["WP_Wärme_geregelt_kW"] = controlled_hp_heat_kw
# weekly_report["Kesselwärme_geregelt_kW"] = controlled_boiler_heat_kw
# weekly_report["Gesamterzeugung_geregelt_kW"] = controlled_total_heat_production_kw
#
# weekly_report["WP_Massenstrom_normal_kg_s"] = baseline_hp_mdot_kg_s
# weekly_report["WP_Massenstrom_geregelt_kg_s"] = controlled_hp_mdot_kg_s
# weekly_report["Kessel_Massenstrom_normal_kg_s"] = baseline_boiler_mdot_kg_s
# weekly_report["Kessel_Massenstrom_geregelt_kg_s"] = controlled_boiler_mdot_kg_s
#
#
# print(
#     "\n"
#     "============================================================\n"
#     "WOCHENBERICHT: NORMALBETRIEB UND GEREGELTER BETRIEB\n"
#     "============================================================"
# )
#
# print(weekly_report.round(4).to_string())
#
