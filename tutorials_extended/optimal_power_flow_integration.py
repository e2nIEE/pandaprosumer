from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import pandapower as pp
from pandapower.networks import lv_schutterwald
from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_heat_demand,
                                             create_controlled_booster_heat_pump, create_controlled_ice_chp,
                                             create_controlled_heat_storage, create_controlled_optimtization)
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries


# 1. Time settings and mall residual electrical load from SES Excel data
# SC_el_demand - SC_Pv_gen
frequency = "60min"
time_resolution = 3600

project_root = (Path.cwd().parent if Path.cwd().name in ["tutorials", "tutorials_extended"]
                else Path.cwd())

ses_data_file = project_root / "tutorials_extended" / "data" / "ses_data.xlsx"
heat_data_file = project_root / "tutorials_extended" / "data" / "aleja_heat_demand_model_data.xlsx"

# Read SES electrical data
ses_data = pd.read_excel(ses_data_file)
ses_data.columns = ses_data.columns.str.strip()
ses_data = ses_data.set_index("Timestamp").sort_index()
# sc demand and pv gen cols
required_cols = ["P el sc [kW]", "P pv [kW]"]

for col in required_cols:
    ses_data[col] = (ses_data[col].astype(str).str.replace(",", ".", regex=False))
    ses_data[col] = pd.to_numeric(ses_data[col], errors="coerce")

ses_data = ses_data.dropna(subset=required_cols)

# Convert SES data to 1-hour resolution
ses_data_1h = ses_data[required_cols].resample("60min").mean()
ses_data_1h = ses_data_1h.dropna(subset=required_cols)

# Use first 8 days
start_timestamp = ses_data_1h.index.min()
end_timestamp = start_timestamp + pd.Timedelta(days=8) - pd.Timedelta(hours=1)

ses_data_1h = ses_data_1h.loc[start_timestamp:end_timestamp]

# Simulation time range
start = ses_data_1h.index.min().strftime("%Y-%m-%d %H:%M:%S")
end = ses_data_1h.index.max().strftime("%Y-%m-%d %H:%M:%S")

# Mall residual electrical demand before CHP/BHP operation
# Positive value = mall imports from grid before CHP/BHP
# Negative value = PV surplus before CHP/BHP

p_el_sc_kw = ses_data_1h["P el sc [kW]"].astype(float).to_numpy()
p_pv_kw = ses_data_1h["P pv [kW]"].astype(float).to_numpy()

residual_mall_load_kw = p_el_sc_kw - p_pv_kw

n_steps = len(residual_mall_load_kw)

# Baseline: no external flex request
baseline_flex_target_kw = np.zeros(n_steps)

# Heat-demand input data
time_series_data = pd.read_excel(heat_data_file)

# Make heat-demand dataframe same length as 1h data
if len(time_series_data) < n_steps:
    repeat_factor = int(np.ceil(n_steps / len(time_series_data)))
    time_series_data = pd.concat(
        [time_series_data] * repeat_factor,
        ignore_index=True,
    )

time_series_data = time_series_data.iloc[:n_steps].copy()

dur = pd.date_range(start=start, periods=n_steps, freq=frequency, tz="utc",)
time_series_data.index = dur

time_series_data["flex_demand_kw"] = baseline_flex_target_kw
time_series_data["t_sink_k"] = 350
time_series_data["cycle"] = 1

print("\n SES mall data at 1-hour resolution")
print(f"Start: {start}")
print(f"End: {end}")
print(f"Number of timesteps: {n_steps}")
print(f"P_el_sc min/max: {p_el_sc_kw.min():.3f} / {p_el_sc_kw.max():.3f} kW")
print(f"P_pv min/max: {p_pv_kw.min():.3f} / {p_pv_kw.max():.3f} kW")
print(f"Residual mall load min/max: {residual_mall_load_kw.min():.3f} / {residual_mall_load_kw.max():.3f} kW")

assert len(time_series_data) == n_steps
assert len(baseline_flex_target_kw) == n_steps
assert len(residual_mall_load_kw) == n_steps


# 2. pprosumer model 
def build_mall_prosumer(time_series_data_base, flex_target_kw, start, 
                        end, time_resolution, frequency, collect_bounds=False, tz="utc"):
    
    prosumer = create_empty_prosumer_container(check_order=False)

    time_series_data_mall = time_series_data_base.copy()
    time_series_data_mall["flex_demand_kw"] = np.asarray(flex_target_kw)
    time_series_data_mall["t_sink_k"] = 350
    time_series_data_mall["cycle"] = 1
    time_series_data_mall.index = pd.date_range(start=start, end=end, freq=frequency, tz=tz)

    time_series_input = DFData(time_series_data_mall)

    period = create_period(prosumer, time_resolution, start, end, 'utc', 'default')

    input_params = ['mode', 't_source_k', 'q_demand_kw', 'cycle', 't_intake_k',
                    "flex_demand_kw", "p_el_bhp", "p_el_chp", "t_amb_k", "t_sink_k"]
    result_params = ['mode_cp', 't_source_cp_k', 'q_demand_cp_kw', 'cycle_cp', 't_intake_cp_k',
                     "flex_demand_cp_kw", "p_el_bhp_cp", "p_el_chp_cp", "t_amb_k_cp", "t_sink_k_cp"]

    cp_index = create_controlled_const_profile(
        prosumer, input_params, result_params, time_series_input, period, level=0)

    bhp_type = 'water-water2'
    bhp_name = 'example_bhp'
    max_thermal_power_kw = 800

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
    size_kw = 350
    fuel = 'ng'
    altitude_m = 0

    ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=2, order=1)

    q_capacity_kwh = 50000

    heat_storage_index = create_controlled_heat_storage(prosumer, q_capacity_kwh, init_soc=0.0, level=2, order=2)

    heat_demand_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=2, order=3)

    optimization_index = create_controlled_optimtization(prosumer, level=1, order=1)

    GenericMapping(prosumer,
                   initiator_id=cp_index,
                   initiator_column=["t_source_cp_k", "mode_cp", "p_el_bhp_cp", "t_amb_k_cp", "t_sink_k_cp"],
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
                   initiator_column=["t_source_cp_k", "mode_cp", "p_el_bhp_cp", "t_amb_k_cp", "t_sink_k_cp"],
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

    optimization_controller = prosumer.controller.loc[optimization_index, "object"]

    optimization_controller.collect_flex_bounds = collect_bounds
    optimization_controller._flex_bounds_log = {}

    return prosumer, period, optimization_controller


# 3. pprosumer run with controller-based bounds
def run_mall_case_with_bounds(time_series_data_base, flex_target_kw, residual_mall_load_kw,
                              start, end, time_resolution, frequency, collect_bounds=False,
                              allow_export=False, verbose=False):
    
    prosumer, period, optimization_controller = build_mall_prosumer(time_series_data_base=time_series_data_base, flex_target_kw=flex_target_kw, 
                                                                    start=start, end=end, time_resolution=time_resolution,
                                                                    frequency=frequency, collect_bounds=collect_bounds)

    run_timeseries(prosumer, period, verbose=verbose)

    res_bhp, res_chp, res_storage, res_heat_demand = [prosumer.time_series.data_source.iloc[i].df
                                                      for i in range(2, 6)]

    residual_mall_series = pd.Series(np.asarray(residual_mall_load_kw), index=res_chp.index, name="residual_mall_load_kw",)

    p_device_kw = res_chp["p_el_out_kw"] - res_bhp["p_el_floor"]
    p_grid_kw = residual_mall_series - p_device_kw

    res_df = pd.DataFrame({
        "residual_mall_load_kw": residual_mall_series,
        "chp_p_el_kw": res_chp["p_el_out_kw"],
        "bhp_p_el_kw": res_bhp["p_el_floor"],
        "p_device_kw": p_device_kw,
        "p_grid_kw": p_grid_kw,
        "chp_q_th_kw": res_chp["p_th_out_kw"],
        "bhp_q_th_kw": res_bhp["q_floor"],
        "q_delivered_storage_kw": res_storage["q_delivered_kw"],
        "q_received_demand_kw": res_heat_demand["q_received_kw"],
        "soc_percent": res_storage["soc"] * 100,
        "flex_target_kw": flex_target_kw
    }, index=res_chp.index)
    
    if not collect_bounds:
        return res_df, None

    bounds_log = getattr(optimization_controller, "_flex_bounds_log", {})

    if not bounds_log:
        raise RuntimeError("No flexibility bounds")

    bounds_df = pd.DataFrame.from_dict(bounds_log, orient="index")
    bounds_df.index = pd.to_datetime(bounds_df.index)
    bounds_df = bounds_df.reindex(res_df.index)

    if "feasible" not in bounds_df.columns:
        raise RuntimeError("Bounds log does not contain the expected 'feasible' col.")

    # Convert device-side powers into grid-side mall consumption
    # P_grid = P_residual_mall - P_device
    # max support means maximum P_device -> minimum grid consumption
    # max absorption means minimum P_device -> maximum grid consumption
    residual_kw = res_df["residual_mall_load_kw"]
    # flex envelope kw
    bounds_df["p_mall_base_kw"] = res_df["p_grid_kw"]
    bounds_df["p_mall_min_kw"] = (residual_kw - bounds_df["p_device_max_support_kw"])
    bounds_df["p_mall_max_kw"] = (residual_kw - bounds_df["p_device_max_absorption_kw"])

    #TODO: CHeck this

    # if mall cannot export to the grid back, clips the mall as a controllable load to reduce consumption till 0
    if not allow_export:
        bounds_df["p_mall_base_kw"] = bounds_df["p_mall_base_kw"].clip(lower=0.0)
        bounds_df["p_mall_min_kw"] = bounds_df["p_mall_min_kw"].clip(lower=0.0)
        bounds_df["p_mall_max_kw"] = bounds_df["p_mall_max_kw"].clip(lower=0.0)

    raw_cols = ["p_mall_min_kw", "p_mall_base_kw", "p_mall_max_kw"]

    #############################
    bounds_df["p_mall_min_mw"] = bounds_df[raw_cols].min(axis=1) / 1000.0
    bounds_df["p_mall_base_mw"] = bounds_df["p_mall_base_kw"] / 1000.0
    bounds_df["p_mall_max_mw"] = bounds_df[raw_cols].max(axis=1) / 1000.0

    bounds_df["flex_down_mw"] = (bounds_df["p_mall_base_mw"] - bounds_df["p_mall_min_mw"])
    bounds_df["flex_up_mw"] = (bounds_df["p_mall_max_mw"] - bounds_df["p_mall_base_mw"])

    return res_df, bounds_df

# 4. pandapower OPF integration
v_min_pu_std= 0.90
v_max_pu_std = 1.10
loading_percent_max_std = 150.0


def run_pf(net, context=""):
    try:
        pp.runpp(net, algorithm="nr", max_iteration=50, tolerance_mva=1e-8, init="auto", numba=False)
        return True

    except Exception as exc:
        print(f"\nPower flow failed: {context}")
        print(f"Reason: {exc}")
        return False

def check_grid_violations(net):
    """
    Check voltage, line-loading and transformer-loading violations after a power flow
    """

    violations = {"undervoltage": [],
                  "overvoltage": [],
                  "line_overload": [],
                  "trafo_overload": []
                  }

    # Bus voltage violations
    for bus in net.res_bus.index:
        vm_pu = net.res_bus.at[bus, "vm_pu"]

        if vm_pu < v_min_pu_std:
            violations["undervoltage"].append((bus, vm_pu))

        if vm_pu > v_max_pu_std:
            violations["overvoltage"].append((bus, vm_pu))

    # Line loading violations
    if len(net.line):
        for line in net.res_line.index:
            loading = net.res_line.at[line, "loading_percent"]

            if loading > loading_percent_max_std:
                violations["line_overload"].append((line, loading))

    # Transformer loading violations
    if len(net.trafo):
        for trafo in net.res_trafo.index:
            loading = net.res_trafo.at[trafo, "loading_percent"]

            if loading > loading_percent_max_std:
                violations["trafo_overload"].append((trafo, loading))

    has_violation = any(len(v) > 0 for v in violations.values())

    return has_violation, violations


def prepare_grid_for_opf(net):
    """
    Prepare the Schutterwald grid for the OPF test
    Existing grid loads and sgens are fixed
    Only the shopping-mall load will be controllable
    """
    if len(net.load):
        net.load["controllable"] = False

    if len(net.sgen):
        net.sgen["controllable"] = False

    # Relaxed limits for this use case only
    net.bus["min_vm_pu"] = v_min_pu_std
    net.bus["max_vm_pu"] = v_max_pu_std

    if len(net.line):
        net.line["max_loading_percent"] = loading_percent_max_std

    if len(net.trafo):
        net.trafo["max_loading_percent"] = loading_percent_max_std

    #  slack limits for ext grid for grid balance
    net.ext_grid["min_p_mw"] = -10.0
    net.ext_grid["max_p_mw"] = 10.0
    net.ext_grid["min_q_mvar"] = -10.0
    net.ext_grid["max_q_mvar"] = 10.0


def run_mall_opf_min_deviation(net, mall_load, p_base_mw):
    """
    Run OPF with one controllable mall load.

    Objective:
        min (P_mall - P_base)^2

        Use as minimal flexibility activation as possible while satisfying voltage and loading constraints
    """

    if "poly_cost" in net and len(net.poly_cost):
        net.poly_cost.drop(net.poly_cost.index, inplace=True)

    weight = 1000.0

    pp.create_poly_cost(net, element=mall_load, et="load", cp2_eur_per_mw2=weight, cp1_eur_per_mw=-2.0 * weight * p_base_mw, cp0_eur=weight * p_base_mw**2)

    for eg in net.ext_grid.index:
        pp.create_poly_cost(net, element=eg, et="ext_grid", cp1_eur_per_mw=0.0, cp2_eur_per_mw2=0.0)

    try:
        pp.runopp(net, calculate_voltage_angles=False, init="pf", numba=False, verbose=False, suppress_warnings=True, OPF_VIOLATION=1e-4, PDIPM_FEASTOL=1e-4,
                  PDIPM_GRADTOL=1e-4, PDIPM_COMPTOL=1e-4, PDIPM_COSTTOL=1e-4, PDIPM_MAX_IT=500,)

    except Exception as exc:
        print("\nOPF failed.")
        print(f"Reason: {exc}")
        return None

    if not getattr(net, "OPF_converged", False):
        print("\nOPF did not converge.")
        return None

    return net.res_load.at[mall_load, "p_mw"]


def plot_results(v_before, v_after, bounds_df, selected_time, p_min_mw, p_base_mw, p_max_mw, p_reference_mw, p_opf_mw, p_updated_grid_kw):

    sorted_buses = v_before.sort_values().index
    plt.figure(figsize=(10, 6))

    plt.plot(range(len(sorted_buses)), v_before.loc[sorted_buses].values, label="Before OPF")
    plt.plot(range(len(sorted_buses)), v_after.loc[sorted_buses].values, label="After OPF ")

    plt.axhline(v_min_pu_std, linestyle="--", label=f"V_min limit {v_min_pu_std:.2f} pu")
    plt.axhline(v_max_pu_std, linestyle="--", label=f"V_max demo limit {v_max_pu_std:.2f} pu")

    plt.xlabel("Buses sorted by voltage before OPF")
    plt.ylabel("Voltage [pu]")
    plt.title("Grid Voltage Before and After Mall OPF dispatch")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(10, 5))
    plt.bar(
        ["P_min", "P_baseline", "P_max", "OPF ref", "OPF result", "OPF dispatch to mall"],
        [p_min_mw * 1000.0, p_base_mw * 1000.0, p_max_mw * 1000.0, p_reference_mw * 1000.0, p_opf_mw * 1000.0, p_updated_grid_kw])

    plt.ylabel("Mall grid power consumption [kW]")
    plt.title("Mall OPF Dispatch")
    plt.grid(axis="y")
    plt.tight_layout()
    plt.show()

    # Flexibility envelope plot
    window_start = selected_time - pd.Timedelta(hours=12)
    window_end = selected_time + pd.Timedelta(hours=12)
    plot_df = bounds_df.loc[window_start:window_end]

    plt.figure(figsize=(12, 6))
    plt.plot(plot_df.index, plot_df["p_mall_base_mw"] * 1000.0, label="Baseline Consumption")
    plt.plot(plot_df.index, plot_df["p_mall_min_mw"] * 1000.0, linestyle="--", label="P_min envelope")

    plt.plot(
        plot_df.index,
        plot_df["p_mall_max_mw"] * 1000.0,
        linestyle="--",
        label="P_max"
        )

    plt.scatter(
        [selected_time],
        [p_reference_mw * 1000.0],
        label="OPF reference",
        zorder=6
    )

    plt.scatter(
        [selected_time],
        [p_opf_mw * 1000.0],
        label="OPF result",
        zorder=7
    )

    plt.scatter(
        [selected_time],
        [p_updated_grid_kw],
        label="Updated pandaprosumer setpoint power",
        zorder=8
    )

    plt.axvline(
        selected_time,
        linestyle=":",
        label="Selected timestep",
    )

    plt.ylabel("Mall grid power consumption [kW]")
    plt.title("Mall Flexibility Envelope and OPF Dispatch")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


# 5. Main workflow
def main():

    # 1. pandaprosumer baseline and flexibility bounds
    res_base, bounds_df = run_mall_case_with_bounds(time_series_data_base=time_series_data, flex_target_kw=baseline_flex_target_kw,
                                                    residual_mall_load_kw=residual_mall_load_kw, start=start, end=end,
                                                    time_resolution=time_resolution, frequency=frequency,
                                                    collect_bounds=True, allow_export=True, verbose=False)

    # Use only downward flexibility
    valid_times = bounds_df[(bounds_df["feasible"] == True)
                            & (bounds_df["p_mall_base_mw"] > 0.02)
                            & (bounds_df["flex_down_mw"] > 0.005)].copy()

    if valid_times.empty:
        raise RuntimeError( "No timestep found with positive mall load and downward flexibility")

    selected_time = valid_times["flex_down_mw"].idxmax()
    selected_position = bounds_df.index.get_loc(selected_time)

    p_mall_min_mw = bounds_df.at[selected_time, "p_mall_min_mw"]
    p_mall_base_mw = bounds_df.at[selected_time, "p_mall_base_mw"]
    p_mall_max_mw = bounds_df.at[selected_time, "p_mall_max_mw"]

    #  keep mall reactive power fixed at zero
    q_mall_base_mvar = 0.0
    q_eps = 1e-6

    print("\nSelected OPF timestep")
    print(selected_time)
    print(f"P_min  = {p_mall_min_mw:.6f} MW")
    print(f"P_base = {p_mall_base_mw:.6f} MW")
    print(f"P_max  = {p_mall_max_mw:.6f} MW")
    print(f"Flex down = {bounds_df.at[selected_time, 'flex_down_mw']:.6f} MW")
    print(f"Flex up   = {bounds_df.at[selected_time, 'flex_up_mw']:.6f} MW")

    # 2. Build simple Schutterwald OPF case
    subnets = lv_schutterwald(separation_by_sub=True, include_heat_pumps=False)

    selected_case = None

    for subnet_id, net in enumerate(subnets):
        if len(net.ext_grid) == 0 or len(net.bus) <= 20:
            continue

        prepare_grid_for_opf(net)

        if not run_pf(net, context=f"subnet {subnet_id} initial PF"):
            continue

        # Select an LV bus that is not the ext grid bus
        ext_grid_buses = set(net.ext_grid.bus.values)

        lv_buses = net.bus.index[(net.bus.vn_kv <= 1.0) & (net.bus.in_service == True)
                                 & (~net.bus.index.isin(ext_grid_buses))]
        if len(lv_buses) == 0:
            continue

        # Choose a normal bus, not the weakest one
        lv_voltages = net.res_bus.loc[lv_buses, "vm_pu"].sort_values()
        bus_pos = int(0.30 * len(lv_voltages))
        bus_pos = min(max(bus_pos, 0), len(lv_voltages) - 1)
        mall_bus = lv_voltages.index[bus_pos]

        mall_load = pp.create_load(
            net,
            bus=mall_bus,
            p_mw=p_mall_base_mw,
            q_mvar=q_mall_base_mvar,
            name="Shopping Mall load",
            controllable=True,
            min_p_mw=p_mall_min_mw,
            max_p_mw=p_mall_max_mw,
            min_q_mvar=q_mall_base_mvar - q_eps,
            max_q_mvar=q_mall_base_mvar + q_eps
        )

        if not run_pf(net, context=f"subnet {subnet_id} with mall"):
            continue

        # 3. Baseline grid state with mall at P_base
        # check and report violation s in the subnet before an OPF is run
        v_before = net.res_bus.vm_pu.copy()

        has_violation_before, violations_before = check_grid_violations(net)

        if not has_violation_before:
            print("\nNo network violation detected in baseline state.")
            print("No flexibility activation required.")

            selected_case = {
                "net": net,
                "subnet_id": subnet_id,
                "subnet_name": net.name,
                "mall_bus": mall_bus,
                "mall_load": mall_load,
                "p_reference_mw": p_mall_base_mw,
                "p_mall_opf_mw": p_mall_base_mw,
                "q_mall_opf_mvar": q_mall_base_mvar,
                "v_before": v_before,
                "v_after": v_before,
                "violations_before": violations_before,
                "violations_after": violations_before,
                "flex_activation_required": False
            }

            break

        print("\nNetwork violation detected before OPF.")
        print(violations_before)

        # 4.  Run OPF only if a violation exists
        # Objective: minimum deviation from baseline, OPF to only compute active power setpoint of the load
        # TODO: check if a battery storage should also be added in the optimization controller to store surplus el. generation when O/P CHP increases
        p_mall_opf_mw = run_mall_opf_min_deviation(net=net, mall_load=mall_load, p_base_mw=p_mall_base_mw,)

        if p_mall_opf_mw is None:
            continue

        q_mall_opf_mvar = net.res_load.at[mall_load, "q_mvar"]

        net.load.at[mall_load, "p_mw"] = p_mall_opf_mw
        net.load.at[mall_load, "q_mvar"] = q_mall_opf_mvar

        if not run_pf(net, context=f"subnet {subnet_id} after OPF"):
            continue

        v_after = net.res_bus.vm_pu.copy()
        has_violation_after, violations_after = check_grid_violations(net)
        print("\nNetwork violations after OPF:")
        print(violations_after)

        if has_violation_after:
            print("OPF reduced the violation but some violations remain")
        else:
            print("All cvoltage/loading violations resolved after OPF.")

        selected_case = {
            "net": net,
            "subnet_id": subnet_id,
            "subnet_name": net.name,
            "mall_bus": mall_bus,
            "mall_load": mall_load,
            "p_reference_mw": p_mall_base_mw,
            "p_mall_opf_mw": p_mall_opf_mw,
            "q_mall_opf_mvar": q_mall_opf_mvar,
            "v_before": v_before,
            "v_after": v_after,
            "violations_before": violations_before,
            "violations_after": violations_after,
            "flex_activation_required": True,
        }

        break

    if selected_case is None:
        raise RuntimeError("No Schutterwald subnet produced a convergent OPF case.")

    net = selected_case["net"]
    p_reference_mw = selected_case["p_reference_mw"]
    # this is the opf calculated setpoint of Mall's active power
    p_mall_opf_mw = selected_case["p_mall_opf_mw"]
    q_mall_opf_mvar = selected_case["q_mall_opf_mvar"]
    v_before = selected_case["v_before"]
    v_after = selected_case["v_after"]

    print("\nSelected Schutterwald OPF case")
    print(f"Subnet id: {selected_case['subnet_id']}")
    print(f"Subnet name: {selected_case['subnet_name']}")
    print(f"Mall bus: {selected_case['mall_bus']}")

    print("\nGrid status")
    print(f"V_min before OPF = {v_before.min():.6f} pu")
    print(f"V_min after OPF  = {v_after.min():.6f} pu")
    print(f"V_max before OPF = {v_before.max():.6f} pu")
    print(f"V_max after OPF  = {v_after.max():.6f} pu")

    print("\nOPF mall result")
    print(f"P_min    = {p_mall_min_mw:.6f} MW")
    print(f"P_base   = {p_mall_base_mw:.6f} MW")
    print(f"P_max    = {p_mall_max_mw:.6f} MW")
    print(f"p_reference = {p_reference_mw:.6f} MW")
    print(f"P_OPF    = {p_mall_opf_mw:.6f} MW")
    print(f"Q_OPF    = {q_mall_opf_mvar:.6f} Mvar")

    if p_mall_min_mw < 0:
        print(f"Export allowed: mall can export up to {-p_mall_min_mw * 1000.0:.3f} kW")
    else:
        print("Export not available at this timestep.")

    print("\nActivated flexibility")
    print(f"Load-sign convention    = {p_mall_opf_mw - p_mall_base_mw:.6f} MW")
    print(f"Grid-support convention = {p_mall_base_mw - p_mall_opf_mw:.6f} MW")

    # 6. Send OPF setpoint back to pprosumer
    p_grid_setpoint_kw = p_mall_opf_mw * 1000.0
    residual_load_selected_kw = residual_mall_load_kw[selected_position]

    # P_grid = P_residual_mall - P_device
    # P_device = P_CHP - P_BHP
    p_device_setpoint_kw = residual_load_selected_kw - p_grid_setpoint_kw

    updated_flex_target_kw = baseline_flex_target_kw.copy()
    updated_flex_target_kw[selected_position] = p_device_setpoint_kw

    print("\nSending OPF setpoint back to PandaProsumer")
    print(f"Selected time: {selected_time}")
    print(f"Residual mall load P_el_sc - P_pv = {residual_load_selected_kw:.3f} kW")
    print(f"OPF grid power setpoint   = {p_grid_setpoint_kw:.3f} kW")
    print(f"Device target P_CHP-P_BHP = {p_device_setpoint_kw:.3f} kW")

    res_updated, _ = run_mall_case_with_bounds(
        time_series_data_base=time_series_data,
        flex_target_kw=updated_flex_target_kw,
        residual_mall_load_kw=residual_mall_load_kw,
        start=start,
        end=end,
        time_resolution=time_resolution,
        frequency=frequency,
        collect_bounds=False,
        allow_export=True,
        verbose=False,
    )

    p_updated_grid_kw = res_updated.at[selected_time, "p_grid_kw"]

    print("\nUpdated pandaprosumerresult at selected timestep")
    print(f"Baseline grid consumption = {p_mall_base_mw * 1000.0:.3f} kW")
    print(f"OPF target                = {p_reference_mw * 1000.0:.3f} kW")
    print(f"OPF setpoint              = {p_grid_setpoint_kw:.3f} kW")
    print(f"Updated pandaprosumer    = {p_updated_grid_kw:.3f} kW")
    print(f"Tracking error            = {p_updated_grid_kw - p_grid_setpoint_kw:.3f} kW")


    plot_results(
        v_before=v_before,
        v_after=v_after,
        bounds_df=bounds_df,
        selected_time=selected_time,
        p_min_mw=p_mall_min_mw,
        p_base_mw=p_mall_base_mw,
        p_max_mw=p_mall_max_mw,
        p_reference_mw=p_reference_mw,
        p_opf_mw=p_mall_opf_mw,
        p_updated_grid_kw=p_updated_grid_kw,
    )


if __name__ == "__main__":
    main()