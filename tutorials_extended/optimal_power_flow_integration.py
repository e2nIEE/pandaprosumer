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

# Synthetic high-PV scenario for overvoltage test
# PV_SCALE = 1.0 → import violation tests
# PV_SCALE > 1.0 (e.g. 12.0) → overvoltage / export absorption test
PV_SCALE = 1.0
p_pv_used_kw = p_pv_kw * PV_SCALE
residual_mall_load_kw = p_el_sc_kw - p_pv_used_kw

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
                                                      for i in range(2, 6)] ## if we add other controllers or change the index of controller then do we need to change the index here as well?

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
v_max_pu_std = 1.10  # # reduced to 1.05 for overvoltage stress-test scenario 
loading_percent_max_std = 150.0

# Which violation type to stress-test this run
TARGET_VIOLATION = "undervoltage"  # "undervoltage" | "line_overload" | "trafo_overload" | "overvoltage"


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


def find_bus_for_stress(net, candidate_buses, p_mw, element="voltage",shortlist_size=50, use_sensitivity_prefilter=True):
    """
    Find the bus in `candidate_buses` that causes the worst voltage/loading
    stress in the subnet when the mall load/sgen is placed there.

    This is intentional: the study aims to observe the prosumer's demand side
    flexibility (CHP/BHP/storage dispatch via pandaprosumer optimization)
    under a genuinely stressed grid condition, not an easy one. A weakly
    stressed bus wouldn't exercise the flexibility envelope at all.

    Two stage search for performance on large networks (e.g. Schutterwald,
    hundreds of buses):
      1. Cheap linear sensitivity estimate (Z-bus self sensitivity for
         voltage stress, PTDF for line/trafo loading) from the base case
         power flow, scoring ALL candidate buses almost for free.
      2. Full/exact AC power flow probing (brute force method), restricted
         to the top `shortlist_size` candidates from step 1.

    A larger `shortlist_size` trades runtime for accuracy. Setting
    `use_sensitivity_prefilter=False` reproduces the original brute force
    behavior over all buses exactly useful for validating that the
    shortlist isn't dropping the true worst bus on a specific network.
    """
    
    
    
    def _full_pf_ranking(buses_to_probe):
        results = []
        for bus in buses_to_probe:
            if p_mw >= 0:
                temp_element = pp.create_load(net, bus=bus, p_mw=p_mw, q_mvar=0.0,name="__probe__", controllable=False)
            else:
                temp_element = pp.create_sgen(net, bus=bus, p_mw=abs(p_mw), q_mvar=0.0,name="__probe__", controllable=False)

            ok = run_pf(net, context=f"probe bus {bus} ({element})")

            if not ok:
                metric = np.nan
            elif element == "voltage":
                metric = net.res_bus["vm_pu"].min()
            elif element == "voltage_high":
                metric = net.res_bus["vm_pu"].max()
            elif element == "line":
                metric = net.res_line["loading_percent"].max() if len(net.line) else np.nan
            elif element == "trafo":
                metric = net.res_trafo["loading_percent"].max() if len(net.trafo) else np.nan
            else:
                raise ValueError(f"Unknown element type: {element}")

            results.append((bus, metric))

            if p_mw >= 0:
                net.load.drop(temp_element, inplace=True)
            else:
                net.sgen.drop(temp_element, inplace=True)

        reverse = element in ("line", "trafo", "voltage_high")
        results.sort(key=lambda x: (np.isnan(x[1]),(-x[1] if reverse else x[1]) if not np.isnan(x[1]) else 0))
        return results

    candidate_buses = list(candidate_buses)

    if not use_sensitivity_prefilter or len(candidate_buses) <= shortlist_size:
        # Not worth pre-filtering a small candidate set
        return _full_pf_ranking(candidate_buses)

    try:
        # base case must already be solved (it is, by the time this is called)
        if not net["converged"]:
            run_pf(net, context="base case for sensitivity build")

        shortlist = _sensitivity_shortlist(net, candidate_buses, p_mw, element, shortlist_size)

    except Exception as exc:
        print(f"\nSensitivity pre-filter failed, falling back to full PF over all candidates.")
        print(f"Reason: {exc}")
        return _full_pf_ranking(candidate_buses)

    # Exact PF on the shortlist only : this IS your final answer, not an approximation
    return _full_pf_ranking(shortlist)


def _sensitivity_shortlist(net, candidate_buses, p_mw, element, shortlist_size):
    """
    Linear sensitivity ranking used ONLY to pick which buses deserve a
    full PF probe. Not returned to the caller as the final metric.
    """
    bus_lookup = net["_pd2ppc_lookups"]["bus"]

    if element in ("voltage", "voltage_high"):
        import scipy.sparse.linalg as spla
        # Use Z-bus self-sensitivity to estimate voltage impact of a load/sgen at each bus:
        ppc = net["_ppc"]
        Ybus = ppc["internal"]["Ybus"].tocsc()
        V = ppc["internal"]["V"]
        n = Ybus.shape[0]
        
        lu = spla.splu(Ybus)
        Vmag = np.abs(V)

        scores = []
        for bus in candidate_buses:
            idx = bus_lookup[bus]
            e = np.zeros(n, dtype=complex)
            e[idx] = 1.0
            z_col = lu.solve(e)                  # column of Z-bus, one solve per bus
            dV = (z_col[idx].real / Vmag[idx]) * p_mw   # self-sensitivity estimate
            scores.append((bus, dV))

        # overvoltage probing uses negative p_mw (export) -> want most POSITIVE dV
        # undervoltage probing uses positive p_mw (import) -> want most NEGATIVE dV
        reverse = element == "voltage_high"
        scores.sort(key=lambda x: -x[1] if reverse else x[1])

    elif element in ("line", "trafo"):
        from pandapower.pypower.makePTDF import makePTDF
        ppc = net["_ppc"]
        ppci = net["_ppc"]["internal"]
        PTDF = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"])

        scores = []
        for bus in candidate_buses:
            idx = bus_lookup[bus]
            col = PTDF[:, idx]
            worst_branch_shift = np.max(np.abs(col)) * abs(p_mw)
            scores.append((bus, worst_branch_shift))

        scores.sort(key=lambda x: -x[1])  # most branch impact first

    else:
        raise ValueError(f"No sensitivity method implemented for element='{element}'")

    return [bus for bus, _ in scores[:shortlist_size]]


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


# trying to make the plots better   : 19.08.2026

import matplotlib.dates as mdates

def plot_results(
    v_before,
    v_after,
    bounds_df,
    selected_time,
    p_min_mw,
    p_base_mw,
    p_max_mw,
    p_reference_mw,
    p_opf_mw,
    p_updated_grid_kw,
    v_min_pu_std,
    v_max_pu_std,
    save=True,
    show=False,
    mall_bus=True,
    res_updated=True,
    res_base=None,
    results_df=None,
):
    """
    Publication quality IEEE style plots for the OPF and flexibility demo.

    Parameters
    
    v_before, v_after : pd.Series
        Bus voltages before and after OPF (index = bus).
    bounds_df : pd.DataFrame
        Flexibility envelope with columns:
        'p_mall_min_mw', 'p_mall_base_mw', 'p_mall_max_mw'.
    selected_time : pd.Timestamp
        Timestep selected for detailed analysis.
    p_min_mw, p_base_mw, p_max_mw : float
        Flexibility envelope at selected_time (MW).
    p_reference_mw : float
        Baseline grid power (MW) at selected_time.
    p_opf_mw : float
        OPF result (MW) at selected_time.
    p_updated_grid_kw : float
        Actual prosumer grid power after re-run (kW).
    v_min_pu_std, v_max_pu_std : float
        Voltage limits (pu).
    save : bool, default True
        Save figures to PDF and PNG.
    show : bool, default False
        Show figures interactively.
    mall_bus : int, optional
        Bus index to highlight in voltage profile.
    res_updated : pd.DataFrame, optional
        Prosumer time-series results after applying OPF setpoint.
        Must contain: 'chp_p_el_kw', 'bhp_p_el_kw', 'soc_percent',
                      'p_grid_kw', 'q_delivered_storage_kw'.
    res_base : pd.DataFrame, optional
        Prosumer time-series results for baseline (no flexibility).
        Same columns as res_updated.
    results_df : pd.DataFrame, optional
        All-timestep OPF results. Must have a DatetimeIndex and columns
        'p_base_mw', 'p_opf_mw', 'flex_activated_mw', etc.
    """

    # Reset to defaults and apply IEEE style rcParams
    plt.rcdefaults()
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["STIXGeneral"],
        "mathtext.fontset": "stix",
        "font.size": 8,
        "axes.labelsize": 9,
        "axes.titlesize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 7.5,
        "axes.linewidth": 0.6,
        "lines.linewidth": 0.9,
        "lines.markersize": 4,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "xtick.minor.size": 1.5,
        "ytick.minor.size": 1.5,
        "xtick.top": True,
        "ytick.right": True,
        "axes.grid": True,
        "grid.color": "0.85",
        "grid.linestyle": "--",
        "grid.linewidth": 0.4,
        "axes.axisbelow": True,
        "legend.frameon": False,
        "legend.scatterpoints": 1,
        "legend.numpoints": 1,
        "figure.dpi": 150,
        "savefig.dpi": 600,
        "savefig.bbox": "tight",
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })

    blue, red, yellow, purple, green, black = (
        "#0072BD", "#D95319", "#EDB120", "#7E2F8E", "#77AC30", "#000000",
    )
    #single_col_in = 3.5
    #double_col_in = 7.16

    FIG_WIDTH_IN = 6.5

    # Plot 1 Voltage profile with optional mall bus highlight

    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 2.6))
    sorted_buses = v_before.sort_values().index
    x = range(len(sorted_buses))

    ax.plot(x, v_before.loc[sorted_buses].values,
            color=blue, linewidth=1.0, label="Before OPF")
    ax.plot(x, v_after.loc[sorted_buses].values,
            color=red, linestyle="--", linewidth=1.0, label="After OPF")
    ax.axhline(v_min_pu_std, color=purple, linestyle=":", linewidth=0.8,
               label=fr"$V_{{\mathrm{{min}}}}$ = {v_min_pu_std:.2f} pu")
    ax.axhline(v_max_pu_std, color=green, linestyle=":", linewidth=0.8,
               label=fr"$V_{{\mathrm{{max}}}}$ = {v_max_pu_std:.2f} pu")

    if mall_bus is not None and mall_bus in sorted_buses:
        mall_rank = list(sorted_buses).index(mall_bus)
        ax.scatter([mall_rank], [v_before.loc[mall_bus]],
                   color=red, marker='o', s=25, zorder=6,
                   label='Selected mall bus')
        ax.annotate(f'Bus {mall_bus}',
                    xy=(mall_rank, v_before.loc[mall_bus]),
                    xytext=(mall_rank - 5, v_before.loc[mall_bus] + 0.02),
                    arrowprops=dict(arrowstyle='->', lw=0.8))

    y_min = min(v_before.min(), v_after.min(), v_min_pu_std) - 0.02
    y_max = max(v_before.max(), v_after.max(), v_max_pu_std) + 0.02
    ax.set_ylim(y_min, y_max)
    ax.set_xlim(0, len(sorted_buses) - 1)
    ax.set_xlabel("Buses sorted by voltage before OPF")
    ax.set_ylabel("Voltage [pu]")
    ax.legend(loc="upper left", handlelength=2.5)
    fig.tight_layout()
    if save:
        fig.savefig("voltage_profile.pdf")
        fig.savefig("voltage_profile.png")
    if show:
        plt.show()
    else:
        plt.close(fig)

    # 
    # Plot 2 Bar chart comparing envelope and dispatch results
    # 
    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 2.4))
    categories = [r"$P_{\mathrm{min}}$", r"$P_{\mathrm{base}}$", r"$P_{\mathrm{max}}$",
                  "OPF ref", "OPF result", "Prosumer"]
    values = [p_min_mw * 1000.0, p_base_mw * 1000.0, p_max_mw * 1000.0,
              p_reference_mw * 1000.0, p_opf_mw * 1000.0, p_updated_grid_kw]
    colors = ['#D95319' if v < 0 else '#0072BD' for v in values]

    bars = ax.bar(categories, values, color=colors, edgecolor=black,
                  linewidth=0.6, width=0.6)
    ax.axhline(0, color=black, linewidth=0.8)
    ax.set_ylabel("Mall grid power [kW]")
    ax.grid(True, axis="y")

    for bar, val in zip(bars, values):
        offset = 1 if val >= 0 else -1
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                f'{val:.1f}', ha='center', va='bottom' if val >= 0 else 'top',
                fontsize=7)

    fig.tight_layout()
    if save:
        fig.savefig("mall_opf_dispatch.pdf")
        fig.savefig("mall_opf_dispatch.png")
    if show:
        plt.show()
    else:
        plt.close(fig)

    # 
    # Plot 3: Flexibility envelope with shaded range
    # 
    window_start = selected_time - pd.Timedelta(hours=12)
    window_end = selected_time + pd.Timedelta(hours=12)
    plot_df = bounds_df.loc[window_start:window_end]

    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 2.8))
    ax.fill_between(plot_df.index,
                    plot_df["p_mall_min_mw"] * 1000.0,
                    plot_df["p_mall_max_mw"] * 1000.0,
                    color='gray', alpha=0.2, label='Flexibility range')
    ax.plot(plot_df.index, plot_df["p_mall_base_mw"] * 1000.0,
            color=blue, linewidth=1.0, label="Baseline consumption")
    ax.plot(plot_df.index, plot_df["p_mall_min_mw"] * 1000.0,
            color=red, linestyle="--", linewidth=0.9, label=r"$P_{\mathrm{min}}$ envelope")
    ax.plot(plot_df.index, plot_df["p_mall_max_mw"] * 1000.0,
            color=purple, linestyle="--", linewidth=0.9, label=r"$P_{\mathrm{max}}$ envelope")

    ax.scatter([selected_time], [p_reference_mw * 1000.0], color=green, marker="o",
               s=30, edgecolors=black, linewidths=0.6, label="OPF reference", zorder=6)
    ax.scatter([selected_time], [p_opf_mw * 1000.0], color=red, marker="s",
               s=30, edgecolors=black, linewidths=0.6, label="OPF result", zorder=7)
    ax.scatter([selected_time], [p_updated_grid_kw], color=yellow, marker="^",
               s=35, edgecolors=black, linewidths=0.6,
               label="Updated pandaprosumer setpoint", zorder=8)
    ax.axvline(selected_time, color=black, linestyle=":", linewidth=0.8,
               label="Selected timestep")

    ax.set_ylabel("Mall grid power [kW]")
    ax.legend(loc="upper right", handlelength=2.5)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.tight_layout()
    if save:
        fig.savefig("flexibility_envelope.pdf")
        fig.savefig("flexibility_envelope.png")
    if show:
        plt.show()
    else:
        plt.close(fig)

    # 
    # Plot 4: Prosumer internal dispatch (baseline vs updated)
    # 
    if res_updated is not None and not res_updated.empty:
        # Determine time window around selected_time
        window_start = selected_time - pd.Timedelta(hours=12)
        window_end = selected_time + pd.Timedelta(hours=12)

        upd = res_updated.loc[window_start:window_end]
        base = None
        if res_base is not None and not res_base.empty:
            base = res_base.loc[window_start:window_end]

        fig, axes = plt.subplots(2, 2, figsize=(FIG_WIDTH_IN, 5.2), sharex=True)
        ax_grid, ax_elec, ax_soc, ax_flex = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

        #  Panel (0,0): Mall grid power 
        if base is not None:
            ax_grid.plot(base.index, base["p_grid_kw"], color=blue,
                         linewidth=1.0, label="Baseline grid power")
        ax_grid.plot(upd.index, upd["p_grid_kw"], color=red,
                     linestyle="--", linewidth=1.0, label="After OPF")
        ax_grid.axvline(selected_time, color=black, linestyle=":", linewidth=0.8)
        ax_grid.scatter([selected_time], [p_updated_grid_kw], color=yellow,
                        marker="^", s=35, edgecolors=black, linewidths=0.6,
                        label="Actual setpoint", zorder=6)
        ax_grid.set_ylabel("Grid power [kW]")
        ax_grid.legend(loc="upper right")
        ax_grid.grid(True)
 
        #  Panel (0,1): CHP and BHP electrical power 
        if base is not None:
            ax_elec.plot(base.index, base["chp_p_el_kw"], color=blue,
                         linewidth=1.0, label="CHP baseline")
            ax_elec.plot(base.index, base["bhp_p_el_kw"], color=red,
                         linewidth=1.0, label="BHP baseline")
        ax_elec.plot(upd.index, upd["chp_p_el_kw"], color=blue,
                     linestyle="--", linewidth=1.0, label="CHP updated")
        ax_elec.plot(upd.index, upd["bhp_p_el_kw"], color=red,
                     linestyle="--", linewidth=1.0, label="BHP updated")
        ax_elec.axvline(selected_time, color=black, linestyle=":", linewidth=0.8)
        ax_elec.set_ylabel("Electrical power [kW]")
        ax_elec.legend(loc="upper right")
        ax_elec.grid(True)
 
        #  Panel (1,0): Storage SOC 
        if base is not None:
            ax_soc.plot(base.index, base["soc_percent"], color=purple,
                        linewidth=1.0, label="SOC baseline")
        ax_soc.plot(upd.index, upd["soc_percent"], color=purple,
                    linestyle="--", linewidth=1.0, label="SOC updated")
        ax_soc.axvline(selected_time, color=black, linestyle=":", linewidth=0.8)
        ax_soc.set_ylabel("Storage SOC [%]")
        ax_soc.legend(loc="upper right")
        ax_soc.grid(True)
 
        # Panel (1,1): Flexibility envelope 
        bnd = bounds_df.loc[window_start:window_end]
        ax_flex.fill_between(bnd.index,
                             bnd["p_mall_min_mw"] * 1000,
                             bnd["p_mall_max_mw"] * 1000,
                             color='gray', alpha=0.2,
                             label='Flexibility range')
        ax_flex.plot(bnd.index, bnd["p_mall_base_mw"] * 1000,
                     color=blue, linewidth=1.0, label="Baseline")
        ax_flex.axvline(selected_time, color=black, linestyle=":", linewidth=0.8)
        ax_flex.set_ylabel("Mall grid power [kW]")
        ax_flex.legend(loc="upper right")
        ax_flex.grid(True)
 
        # Only bottom row gets date-formatted x-axis tick labels;
        # top row keeps gridlines but hides tick labels to avoid clutter.
        for ax in (ax_soc, ax_flex):
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        for ax in (ax_grid, ax_elec):
            ax.tick_params(labelbottom=False)
 
        fig.tight_layout()
        if save:
            fig.savefig("prosumer_response.pdf")
            fig.savefig("prosumer_response.png")
        if show:
            plt.show()
        else:
            plt.close(fig)

    # 
    # Plot 5: All-timestep overview (if results_df provided) : 
    # currently only supports a single snapshot; multi-timestep support not yet implemented 

# 5. Main workflow
def main():

    # 1. pandaprosumer baseline and flexibility bounds
    res_base, bounds_df = run_mall_case_with_bounds(time_series_data_base=time_series_data, flex_target_kw=baseline_flex_target_kw,
                                                    residual_mall_load_kw=residual_mall_load_kw, start=start, end=end,
                                                    time_resolution=time_resolution, frequency=frequency,
                                                    collect_bounds=True, allow_export=True, verbose=False)
    
    if TARGET_VIOLATION == "overvoltage":
        valid_times = bounds_df[(bounds_df["feasible"] == True)
                                & (bounds_df["p_mall_base_mw"] < -0.02)
                                & (bounds_df["flex_up_mw"] > 0.005)].copy()

        if valid_times.empty:
            raise RuntimeError("No timestep found with mall export and upward flexibility")

        selected_time = valid_times["flex_up_mw"].idxmax()
        selected_position = bounds_df.index.get_loc(selected_time)

    else:
        valid_times = bounds_df[(bounds_df["feasible"] == True)
                                & (bounds_df["p_mall_base_mw"] > 0.02)
                                & (bounds_df["flex_down_mw"] > 0.005)].copy()

        if valid_times.empty:
            raise RuntimeError("No timestep found with positive mall load and downward flexibility")

        selected_time = valid_times["flex_down_mw"].idxmax()
        selected_position = bounds_df.index.get_loc(selected_time)
    
    p_mall_min_mw = bounds_df.at[selected_time, "p_mall_min_mw"]
    p_mall_base_mw = bounds_df.at[selected_time, "p_mall_base_mw"]
    p_mall_max_mw = bounds_df.at[selected_time, "p_mall_max_mw"]

    #  keep mall reactive power fixed at zero
    # if in future we want to allow reactive power flexibility, we can add it here
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

        if TARGET_VIOLATION == "overvoltage":
            element = "voltage_high"
            probe_p_mw = -abs(p_mall_base_mw)  # export injection
        else:
            element = {
                "undervoltage": "voltage",
                "line_overload": "line",
                "trafo_overload": "trafo",
            }[TARGET_VIOLATION]
            probe_p_mw = p_mall_base_mw

        stress_ranking = find_bus_for_stress(
            net,
            lv_buses,
            p_mw=probe_p_mw,
            element=element,
        )

        if np.isnan(stress_ranking[0][1]):
            continue  # nothing usable in this subnet for this metric (e.g. no trafos)

        unit = "pu" if element == "voltage" else "%"
        print(f"\nTop 5 buses in subnet {subnet_id} by {element} stress:")
        for bus, metric in stress_ranking[:5]:
            print(f"  bus {bus}: {metric:.3f} {unit}")

        mall_bus = stress_ranking[0][0]

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
    print("\nProsumer internal response to OPF setpoint")
    print(f"CHP electrical output = {res_updated.at[selected_time, 'chp_p_el_kw']:.3f} kW")
    print(f"BHP electrical input  = {res_updated.at[selected_time, 'bhp_p_el_kw']:.3f} kW")
    print(f"Net P_device          = {res_updated.at[selected_time, 'p_device_kw']:.3f} kW")
    print(f"Thermal storage SOC   = {res_updated.at[selected_time, 'soc_percent']:.1f} %")
    print(f"Heat demand delivered = {res_updated.at[selected_time, 'q_delivered_storage_kw']:.3f} kW")

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
        v_min_pu_std=v_min_pu_std,
        v_max_pu_std=v_max_pu_std,
        mall_bus=selected_case["mall_bus"],          # from selected_case
        res_updated=res_updated,                     # from the prosumer re-run
        res_base=res_base,                       # optional, if you have baseline prosumer results
        #results_df=results_df,                   # optional, if you ran all-timestep OPF
    )


if __name__ == "__main__":
    main()