import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
import numpy as np

from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_battery_storage,
                                             create_controlled_ice_chp, create_controlled_electrical_optimization_mpc,
                                             create_controlled_electrical_optimization)
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
#TODO- resample overall to 15min for the MPC
hourly_data = pd.DataFrame({
    "p_el_demand_kw": time_series_data["p_el_demand_kw"].resample("1h").mean(),
    "p_pv_in_kw": time_series_data["p_pv_in_kw"].resample("1h").mean(),
    "p_contract_kw": time_series_data["p_contract_kw"].resample("1h").min(),
    "p_flex_kw": time_series_data["p_flex_kw"].resample("1h").mean()
})

hourly_data = hourly_data.dropna().copy()
hourly_data.index = pd.to_datetime(hourly_data.index, utc=True)

# Strompreise einlesen
data_dir = Path(__file__).resolve().parent
price_file = data_dir / "data\\ses_price_data.xlsx"
price_column = "Price (EUR/MWhe)"

price_data = pd.read_excel(price_file, index_col=0)
price_data.index = pd.to_datetime(
    price_data.index,
    errors="coerce",
    utc=True,
)
price_data = price_data.loc[price_data.index.notna()]

if price_column not in price_data.columns:
    raise KeyError(
        f"Spalte '{price_column}' fehlt in {price_file}."
    )

electricity_price = pd.to_numeric(
    price_data[price_column],
    errors="coerce",
)

electricity_price = (
    electricity_price
    .groupby(level=0)
    .mean()
    .sort_index()
    .resample("1h")
    .mean()
)

hourly_data["electricity_price_eur_per_mwh"] = (
    electricity_price.reindex(hourly_data.index)
)

if hourly_data["electricity_price_eur_per_mwh"].isna().any():
    missing = hourly_data.index[
        hourly_data["electricity_price_eur_per_mwh"].isna()
    ]
    raise ValueError(
        f"Für {len(missing)} Zeitschritte fehlen Strompreise. "
        f"Erster fehlender Wert: {missing[0]}"
    )

# Kein EV-Profil vorhanden
hourly_data["p_ev_charge_kw"] = 0.0

# Konstanter Gaspreis
hourly_data["gas_price_eur_per_mwh"] = 40.0

hourly_data["cycle"] = 1
hourly_data["t_intake_k"] = 298.15

time_series_data = hourly_data

time_resolution = 3600
start = time_series_data.index[0]
end = time_series_data.index[-1]

period = create_period(
    prosumer,
    time_resolution,
    start,
    end,
    "UTC",
    "default",
)

time_series_input = DFData(time_series_data)

print("Simulation start:", start)
print("Simulation end:", end)
print("Number of timesteps:", len(time_series_data))
print(time_series_data.head())

# setup of controllers
# Constant profile
input_params = [
    "p_el_demand_kw",
    "p_pv_in_kw",
    "p_contract_kw",
    "p_flex_kw",
    "p_ev_charge_kw",
    "electricity_price_eur_per_mwh",
    "gas_price_eur_per_mwh",
    "cycle",
    "t_intake_k",
]

result_params = [
    "p_el_demand_cp_kw",
    "p_pv_in_cp_kw",
    "p_contract_cp_kw",
    "p_flex_cp_kw",
    "p_ev_charge_cp_kw",
    "electricity_price_cp_eur_per_mwh",
    "gas_price_cp_eur_per_mwh",
    "cycle_cp",
    "t_intake_cp_k",
]

cp_index = create_controlled_const_profile(
    prosumer,
    input_params,
    result_params,
    time_series_input,
    period,
    level=0,
    order=0,
)

# CHP
chp_name = "SES CHP"
chp_size_kw = 700
chp_fuel = "ng"
chp_altitude_m = 0

ice_chp_index = create_controlled_ice_chp(prosumer, chp_size_kw, chp_fuel, chp_altitude_m, chp_name, level=2, order=1)

# Battery storage
battery_capacity = 1e4
battery_index = create_controlled_battery_storage(prosumer=prosumer, e_capacity_kwh=battery_capacity, p_charge_max_kw=battery_capacity, p_discharge_max_kw=battery_capacity, eta_charge=0.95, eta_discharge=0.95, soc_min=0.10, soc_max=0.90,
                                                  self_discharge_per_hour=0.0001, init_soc=0.60, name="SES Battery", level=2, order=0)

# Electrical optimization controller
forecast_columns = [
    "p_el_demand_kw",
    "p_pv_in_kw",
    "p_ev_charge_kw",
    "p_contract_kw",
    "electricity_price_eur_per_mwh",
    "gas_price_eur_per_mwh",
]

optimization_index = create_controlled_electrical_optimization_mpc(
    prosumer=prosumer,
    name="SES Electrical Optimization",
    period=period,
    level=1,
    order=0,
    solver_name="appsi_highs",
    horizon_steps=24,
    contract_penalty_eur_per_mwh=200.0,
    chp_start_cost_eur=50.0,
    soc_target=0.80,
    weight_soc=2000.0,
    flex_revenue_eur_per_mwh=200.0,
    request_tolerance_kw=1e-6,
    forecast_data=time_series_data[forecast_columns].copy(),
    pad_forecast_end=True,
)

# Optimiser:
# optimization_index = create_controlled_electrical_optimization(
#     prosumer=prosumer,
#     name="SES Electrical Optimization",
#     period=period,
#     level=1,
#     order=0,
#     solver_name="appsi_highs",
#     p_large_requested_threshold_kw=500.0,
#     sustained_request_timesteps=4,
#     request_tolerance_kw=1e-6,
#     weight_target=1e5,
#     weight_contract=1e7
# )


# input mappings from const. prof controller to chp and el. optim
GenericMapping(
    prosumer,
    initiator_id=cp_index,
    initiator_column=[
        "p_el_demand_cp_kw",
        "p_pv_in_cp_kw",
        "p_contract_cp_kw",
        "p_flex_cp_kw",
        "p_ev_charge_cp_kw",
        "electricity_price_cp_eur_per_mwh",
        "gas_price_cp_eur_per_mwh",
    ],
    responder_id=optimization_index,
    responder_column=[
        "p_el_demand_kw",
        "p_pv_in_kw",
        "p_contract_kw",
        "p_flex_kw",
        "p_ev_charge_kw",
        "electricity_price_eur_per_mwh",
        "gas_price_eur_per_mwh",
    ],
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

# Compare MPC CHP setpoints against physical CHP output
actual_chp = {}

for timestamp, controller_data in (prosumer.controller_results.items()):
    chp_data = controller_data.get(ice_chp_index, {})
    if "p_el_out_kw" in chp_data:
        actual_chp[pd.Timestamp(timestamp)] = float(np.asarray(chp_data["p_el_out_kw"]).reshape(-1)[0])

actual_chp = pd.Series(actual_chp, dtype=float)
actual_chp.index = pd.to_datetime(actual_chp.index, utc=True)

optimized_results.index = pd.to_datetime(optimized_results.index, utc=True)

optimized_results["chp_actual_kw"] = (actual_chp.reindex(optimized_results.index))

if optimized_results["chp_actual_kw"].isna().any():
    raise ValueError("Missing actual CHP output")

optimized_results["chp_tracking_error_kw"] = (optimized_results["chp_actual_kw"] - optimized_results["dispatch_p_el_chp_kw"])

print("Max CHP tracking error [kW]:",optimized_results["chp_tracking_error_kw"].abs().max())

def actual_output(controller_index, key):
    values = {}

    for timestamp, controllers in prosumer.controller_results.items():
        data = controllers.get(controller_index, {})

        if key in data:
            values[pd.Timestamp(timestamp)] = float(
                np.asarray(data[key], dtype=float).reshape(-1)[0]
            )

    series = pd.Series(values, dtype=float)
    series.index = pd.to_datetime(series.index, utc=True)

    return series.reindex(optimized_results.index)

# Plot results
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# optimized_results must be a DataFrame with a time-based index
results = optimized_results.copy()

if not isinstance(results, pd.DataFrame):
    raise TypeError(
        "optimized_results must contain the collected results "
        "of all time steps as a DataFrame."
    )

# Use a consistent UTC time index
results.index = pd.to_datetime(results.index, utc=True)

inputs = time_series_data[
    ["electricity_price_eur_per_mwh"]
].copy()

inputs.index = pd.to_datetime(inputs.index, utc=True)

# Align electricity prices with the optimization results
results = (
    results
    .drop(
        columns=["electricity_price_eur_per_mwh"],
        errors="ignore",
    )
    .join(inputs, how="left")
)

if results["electricity_price_eur_per_mwh"].isna().any():
    raise ValueError(
        "Electricity prices and optimization results are not "
        "fully aligned in time."
    )

# Positive power represents discharging; negative power represents charging
battery_power = (
    results["dispatch_p_battery_discharge_kw"]
    - results["dispatch_p_battery_charge_kw"]
)

chp_on = (results["dispatch_p_el_chp_kw"] > 1e-6).astype(int)

# Assumes CHP is initially OFF
startup_events = (chp_on.diff().fillna(chp_on.iloc[0]) == 1)
print("CHP startups", int(startup_events.sum()))
print("Startup cost[€]:",results["cost_startup_current_eur"].sum())
print("Expected startup cost [€]:", startup_events.sum() * 50.0)

def combined_legend(left_axis, right_axis=None):
    handles, labels = left_axis.get_legend_handles_labels()

    if right_axis is not None:
        handles_right, labels_right = (
            right_axis.get_legend_handles_labels()
        )
        handles += handles_right
        labels += labels_right

    left_axis.legend(
        handles,
        labels,
        loc="upper left",
    )


fig, ax = plt.subplots(
    5,
    1,
    figsize=(13, 14),
    sharex=True,
)

x = results.index

# 1. Electricity price and battery operation
ax_price = ax[0]
ax_battery = ax_price.twinx()

ax_price.step(
    x,
    results["electricity_price_eur_per_mwh"],
    where="post",
    color="black",
    label="Electricity price",
)

ax_battery.step(
    x,
    battery_power,
    where="post",
    color="tab:blue",
    label="Battery (+ discharge / − charge)",
)

ax_battery.axhline(
    0.0,
    color="gray",
    linewidth=0.8,
)

ax_price.set_ylabel("Price [€/MWh]")
ax_battery.set_ylabel("Battery power [kW]")
combined_legend(ax_price, ax_battery)


# 2. Grid import and contract limit
ax[1].step(
    x,
    results["p_grid_baseline_kw"],
    where="post",
    color="tab:gray",
    label="Baseline",
)

ax[1].step(
    x,
    results["p_grid_dispatch_kw"],
    where="post",
    color="tab:blue",
    label="Optimized",
)

ax[1].step(
    x,
    results["p_contract_kw"],
    where="post",
    color="tab:red",
    linestyle="--",
    label="Contract limit",
)

ax[1].fill_between(
    x,
    results["p_contract_kw"].to_numpy(),
    results["p_grid_dispatch_kw"].to_numpy(),
    where=(
        results["contract_violation_kw"].to_numpy()
        > 0.0
    ),
    step="post",
    color="tab:red",
    alpha=0.25,
    label="Contract violation",
)

ax[1].set_ylabel("Grid power [kW]")
ax[1].legend(loc="upper left")


# 3. Battery SOC and CHP output
ax_soc = ax[2]
ax_chp = ax_soc.twinx()

ax_soc.plot(
    x,
    results["dispatch_battery_soc"] * 100.0,
    color="tab:purple",
    label="Battery SOC",
)

ax_chp.step(
    x,
    results["dispatch_p_el_chp_kw"],
    where="post",
    color="tab:orange",
    label="CHP output",
)

ax_soc.set_ylabel("SOC [%]")
ax_chp.set_ylabel("CHP power [kW]")
combined_legend(ax_soc, ax_chp)


# 4. Flexibility request and delivery
ax[3].step(
    x,
    results["p_flex_request_kw"],
    where="post",
    color="tab:red",
    linestyle=":",
    label="Flexibility request",
)

ax[3].step(
    x,
    results["p_flex_delivered_kw"],
    where="post",
    color="tab:green",
    label="Delivered flexibility",
)

ax[3].set_ylabel("Flexibility [kW]")
ax[3].legend(loc="upper left")


# 5. Cost of the current MPC step
ax[4].step(
    x,
    results["cost_current_step_eur"],
    where="post",
    color="tab:blue",
    label="Current-step cost",
)

infeasible = ~results["feasible"].fillna(False).astype(bool)

ax[4].scatter(
    x[infeasible],
    results.loc[
        infeasible,
        "cost_current_step_eur",
    ],
    color="red",
    marker="x",
    label="Infeasible",
    zorder=5,
)

ax[4].set_ylabel("Cost [€]")
ax[4].set_xlabel("Time")
ax[4].legend(loc="upper left")


for axis in ax:
    axis.grid(True, alpha=0.3)

ax[-1].xaxis.set_major_formatter(
    mdates.DateFormatter(
        "%d.%m\n%H:%M",
        tz=results.index.tz,
    )
)

fig.suptitle("Cost Optimization Results")
fig.tight_layout()
plt.show()

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

r = optimized_results.copy()
r.index = pd.to_datetime(r.index, utc=True)

fig, ax = plt.subplots(figsize=(15, 5))

x = mdates.date2num(r.index.to_pydatetime())
width = 0.035  # roughly 50 minutes, in days

positive_bottom = np.zeros(len(r))
negative_bottom = np.zeros(len(r))

components = {
    "Electricity": results["cost_grid_current_eur"],
    "Gas": results["cost_gas_current_eur"],
    "Contract penalty": results["cost_contract_current_eur"],
    "CHP startup": r["cost_startup_current_eur"],
    "Flexibility revenue": -results["revenue_flex_current_eur"],
}

for name, values in components.items():
    v = values.to_numpy(dtype=float)
    bottom = np.where(v >= 0, positive_bottom, negative_bottom)

    ax.bar(x, v, bottom=bottom, width=width, label=name)

    positive_bottom += np.maximum(v, 0)
    negative_bottom += np.minimum(v, 0)

ax.plot(
    r.index,
    results["cost_current_step_eur"],
    color="black",
    linewidth=1.2,
    label="Net operating cost"
)

ax.xaxis_date()
ax.xaxis.set_major_locator(mdates.DayLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
ax.set_ylabel("Hourly cost / revenue [€]")
ax.set_xlabel("Date")
ax.legend(ncol=3)
ax.grid(alpha=0.2)
plt.tight_layout()
plt.show()
# fig, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
#
# ax[0].plot(optimized_results.index, optimized_results["p_grid_baseline_kw"], label="Baseline grid import")
# ax[0].plot(optimized_results.index, optimized_results["p_grid_dispatch_kw"], label="Optimized grid import")
# ax[0].plot(optimized_results.index, optimized_results["p_contract_kw"], label="Contractual grid limit", linestyle="--")
# ax[0].set_ylabel("Grid power [kW]")
# ax[0].legend()
# ax[0].grid(True)
#
# ax[1].plot(optimized_results.index, optimized_results["dispatch_p_el_chp_kw"], label="CHP electrical output")
# ax[1].plot(optimized_results.index, optimized_results["dispatch_p_battery_kw"], label="Battery power")
# ax[1].axhline(0.0, linewidth=1.0)
# ax[1].set_ylabel("Device power [kW]")
# ax[1].legend()
# ax[1].grid(True)
#
# ax[2].plot(optimized_results.index, optimized_results["dispatch_battery_soc"] * 100.0, label="Battery SOC")
# ax[2].plot(
#     optimized_results.index,
#     optimized_results["p_flex_request_kw"],
#     label="External flexibility request",
#     linestyle=":"
# )
# ax[2].set_ylabel("SOC [%] / Flex [kW]")
# ax[2].set_xlabel("Time")
# ax[2].legend()
# ax[2].grid(True)
#
# hour_format = mdates.DateFormatter("%d.%m %H:%M")
# ax[2].xaxis.set_major_formatter(hour_format)
#
# fig.autofmt_xdate()
# fig.tight_layout()
# plt.show()