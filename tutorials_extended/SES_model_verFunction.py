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

# ==================================================================================================
# 1 - IMPORTS
# ==================================================================================================
# General imports:
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
# pandaprosumer imports:
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import create_controlled_const_profile, create_controlled_battery_storage, create_controlled_ice_chp, create_controlled_electrical_optimization
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
# SES specific imports:
from tutorials_extended.data.ses_data_management import ses_data_df               # dataframe with input data
import matplotlib.dates as mdates

# ==================================================================================================
# 2 - DATA PREPARATION (done once and reused every run)
# ==================================================================================================
time_series_data = ses_data_df.copy()
time_series_data.index = pd.to_datetime(time_series_data.index)
time_series_data = time_series_data.sort_index()
time_series_data = time_series_data[~time_series_data.index.duplicated(keep="first")]

time_series_data["p_el_demand_kw"] = time_series_data["P el total [kW]"].astype(float)
time_series_data["p_pv_in_kw"] = time_series_data["P pv [kW]"].astype(float)
time_series_data["p_contract_kw"] = time_series_data["P el contr [kW]"].astype(float)
time_series_data["p_flex_kw"] = time_series_data["P el flex [kW]"].astype(float)

time_series_data["cycle"] = 1                                          # mapped output: electrical power
time_series_data["t_intake_k"] = 298.15                                # 25°C ---> assumed temperature of the CHP intake air


# ANALYSIS PERIOD
# One-week simulation with hourly resolution
week_start = pd.Timestamp("2025-07-07 00:00:00")
week_end = week_start + pd.Timedelta(days=7)

time_series_data = time_series_data.loc[(time_series_data.index >= week_start) & (time_series_data.index < week_end)]

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


time_series_data["cycle"] = 1
time_series_data["t_intake_k"] = 298.15



if time_series_data.index.tz is None:
    time_series_data.index = time_series_data.index.tz_localize("UTC")
else:
    time_series_data.index = time_series_data.index.tz_convert("UTC")


time_resolution_s = 3600
dt_h = time_resolution_s / 3600.0                  # hours per timestep, used to convert kW -> kWh (= Delta t)

start = time_series_data.index[0]
end = time_series_data.index[-1]

print("Simulation start:", start)
print("Simulation end:", end)
print("Number of timesteps:", len(time_series_data))

input_params = ["p_el_demand_kw", "p_pv_in_kw", "p_contract_kw", "p_flex_kw", "cycle", "t_intake_k"]
result_params = ["p_el_demand_cp_kw", "p_pv_in_cp_kw", "p_contract_cp_kw", "p_flex_cp_kw", "cycle_cp", "t_intake_cp_k"]


# CHP fixed properties (fuel/altitude/name don't vary across the sweep):
chp_name = "SES CHP"
chp_fuel = "ng"
chp_altitude_m = 290


# ==================================================================================================
# 2 - FUNCTION (pandaprosumer)
# ==================================================================================================
def run_simulation(battery_capacity_kwh:float, chp_size_kw:float) -> dict:
    """
    - Build a new prosumer container
    - Run a single timeseries simulation with the chosen battery energy capacity and CHP size

    A new container/controllers are created on every call so runs don't interfere with each other.
    """
    prosumer = create_empty_prosumer_container(check_order=False)
    period = create_period(prosumer, time_resolution_s, start, end, "UTC", "default")
    time_series_input = DFData(time_series_data)

    # C-Rate Battery power to capacity ratio
    c = 1


    # CREATING MODEL ELEMENTS
    # Const. profile
    cp_index = create_controlled_const_profile(prosumer, input_params, result_params, time_series_input, period, level=0, order=0)

    # CHP:
    ice_chp_index = create_controlled_ice_chp(prosumer, chp_size_kw, chp_fuel, chp_altitude_m, chp_name, level=2, order=1)

    # Battery:
    battery_index = create_controlled_battery_storage(
        prosumer=prosumer, e_capacity_kwh=battery_capacity_kwh, p_charge_max_kw=battery_capacity_kwh/c, p_discharge_max_kw=battery_capacity_kwh/c,
        eta_charge=0.95, eta_discharge=0.95, soc_min=0.20, soc_max=0.80,
        self_discharge_per_hour=0.0001, init_soc=0.80, name="SES Battery", level=2, order=0                                   # !!! ATTENTO: init_soc < soc_max !!!
    )

    # Optimiser:
    optimization_index = create_controlled_electrical_optimization(
        prosumer=prosumer, name="SES Electrical Optimization", period=period, level=1,
        order=0, solver_name="appsi_highs", p_large_requested_threshold_kw=500.0,
        sustained_request_timesteps=4, request_tolerance_kw=1e-6, weight_target=1e5,
        weight_contract=1e7
    )


    # CONNECTIONS - MAPPINGS:
    # Const. profile ---> optimiser
    GenericMapping(
        prosumer,
        initiator_id=cp_index,
        initiator_column=["p_el_demand_cp_kw", "p_pv_in_cp_kw", "p_contract_cp_kw", "p_flex_cp_kw"],
        responder_id=optimization_index,
        responder_column=["p_el_demand_kw", "p_pv_in_kw", "p_contract_kw", "p_flex_kw"]
    )

    # Const. profile ---> CHP
    GenericMapping(
        prosumer,
        initiator_id=cp_index,
        initiator_column=["cycle_cp", "t_intake_cp_k"],
        responder_id=ice_chp_index,
        responder_column=["cycle", "t_intake_k"]
    )

    # Optimiser ---> battery
    GenericMapping(
        prosumer,
        initiator_id=optimization_index,
        initiator_column="p_battery_kw",
        responder_id=battery_index,
        responder_column="p_requested_kw"
    )

    # Optimiser ---> CHP
    GenericMapping(
        prosumer,
        initiator_id=optimization_index,
        initiator_column="p_el_chp_kw",
        responder_id=ice_chp_index,
        responder_column="p_requested_kw"
    )

    # RUN THE ANALYSIS:
    run_timeseries(prosumer, period, verbose=False)


    if not hasattr(prosumer, "optimizer_controller_results"):
        raise RuntimeError("No optimizer_controller_results were written by the electrical optimization controller")

    optimized_results = pd.DataFrame.from_dict(prosumer.optimizer_controller_results, orient="index")
    optimized_results.index = pd.to_datetime(optimized_results.index)
    optimized_results = optimized_results.sort_index()

    # El. grid buy and sell:
    # (i) Power
    p_grid_import_kw = optimized_results["p_grid_dispatch_kw"].clip(lower=0.0)        # ignore any export, keep import only ---> positive grid dispatch
    p_grid_export_kw = (-optimized_results["p_grid_dispatch_kw"]).clip(lower=0.0)     # negative grid dispatch
    # (ii) Energy
    e_grid_import_total_kwh = float((p_grid_import_kw * dt_h).sum())
    e_grid_export_total_kwh = float((p_grid_export_kw * dt_h).sum())
    p_grid_import_peak_kw   = float(p_grid_import_kw.max())

    # CHP electricity generation:
    # (i) Power
    p_chp_gener_kw = optimized_results["dispatch_p_el_chp_kw"]
    # (ii) Energy
    e_chp_gener_kwh = float((p_chp_gener_kw * dt_h).sum())

    #P contracted
    p_contracted_kw = optimized_results["p_contract_kw"]
    # P above contracual limit:
    p_over_contr_kw = (p_grid_import_kw - p_contracted_kw).clip(lower=0.0)

    e_over_contr_kwh = float((p_over_contr_kw * dt_h).sum())

    # demand
    e_consumption_kwh = float(
        (optimized_results["p_el_demand_kw"] * dt_h).sum()
    )

    e_pv_total_kwh = float((optimized_results["p_pv_in_kw"] * dt_h).sum())
    e_battery_net_kwh = float((optimized_results["dispatch_p_battery_kw"] * dt_h).sum())  # discharge - charge

    balance_check = (e_chp_gener_kwh
                     + e_grid_import_total_kwh - e_grid_export_total_kwh
                     + e_pv_total_kwh
                     + e_battery_net_kwh) - e_consumption_kwh

    print(f"PV total: {e_pv_total_kwh:.1f} kWh, Import: {e_grid_import_total_kwh:.1f} kWh, "
          f"Battery net: {e_battery_net_kwh:.1f} kWh, Bilanzfehler: {balance_check:.4f} kWh")

    fig, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

    ax[0].plot(optimized_results.index, optimized_results["p_grid_baseline_kw"], label="Baseline grid import")
    ax[0].plot(
        optimized_results.index,
        optimized_results["p_grid_target_kw"],
        label="Requested grid target",
        linestyle=":"
    )
    ax[0].plot(optimized_results.index, optimized_results["p_grid_dispatch_kw"], label="Optimized grid import")
    ax[0].plot(optimized_results.index, optimized_results["p_contract_kw"], label="Contractual grid limit",
               linestyle="--")
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

    # # Energy cost of grid import only, using the same hourly price series (EUR/MWh -> EUR/kWh)
    # price_eur_per_kwh = results["electricity_price_eur_per_mwh"] / 1000.0 if "electricity_price_eur_per_mwh" in results else None
    # total_import_cost_eur = float((grid_import_kw * dt_h * price_eur_per_kwh).sum()) if price_eur_per_kwh is not None else np.nan

    return {
        "battery_capacity_kwh": battery_capacity_kwh,
        "chp_size_kw": chp_size_kw,
        "total_grid_import_kwh": e_grid_import_total_kwh,
        "total_grid_export_kwh": e_grid_export_total_kwh,
        "peak_grid_import_kw": p_grid_import_peak_kw,
        #"total_import_cost_eur": total_import_cost_eur,
        "total_chp_generation_kwh": e_chp_gener_kwh,
        "total_energy_over_contractual_limit_kwh": e_over_contr_kwh,
    }


# ==================================================================================================
# 3 - PARAMETRIC SWEEP
# ==================================================================================================                               # a single value (e.g. [350]) for sweeping battery capacity only
chp_size_kw = [350]

battery_capacity_kwh = [9e3, 1e4, 3e4, 5e4, 7e4, 9e4]


if __name__ == "__main__":
    sweep_results = []
    total_runs = len(chp_size_kw) * len(battery_capacity_kwh)
    run_counter = 0
    for chp_size in chp_size_kw:
        for capacity in battery_capacity_kwh:
            run_counter += 1
            print(f"[{run_counter}/{total_runs}] Running chp_size_kw = {chp_size:,.4g}, "
                  f"battery_capacity_kwh = {capacity:,.4g} ...")
            try:
                simulation_results = run_simulation(capacity, chp_size)
                sweep_results.append(simulation_results)
                # print(f"    -> total grid import: {metrics['total_grid_import_kwh']:.2f} kWh, "
                #       f"peak: {metrics['peak_grid_import_kw']:.2f} kW")
            except Exception as exc:
                print(f" Run failed for chp_size_kw={chp_size}, capacity={capacity}: {exc}")

    #sweep_df = pd.DataFrame(sweep_results).sort_values(["chp_size_kw", "battery_capacity_kwh"]).reset_index(drop=True)
    sweep_df = pd.DataFrame(sweep_results)

    output_file = Path(__file__).resolve().parent / "battery_capacity_sweep_results.csv"
    sweep_df.to_csv(output_file, index=False)
    print("\nSweep results written to:", output_file)
    print(sweep_df)


    # ===================================================================================================
    # 4 - PLOTS
    # ===================================================================================================

    fig, ax1 = plt.subplots(figsize=(9, 6))
    colors = plt.cm.viridis(np.linspace(0, 0.85, len(chp_size_kw)))

    for chp_size, color in zip(chp_size_kw, colors):
        subset = sweep_df[sweep_df["chp_size_kw"] == chp_size]
        ax1.plot(subset["battery_capacity_kwh"], subset["total_energy_over_contractual_limit_kwh"], marker="o", color=color, label=f"CHP {chp_size:.0f} kW - grid import over contr. limit")

    ax1.set_xscale("log")
    ax1.set_xlabel("Battery capacity [kWh] (log scale)")
    ax1.set_ylabel("Total grid import over contractual limit [kWh]")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend(loc="upper left")

    fig.suptitle("Effect of battery capacity and CHP size on grid energy import over contractual limit")
    fig.tight_layout()

    plot_file = Path(__file__).resolve().parent / "battery_capacity_sweep_plot.png"
    fig.savefig(plot_file, dpi=150)
    print("Plot saved to:", plot_file)

    plt.show()

    fig, ax3 = plt.subplots(figsize=(9, 6))
    colors = plt.cm.viridis(np.linspace(0, 0.85, len(chp_size_kw)))

    for chp_size, color in zip(chp_size_kw, colors):
        subset = sweep_df[sweep_df["chp_size_kw"] == chp_size]
        ax3.plot(subset["battery_capacity_kwh"], subset["total_grid_import_kwh"], marker="o",
                 color=color, label=f"CHP {chp_size:.0f} kW - grid import")

    ax3.set_xscale("log")
    ax3.set_xlabel("Battery capacity [kWh] (log scale)")
    ax3.set_ylabel("Total grid import [kWh]")
    ax3.grid(True, which="both", alpha=0.3)
    ax3.legend(loc="upper left")

    fig.suptitle("Effect of battery capacity and CHP size on grid energy import")
    fig.tight_layout()

    plot_file = Path(__file__).resolve().parent / "battery_capacity_sweep_plot_import.png"
    fig.savefig(plot_file, dpi=150)
    print("Plot saved to:", plot_file)

    plt.show()

    #............................................................

    fig, ax2 = plt.subplots(figsize=(9, 6))
    colors = plt.cm.viridis(np.linspace(0, 0.85, len(chp_size_kw)))

    for chp_size, color in zip(chp_size_kw, colors):
        subset = sweep_df[sweep_df["chp_size_kw"] == chp_size]
        ax2.plot(subset["battery_capacity_kwh"], subset["total_chp_generation_kwh"], marker="o", color=color, label=f"CHP {chp_size:.0f} kW - CHP generation")

    ax2.set_xscale("log")
    ax2.set_xlabel("Battery capacity [kWh] (log scale)")
    ax2.set_ylabel("Total CHP generation [kWh]")
    ax2.grid(True, which="both", alpha=0.3)
    ax2.legend(loc="upper right")

    fig.suptitle("Effect of battery capacity and CHP size on the CHP electricity generation")
    fig.tight_layout()

    plot_file = Path(__file__).resolve().parent / "battery_capacity_sweep_plot_chp.png"
    fig.savefig(plot_file, dpi=150)
    print("Plot saved to:", plot_file)

    plt.show()