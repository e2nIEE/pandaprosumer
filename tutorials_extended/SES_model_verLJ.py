import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"                                                         # OpenMP runtime conflict--->temp solution

# Kernel path
import sys
print(sys.executable)

# Setting the path to the pandaprosumer source:
from pathlib import Path
import sys

source_root = Path(__file__).resolve().parent.parent
sys.path.append(str(source_root / "src"))
#===================================================================================================

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
import numpy as np

from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import create_controlled_const_profile, create_controlled_battery_storage, create_controlled_ice_chp, create_controlled_electrical_optimization
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
from tutorials_extended.data.ses_data_management import ses_data_df

prosumer = create_empty_prosumer_container(check_order=False)

# Time-series dataframe
time_series_data = ses_data_df.copy()
time_series_data.index = pd.to_datetime(time_series_data.index)
time_series_data = time_series_data.sort_index()
time_series_data = time_series_data[~time_series_data.index.duplicated(keep="first")]

time_series_data["p_el_demand_kw"] = time_series_data["P el total [kW]"].astype(float)
time_series_data["p_pv_in_kw"] = time_series_data["P pv [kW]"].astype(float)
time_series_data["p_contract_kw"] = time_series_data["P el contr [kW]"].astype(float)
time_series_data["p_flex_kw"] = time_series_data["P el flex [kW]"].astype(float)

time_series_data["cycle"] = 1
time_series_data["t_intake_k"] = 298.15

# One-week simulation with hourly resolution
week_start = pd.Timestamp("2025-07-07 00:00:00")
week_end = week_start + pd.Timedelta(days=7)

time_series_data = time_series_data.loc[
    (time_series_data.index >= week_start)
    & (time_series_data.index < week_end)
]

hourly_data = pd.DataFrame({
    "p_el_demand_kw": time_series_data["p_el_demand_kw"].resample("1h").mean(),
    "p_pv_in_kw": time_series_data["p_pv_in_kw"].resample("1h").mean(),
    "p_contract_kw": time_series_data["p_contract_kw"].resample("1h").min(),
    "p_flex_kw": time_series_data["p_flex_kw"].resample("1h").mean()
})

time_series_data = hourly_data.dropna(
    subset=[
        "p_el_demand_kw",
        "p_pv_in_kw",
        "p_contract_kw",
        "p_flex_kw"
    ]
)

daily_prices = [                                                                       # electricity prices ---> TODO: USE REAL VALUES !!!
    115.95, 102.00, 97.82, 94.10, 96.07, 106.78,
    128.24, 133.03, 139.43, 126.02, 110.65, 102.19,
    87.17, 88.44, 85.88, 91.39, 112.49, 118.36,
    129.77, 145.34, 156.06, 132.83, 129.77, 96.33
]

time_series_data[("electricity_price_eur_per_mwh")] = np.tile(
    daily_prices,
    len(time_series_data) // 24 + 1
)[:len(time_series_data)]

time_series_data["cycle"] = 1
time_series_data["t_intake_k"] = 298.15
time_series_data["electricity_price_eur_per_mwh"] += 150 # Taxes, etc.
time_series_data["gas_price_eur_per_mwh"] = 20                                        # gas prices ---> TODO: USE REAL VALUES !!!

if time_series_data.index.tz is None:
    time_series_data.index = time_series_data.index.tz_localize("UTC")
else:
    time_series_data.index = time_series_data.index.tz_convert("UTC")

time_resolution = 3600
start = time_series_data.index[0]
end = time_series_data.index[-1]

period = create_period(prosumer, time_resolution, start, end, "UTC", "default")
time_series_input = DFData(time_series_data)

print("Simulation start:", start)
print("Simulation end:", end)
print("Number of timesteps:", len(time_series_data))
print(time_series_data.head())

# setup of controllers
# Constant profile
input_params = ["p_el_demand_kw", "p_pv_in_kw", "p_contract_kw", "p_flex_kw", "cycle", "t_intake_k",
                "electricity_price_eur_per_mwh", "gas_price_eur_per_mwh"]
result_params = ["p_el_demand_cp_kw", "p_pv_in_cp_kw", "p_contract_cp_kw", "p_flex_cp_kw", "cycle_cp", "t_intake_cp_k",
                 "electricity_price_eur_per_mwh_cp", "gas_price_eur_per_mwh_cp"]

cp_index = create_controlled_const_profile(prosumer, input_params, result_params, time_series_input, period, level=0, order=0)

# CHP
chp_name = "SES CHP"
chp_size_kw = 350
chp_fuel = "ng"
chp_altitude_m = 0

ice_chp_index = create_controlled_ice_chp(prosumer, chp_size_kw, chp_fuel, chp_altitude_m, chp_name, level=2, order=1)

# Battery storage
#battery_capacity = 1e308                                         # minimum capacity = 0.0000000000000011 kWh ---> below this value the program doesn't work // 80000000000000000000000 or 1e308 max. value
battery_capacity = 10e6
battery_index = create_controlled_battery_storage(prosumer=prosumer, e_capacity_kwh=battery_capacity, p_charge_max_kw=1000.0, p_discharge_max_kw=1000.0, eta_charge=0.95, eta_discharge=0.95, soc_min=0.10, soc_max=0.90,
                                                  self_discharge_per_hour=0.0001, init_soc=0.90, name="SES Battery", level=2, order=0)

# Electrical optimization controller
optimization_index = create_controlled_electrical_optimization(prosumer=prosumer, name="SES Electrical Optimization", period=period, level=1,
                                                               order=0, solver_name="appsi_highs", p_large_requested_threshold_kw=500.0,
                                                               sustained_request_timesteps=4, request_tolerance_kw=1e-6, weight_target=1e5,
                                                               weight_contract=1e7)


# input mappings from const. prof controller to chp and el. optim
GenericMapping(
    prosumer,
    initiator_id=cp_index,
    initiator_column=["p_el_demand_cp_kw", "p_pv_in_cp_kw", "p_contract_cp_kw", "p_flex_cp_kw", "electricity_price_eur_per_mwh_cp", "gas_price_eur_per_mwh_cp"],
    responder_id=optimization_index,
    responder_column=["p_el_demand_kw", "p_pv_in_kw", "p_contract_kw", "p_flex_kw", "electricity_price_eur_per_mwh", "gas_price_eur_per_mwh"]
)

GenericMapping(
    prosumer,
    initiator_id=cp_index,
    initiator_column=["cycle_cp", "t_intake_cp_k"],
    responder_id=ice_chp_index,
    responder_column=["cycle", "t_intake_k"]
)

# Optimizer output mappings
GenericMapping(
    prosumer,
    initiator_id=optimization_index,
    initiator_column="p_battery_kw",
    responder_id=battery_index,
    responder_column="p_requested_kw"
)

GenericMapping(
    prosumer,
    initiator_id=optimization_index,
    initiator_column="p_el_chp_kw",
    responder_id=ice_chp_index,
    responder_column="p_requested_kw"
)


run_timeseries(prosumer, period, verbose=True)

# Collect optimization results
if not hasattr(prosumer, "optimizer_controller_results"):
    raise RuntimeError("No optimizer_controller_results were written by the electrical optimization controller")

optimized_results = pd.DataFrame.from_dict(prosumer.optimizer_controller_results, orient="index")
optimized_results.index = pd.to_datetime(optimized_results.index)
optimized_results = optimized_results.sort_index()

# Export results to csv-file
output_file = Path(__file__).resolve().parent / "ses_electrical_optimization_results.csv"
optimized_results.to_csv(output_file, index_label="Timestamp")

print("\nElectrical optimization results:")
print(optimized_results.head())

print("\nResults written to:")
print(output_file)

# Plot results
fig, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

ax[0].plot(optimized_results.index, optimized_results["p_grid_baseline_kw"], label="Baseline grid import")
ax[0].plot(
    optimized_results.index,
    optimized_results["p_grid_target_kw"],
    label="Requested grid target",
    linestyle=":"
)
ax[0].plot(optimized_results.index, optimized_results["p_grid_dispatch_kw"], label="Optimized grid import")
ax[0].plot(optimized_results.index, optimized_results["p_contract_kw"], label="Contractual grid limit", linestyle="--")
ax[0].set_ylabel("Grid power [kW]")
ax[0].legend()
ax[0].grid(True)

ax[1].plot(optimized_results.index, optimized_results["dispatch_p_el_chp_kw"], label="CHP electrical output")
ax[1].plot(optimized_results.index, optimized_results["dispatch_p_battery_kw"], label="Battery power")
ax[1].axhline(0.0, linewidth=1.0)
ax[1].set_ylabel("Device power [kW]")
ax[1].legend()
ax[1].grid(True)

ax[2].plot(optimized_results.index, optimized_results["dispatch_battery_soc"] * 100.0, label="Battery SOC")
ax[2].plot(
    optimized_results.index,
    optimized_results["p_flex_request_kw"],
    label="External flexibility request",
    linestyle=":"
)
ax[2].set_ylabel("SOC [%] / Flex [kW]")
ax[2].set_xlabel("Time")
ax[2].legend()
ax[2].grid(True)

hour_format = mdates.DateFormatter("%d.%m %H:%M")
ax[2].xaxis.set_major_formatter(hour_format)

fig.autofmt_xdate()
fig.tight_layout()
plt.show()