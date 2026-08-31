from pathlib import Path
import copy

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
# Shopping center uncontrolled consumption - local PV generation
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
# included previous controller results and counter for CHP downtime
def build_mall_prosumer(time_series_data_base, flex_target_kw, start,
                        end, time_resolution, frequency, collect_bounds=False, init_soc=0.0,
                        previous_controller_results=None, previous_chp_downtime=None, tz="utc"):

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
    # storage at t+1 starts from the last attained SOC at t
    heat_storage_index = create_controlled_heat_storage(prosumer, q_capacity_kwh, init_soc=init_soc, level=2, order=2)

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
    # optimization and storage controller obtains the output from previous timestep
    # previous storage SOC and CHP el output, |CHP out (t-1) - CHP out
    if previous_controller_results is not None:
        prosumer.controller_results = copy.deepcopy(previous_controller_results)

    if previous_chp_downtime is not None:
        optimization_controller._chp_downtime = copy.deepcopy(previous_chp_downtime)

    return prosumer, period, optimization_controller


# 3. pprosumer run with controller-based bounds
# new i/p parameters added: init_soc, prev controller results, previous CHP downtime, return state
def run_mall_case_with_bounds(time_series_data_base, flex_target_kw, residual_mall_load_kw,
                              start, end, time_resolution, frequency, collect_bounds=False,
                              allow_export=False, init_soc=0.0, previous_controller_results=None,
                              previous_chp_downtime=None, return_state=False, verbose=False):

    prosumer, period, optimization_controller = build_mall_prosumer(time_series_data_base=time_series_data_base, flex_target_kw=flex_target_kw,
                                                                    start=start, end=end, time_resolution=time_resolution,
                                                                    frequency=frequency, collect_bounds=collect_bounds, init_soc=init_soc,
                                                                    previous_controller_results=previous_controller_results,
                                                                    previous_chp_downtime=previous_chp_downtime)

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
    # SOC at t-1 from prosumer.controller_results and CHP downtime from optim controller dependent to prev timestep
    state = {"controller_results": copy.deepcopy(getattr(prosumer, "controller_results", {})),
             "chp_downtime": copy.deepcopy(getattr(optimization_controller, "_chp_downtime", {}))}

    if not collect_bounds:
        if return_state:
            return res_df, None, state
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

    if return_state:
        return res_df, bounds_df, state

    return res_df, bounds_df

# 4. pandapower OPF integration
v_min_pu_std= 0.90
v_max_pu_std = 1.10
loading_percent_max_std = 100.0

# True = mall can reduce import below zero, i.e. export through CHP surplus
# False = mall can only reduce grid import down to 0 kW
allow_export_to_grid = True

def get_schutterwald_subnets():
    """
    Return Schutterwald as separated LV subnets.
    """

    subnets = lv_schutterwald(separation_by_sub=True, include_heat_pumps=False)

    return subnets


def get_single_schutterwald_subnet(subnet_id):
    """
    Return one selected Schutterwald subnet.
    """

    subnets = get_schutterwald_subnets()

    if subnet_id >= len(subnets):
        raise RuntimeError(f"Subnet id {subnet_id} does not exist and Available subnets: {len(subnets)}")

    return subnets[subnet_id]


def run_pf(net, context="", print_error=True):
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
    Prepare the selected Schutterwald subnet for the OPF test.
    Existing grid loads and sgens are fixed
    Only the shopping-mall load is controllable
    """

    if len(net.load):
        net.load["controllable"] = False

    if len(net.sgen):
        net.sgen["controllable"] = False

    net.bus["min_vm_pu"] = v_min_pu_std
    net.bus["max_vm_pu"] = v_max_pu_std

    if len(net.line):
        net.line["max_loading_percent"] = loading_percent_max_std

    if len(net.trafo):
        net.trafo["max_loading_percent"] = loading_percent_max_std

    net.ext_grid["min_p_mw"] = -10.0
    net.ext_grid["max_p_mw"] = 10.0
    net.ext_grid["min_q_mvar"] = -10.0
    net.ext_grid["max_q_mvar"] = 10.0


def create_mall_load(net, mall_bus, p_mw, p_min_mw, p_max_mw, q_mvar, q_eps):
    """
    Create one controllable shopping-mall load in the selected subnet
    """
    mall_load = pp.create_load(net, bus=mall_bus,
                               p_mw=p_mw, q_mvar=q_mvar,
                               name="Shopping Mall load", controllable=True,
                               min_p_mw=p_min_mw, max_p_mw=p_max_mw,
                               min_q_mvar=q_mvar - q_eps, max_q_mvar=q_mvar + q_eps)
    return mall_load


def run_mall_opf(net, mall_load, p_base_mw, print_error=True):
    """
    Run OPF with one controllable mall load.

    Objective:
        min (P_mall - P_base)^2

        Use as minimal flexibility activation as possible while satisfying voltage and loading constraints.
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

def build_opf_results(selected_time, subnet_id, mall_bus, status,
                         flex_activation_required, p_mall_min_mw, p_mall_base_mw,
                         p_mall_max_mw, p_reference_mw, p_mall_opf_mw,
                         q_mall_opf_mvar, p_grid_setpoint_kw, p_device_setpoint_kw,
                         v_before=None, v_after=None, violations_before=None,
                         violations_after=None):

    if violations_before is None:
        violations_before = {"undervoltage": [], "overvoltage": [], "line_overload": [], "trafo_overload": []}

    if violations_after is None:
        violations_after = {"undervoltage": [], "overvoltage": [], "line_overload": [], "trafo_overload": []}

    if v_before is None:
        v_min_before = np.nan
        v_max_before = np.nan
    else:
        v_min_before = v_before.min()
        v_max_before = v_before.max()

    if v_after is None:
        v_min_after = np.nan
        v_max_after = np.nan
    else:
        v_min_after = v_after.min()
        v_max_after = v_after.max()

    if pd.isna(p_mall_opf_mw):
        grid_support_kw = 0.0
    else:
        grid_support_kw = (p_mall_base_mw - p_mall_opf_mw) * 1000.0

    row = {"time": selected_time,
           "subnet_id": subnet_id,
           "mall_bus": mall_bus,
           "status": status,
           "flex_activation_required": flex_activation_required,
           "p_min_mw": p_mall_min_mw,
           "p_base_mw": p_mall_base_mw,
           "p_max_mw": p_mall_max_mw,
           "p_reference_mw": p_reference_mw,
           "p_opf_mw": p_mall_opf_mw,
           "q_opf_mvar": q_mall_opf_mvar,
           "p_grid_setpoint_kw": p_grid_setpoint_kw,
           "p_device_setpoint_kw": p_device_setpoint_kw,
           "grid_support_kw": grid_support_kw,
           "v_min_before_pu": v_min_before,
           "v_min_after_pu": v_min_after,
           "v_max_before_pu": v_max_before,
           "v_max_after_pu": v_max_after,
           "n_undervoltage_before": len(violations_before["undervoltage"]),
           "n_undervoltage_after": len(violations_after["undervoltage"]),
           "n_overvoltage_before": len(violations_before["overvoltage"]),
           "n_overvoltage_after": len(violations_after["overvoltage"]),
           "n_line_overload_before": len(violations_before["line_overload"]),
           "n_line_overload_after": len(violations_after["line_overload"]),
           "n_trafo_overload_before": len(violations_before["trafo_overload"]),
           "n_trafo_overload_after": len(violations_after["trafo_overload"])}

    return row


def run_opf_timeseries_for_subnet(fixed_subnet_id, fixed_mall_bus, time_series_data_base,
                                  residual_mall_load_kw, q_mall_base_mvar, q_eps,
                                  initial_soc=0.0):
    """
    Run the OPF time series for one net with a shopping mall bus
    The actual state x_t is used to calculate the baseline and
    flexibility envelope at timestep t
    The resultant updated state x_(t+1) is then used for the next iteration
    """

    updated_flex_target_kw = np.zeros(len(time_series_data_base))
    opf_rows = []
    res_base_rows = []
    # updated power after pandaprosumer run
    res_actual_rows = []
    # flex envelope at each timestep
    flex_bounds_rows = []
    # initialization of state variables at the beginning of the loop
    # x|(t) = {SOC[(t), Pchp |(t-1), CHP state, CHP downtime}
    # at t=0, SOC=init_soc
    # from previous controller_results, retrieve SOC and Pchp at t-1
    soc_current = initial_soc
    prev_controller_results = {}
    prev_chp_downtime = {}
    # for timestep t, calculate baseline with no grid-side flex request
    # idx of timestep
    for selected_time_idx, selected_time in enumerate(time_series_data_base.index):

        # 1. Current timestep inputs
        time_series_t = time_series_data_base.iloc[[selected_time_idx]].copy()
        residual_t_kw = np.asarray([residual_mall_load_kw[selected_time_idx]])
        baseline_target_t_kw = np.array([0.0])

        start_t = selected_time.strftime("%Y-%m-%d %H:%M:%S")
        end_t = start_t

        # 2. Baseline and flexibility envelope from the current state x_t with the currest SOC and previous CHP output power
        # state_base_t has the SOC after the baseline has been tracked at the end of this timestep
        res_base_t, bounds_t, state_base_t = run_mall_case_with_bounds(
            time_series_data_base=time_series_t,
            flex_target_kw=baseline_target_t_kw,
            residual_mall_load_kw=residual_t_kw,
            start=start_t, end=end_t,
            time_resolution=time_resolution,
            frequency=frequency,
            collect_bounds=True,
            allow_export=allow_export_to_grid,
            init_soc=soc_current,
            previous_controller_results=prev_controller_results,
            previous_chp_downtime=prev_chp_downtime,
            return_state=True,
            verbose=False)

        res_base_t = res_base_t.iloc[[0]].copy()
        bounds_t = bounds_t.iloc[[0]].copy()

        res_base_rows.append(res_base_t.iloc[0])
        flex_bounds_rows.append(bounds_t.iloc[0])

        p_mall_base_mw = res_base_t.iloc[0]["p_grid_kw"] / 1000.0
        bounds_feasible = bool(bounds_t.iloc[0]["feasible"])
        # if pandaprosumer had a successful run
        if bounds_feasible:
            p_mall_min_mw = bounds_t.iloc[0]["p_mall_min_mw"]
            p_mall_max_mw = bounds_t.iloc[0]["p_mall_max_mw"]
        # if not, then no flex envelope is calculated
        else:
            p_mall_min_mw = p_mall_base_mw
            p_mall_max_mw = p_mall_base_mw
        # default is the baseline with no flex required and mall opf = mall's baseline power
        p_grid_setpoint_kw = p_mall_base_mw * 1000.0
        p_device_setpoint_kw = 0.0
        p_mall_opf_mw = p_mall_base_mw
        q_mall_opf_mvar = q_mall_base_mvar

        # Baseline action is the default actual action until a violation requires flex to mitigate it
        res_actual_t = res_base_t
        state_actual_t = state_base_t
        # TODO: change grid here
        # 3. use baseline mall load into the electrical grid and run PF
        net = get_single_schutterwald_subnet(fixed_subnet_id)
        prepare_grid_for_opf(net)

        if fixed_mall_bus not in net.bus.index:
            raise RuntimeError(f"Selected mall bus {fixed_mall_bus} is not in subnet {fixed_subnet_id}.")

        mall_load = create_mall_load(net=net,
                                     mall_bus=fixed_mall_bus,
                                     p_mw=p_mall_base_mw,
                                     p_min_mw=p_mall_min_mw,
                                     p_max_mw=p_mall_max_mw,
                                     q_mvar=q_mall_base_mvar,
                                     q_eps=q_eps)

        if not run_pf(net, context=f"subnet {fixed_subnet_id} with mall at {selected_time}", print_error=False):
            status = "pf_with_mall_failed"
            flex_activation_required = False
            v_before = None
            violations_before = None
            v_after = None
            violations_after = None
        # if pf converges, 2 possibilities exist : violation or no violations in the grid
        else:
            v_before = net.res_bus.vm_pu.copy()
            has_violation_before, violations_before = check_grid_violations(net)

            # 4. No violation -> no flex activation and use baseline only
            if not has_violation_before:
                status = "no_violation_no_flex_needed"
                flex_activation_required = False
                v_after = v_before
                violations_after = violations_before
            # case: violations exist but mall cannot provide a flex envelope, violations remain
            elif not bounds_feasible:
                status = "flex_bounds_infeasible"
                flex_activation_required = True
                v_after = v_before
                violations_after = violations_before
            else:
                # 5. Case:Violation + flex envelope exist -> OPF with the flex envelope calculated from x_t
                flex_activation_required = True
                p_mall_opf_mw = run_mall_opf(net=net,
                                              mall_load=mall_load,
                                              p_base_mw=p_mall_base_mw,
                                              print_error=False)

                opf_failed = p_mall_opf_mw is None

                if opf_failed:
                    # Corrective fallback:
                    # Under-voltage or overload -> minimum mall demand first
                    # over-voltage -> maximum mall demand first
                    pure_overvoltage = (len(violations_before["overvoltage"]) > 0 and
                                        len(violations_before["undervoltage"]) == 0 and
                                        len(violations_before["line_overload"]) == 0 and
                                        len(violations_before["trafo_overload"]) == 0)
                    #TODO: implement fallback for mixed violations such as undervoltage + overloaded line based on the extent of the existing violation
                    if pure_overvoltage:
                        fallback_candidates = [p_mall_max_mw, p_mall_min_mw]
                    else:
                        fallback_candidates = [p_mall_min_mw, p_mall_max_mw]

                    best_score = np.inf
                    best_p_mw = fallback_candidates[0]
                   # evaluate the grid with mall operating around flex envelope bounds
                    for p_candidate_mw in fallback_candidates:
                        net.load.at[mall_load, "p_mw"] = p_candidate_mw
                        net.load.at[mall_load, "q_mvar"] = q_mall_base_mvar

                        if not run_pf(net, context=f"fallback PF at {selected_time}", print_error=False):
                            continue

                        voltage = net.res_bus.vm_pu
                        score = np.maximum(v_min_pu_std - voltage, 0.0).sum()
                        score += np.maximum(voltage - v_max_pu_std, 0.0).sum()

                        if len(net.line):
                            score += np.maximum(net.res_line.loading_percent - loading_percent_max_std, 0.0).sum() / 100.0

                        if len(net.trafo):
                            score += np.maximum(net.res_trafo.loading_percent - loading_percent_max_std, 0.0).sum() / 100.0

                        if score < best_score:
                            best_score = score
                            best_p_mw = p_candidate_mw

                    p_mall_opf_mw = best_p_mw
                    q_mall_opf_mvar = q_mall_base_mvar

                else:
                    q_mall_opf_mvar = net.res_load.at[mall_load, "q_mvar"]

                # 6. Convert grid-side setpoint from OPF to device-side request for mall
                p_grid_setpoint_kw = p_mall_opf_mw * 1000.0
                p_device_setpoint_kw = residual_t_kw[0] - p_grid_setpoint_kw
                # updated flex target as request for the change in operation of CHP and BHP to change their el. generation and consumption respectively
                updated_flex_target_kw[selected_time_idx] = p_device_setpoint_kw

                # 7. Apply the actual action updated flex target from the x_t
                res_actual_t, _, state_actual_t = run_mall_case_with_bounds(
                    time_series_data_base=time_series_t,
                    flex_target_kw=np.asarray([p_device_setpoint_kw]),
                    residual_mall_load_kw=residual_t_kw,
                    start=start_t, end=end_t,
                    time_resolution=time_resolution,
                    frequency=frequency,
                    collect_bounds=False,
                    allow_export=allow_export_to_grid,
                    init_soc=soc_current,
                    previous_controller_results=prev_controller_results,
                    previous_chp_downtime=prev_chp_downtime,
                    return_state=True,
                    verbose=False)

                res_actual_t = res_actual_t.iloc[[0]].copy()

                # Check the grid with the power actually achieved by shopping center
                p_actual_grid_mw = res_actual_t.iloc[0]["p_grid_kw"] / 1000.0
                net.load.at[mall_load, "p_mw"] = p_actual_grid_mw
                net.load.at[mall_load, "q_mvar"] = q_mall_opf_mvar

                if run_pf(net, context=f"subnet {fixed_subnet_id} after actual dispatch at {selected_time}", print_error=False):
                    v_after = net.res_bus.vm_pu.copy()
                    has_violation_after, violations_after = check_grid_violations(net)

                    if opf_failed:
                        status = ("opf_failed_fallback_violations" if has_violation_after
                                  else "opf_failed_fallback_resolved")
                    else:
                        status = ("opf_success_remaining_violations" if has_violation_after
                                  else "opf_success_violations_resolved")
                else:
                    status = "pf_after_ppros_update"
                    v_after = None
                    violations_after = None

        # 8. x_{t+1}: carry the actual storage SOC, previous controller outputs and CHP downtime
        soc_current = res_actual_t.iloc[0]["soc_percent"] / 100.0
        prev_controller_results = state_actual_t["controller_results"]
        prev_chp_downtime = state_actual_t["chp_downtime"]

        res_actual_rows.append(res_actual_t.iloc[0])

        opf_rows.append(build_opf_results(selected_time=selected_time,
                                             subnet_id=fixed_subnet_id,
                                             mall_bus=fixed_mall_bus,
                                             status=status,
                                             flex_activation_required=flex_activation_required,
                                             p_mall_min_mw=p_mall_min_mw,
                                             p_mall_base_mw=p_mall_base_mw,
                                             p_mall_max_mw=p_mall_max_mw,
                                             p_reference_mw=p_mall_base_mw,
                                             p_mall_opf_mw=p_mall_opf_mw,
                                             q_mall_opf_mvar=q_mall_opf_mvar,
                                             p_grid_setpoint_kw=p_grid_setpoint_kw,
                                             p_device_setpoint_kw=p_device_setpoint_kw,
                                             v_before=v_before,
                                             v_after=v_after,
                                             violations_before=violations_before,
                                             violations_after=violations_after))

    opf_results_df = pd.DataFrame(opf_rows).set_index("time")
    res_base = pd.DataFrame(res_base_rows)
    res_actual = pd.DataFrame(res_actual_rows)
    bounds_df = pd.DataFrame(flex_bounds_rows)

    res_base.index = time_series_data_base.index
    res_actual.index = time_series_data_base.index
    bounds_df.index = time_series_data_base.index

    return opf_results_df, updated_flex_target_kw, res_base, res_actual, bounds_df


# 5. Main workflow
def main():
    # TODO: remove hardcoded mall bus to choose a suitable placement
    # TODO: Use Simbench MV net with load timeseries
    # 1. Use known suitable Schutterwald OPF case
    fixed_subnet_id = 1
    fixed_subnet_name = "LV Schutterwald 1"
    fixed_mall_bus = 623

    q_mall_base_mvar = 0.0
    q_eps = 1e-6
    initial_soc = 0.0

    print("\nUsing selected Schutterwald OPF case")
    print(f"Subnet id: {fixed_subnet_id}")
    print(f"Subnet name: {fixed_subnet_name}")
    print(f"Mall bus: {fixed_mall_bus}")

    check_net = get_single_schutterwald_subnet(fixed_subnet_id)
    print(f"Number of buses in selected subnet: {len(check_net.bus)}")

    if fixed_mall_bus not in check_net.bus.index:
        raise RuntimeError(f"Selected mall bus {fixed_mall_bus} is not in subnet {fixed_subnet_id}.")

    if not run_pf(check_net, context=f"subnet {fixed_subnet_id} base PF"):
        raise RuntimeError(f"Base PF does not converge for subnet {fixed_subnet_id}.")

    # 2. Closed-loop time series
    opf_results_df, updated_flex_target_kw, res_base, res_updated, bounds_df = run_opf_timeseries_for_subnet(
        fixed_subnet_id=fixed_subnet_id,
        fixed_mall_bus=fixed_mall_bus,
        time_series_data_base=time_series_data,
        residual_mall_load_kw=residual_mall_load_kw,
        q_mall_base_mvar=q_mall_base_mvar,
        q_eps=q_eps,
        initial_soc=initial_soc)

    if opf_results_df.empty:
        raise RuntimeError("No OPF timestep was calculated for the selected Schutterwald subnet.")

    # 3. Detect violations
    n_violation_timesteps = ((opf_results_df["n_undervoltage_before"] > 0)|
                             (opf_results_df["n_overvoltage_before"] > 0)|
                             (opf_results_df["n_line_overload_before"] > 0)|
                             (opf_results_df["n_trafo_overload_before"] > 0)).sum()

    # 4. Check resolved violations
    n_opf_success = opf_results_df["status"].isin(["opf_success_violations_resolved",
                                                   "opf_success_remaining_violations"]).sum()

    n_opf_resolved = (opf_results_df["status"] == "opf_success_violations_resolved").sum()
    n_fallback_resolved = (opf_results_df["status"] == "opf_failed_fallback_resolved").sum()

    n_voltage_improved = (opf_results_df["status"].isin(["opf_success_violations_resolved",
                                                          "opf_success_remaining_violations",
                                                          "opf_failed_fallback_resolved",
                                                          "opf_failed_fallback_violations"])
                          & (opf_results_df["v_min_after_pu"] > opf_results_df["v_min_before_pu"])).sum()

    print("\nSelected Schutterwald subnet summary")
    print(f"Subnet id: {fixed_subnet_id}")
    print(f"Subnet name: {fixed_subnet_name}")
    print(f"Mall bus: {fixed_mall_bus}")
    print(f"Calculated timesteps: {len(opf_results_df)}")
    print(f"Violation timesteps: {n_violation_timesteps}")
    print(f"OPF success timesteps: {n_opf_success}")
    print(f"OPF resolved timesteps: {n_opf_resolved}")
    print(f"Fallback resolved timesteps: {n_fallback_resolved}")
    print(f"Voltage-improved timesteps: {n_voltage_improved}")

    # 5. Compare requested grid setpoint against actual pandaprosumer updated power
    opf_results_df["p_updated_grid_kw"] = res_updated["p_grid_kw"].reindex(opf_results_df.index)
    opf_results_df["tracking_error_kw"] = opf_results_df["p_updated_grid_kw"] - opf_results_df["p_grid_setpoint_kw"]

    opf_results_df.to_csv("mall_closed_loop_opf_timeseries.csv")
    bounds_df.to_csv("mall_closed_loop_flexibility_bounds.csv")

    print("\nAll timesteps finished")
    print("\nStatus summary")
    print(opf_results_df["status"].value_counts(dropna=False))

    # 6. Build final mall flexibility time series
    mall_idx = res_updated.index
    flex_ts_df = pd.DataFrame(index=mall_idx)

    flex_ts_df["residual_mall_load_kw"] = res_updated["residual_mall_load_kw"].reindex(mall_idx)
    flex_ts_df["p_grid_baseline_kw"] = res_base["p_grid_kw"].reindex(mall_idx)
    flex_ts_df["p_grid_updated_kw"] = res_updated["p_grid_kw"].reindex(mall_idx)

    # Positive value = mall supports the grid by reducing grid import - undervoltage test
    # Negative value = mall consumes more from the grid than in baseline
    flex_ts_df["flexibility_provided_to_grid_kw"] = (flex_ts_df["p_grid_baseline_kw"] - flex_ts_df["p_grid_updated_kw"])

    flex_ts_df["p_device_kw"] = res_updated["p_device_kw"].reindex(mall_idx)
    flex_ts_df["chp_p_el_kw"] = res_updated["chp_p_el_kw"].reindex(mall_idx)
    flex_ts_df["bhp_p_el_kw"] = res_updated["bhp_p_el_kw"].reindex(mall_idx)
    flex_ts_df["soc_percent"] = res_updated["soc_percent"].reindex(mall_idx)
    flex_ts_df["q_delivered_storage_kw"] = res_updated["q_delivered_storage_kw"].reindex(mall_idx)
    flex_ts_df["q_received_demand_kw"] = res_updated["q_received_demand_kw"].reindex(mall_idx)
    flex_ts_df["p_flex_request_kw"] = pd.Series(updated_flex_target_kw, index=mall_idx)

    flex_ts_df["opf_timestep"] = flex_ts_df.index.isin(
        opf_results_df[opf_results_df["flex_activation_required"]].index)

    print("\nMall flexibility timeseries dataframe")
    print(f"pandaprosumer run timesteps: {len(flex_ts_df)}")
    print(f"OPF timesteps: {flex_ts_df['opf_timestep'].sum()}")

    print(f"Max tracking error = {opf_results_df['tracking_error_kw'].abs().max():.6f} kW")
    print(f"Mean tracking error = {opf_results_df['tracking_error_kw'].abs().mean():.6f} kW")

    # 7. Plotting

    # Plot 1: final storage-based mall flexibility provision
    plt.figure(figsize=(12, 6))

    plt.plot(flex_ts_df.index,
             flex_ts_df["p_grid_updated_kw"],
             label="Updated mall grid power",
             linewidth=1.5)

    plt.plot(flex_ts_df.index,
             flex_ts_df["p_grid_baseline_kw"],
             label="Baseline mall grid power",
             linestyle=":",
             linewidth=2.5)

    plt.plot(flex_ts_df.index,
             flex_ts_df["flexibility_provided_to_grid_kw"],
             label="Flexibility provided to grid",
             linewidth=1.5)

    plt.ylabel("Power [kW]")
    plt.xlabel("Time")
    plt.title("Storage-aware Mall Flexibility Provision")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot 3: OPF setpoint tracking by pandaprosumer model
    plt.figure(figsize=(12, 6))
    plt.plot(opf_results_df.index, opf_results_df["p_grid_setpoint_kw"], label="OPF grid setpoint")
    plt.plot(opf_results_df.index, opf_results_df["p_updated_grid_kw"], linestyle="--", label="Updated pandaprosumer grid power")
    plt.ylabel("Mall net grid power [kW]")
    plt.xlabel("Time")
    plt.title("OPF Setpoint Tracking by pandaprosumer")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot 4: minimum grid voltage before and after OPF
    plt.figure(figsize=(12, 6))
    plt.plot(opf_results_df.index, opf_results_df["v_min_before_pu"], label="V_min before OPF")
    plt.plot(opf_results_df.index, opf_results_df["v_min_after_pu"], label="V_min after OPF")
    plt.axhline(v_min_pu_std, linestyle="--", label=f"V_min threshold {v_min_pu_std:.2f} pu")
    plt.ylabel("Minimum voltage [pu]")
    plt.xlabel("Time")
    plt.title("Minimum Grid Voltage Comparison")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot 5: device dispatch behind flexibility provision
    plt.figure(figsize=(12, 6))
    plt.plot(flex_ts_df.index, flex_ts_df["p_flex_request_kw"], linestyle="--", linewidth=3, label="P_device target from OPF")
    plt.plot(flex_ts_df.index, flex_ts_df["p_device_kw"], linewidth=1.2, label="Actual P_device = CHP - BHP")
    plt.plot(flex_ts_df.index, flex_ts_df["chp_p_el_kw"], linestyle="--", label="CHP electrical output")
    plt.plot(flex_ts_df.index, flex_ts_df["bhp_p_el_kw"], linestyle=":", label="BHP electrical consumption")
    plt.ylabel("Power [kW]")
    plt.xlabel("Time")
    plt.title("Mall Flexibility Provision")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot 6: thermal storage SOC
    plt.figure(figsize=(12, 6))
    plt.plot(flex_ts_df.index, flex_ts_df["soc_percent"], label="Thermal storage SOC")
    plt.ylabel("SOC [%]")
    plt.xlabel("Time")
    plt.title("Thermal Storage SOC during Flexibility Provision")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()