import warnings
import copy
import time
import contextlib
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import networkx as nx
import os
import sys
from contextlib import contextmanager
import pandapower as pp
import pandapower.plotting as pp_plot
import pandapower.topology as pp_topology
import simbench as sb


try:
    from tqdm import tqdm
    _HAVE_TQDM = True
except ImportError:
    _HAVE_TQDM = False


# 1. Terminal / environment setup
# suppress the HiGHS solver banner that pandapower's OPF prints to stdout
@contextmanager
def suppress_native_stdout():
    stdout_fd = sys.stdout.fileno()
    saved_fd = os.dup(stdout_fd)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, stdout_fd)
        yield
    finally:
        os.dup2(saved_fd, stdout_fd)
        os.close(devnull_fd)
        os.close(saved_fd)


warnings.filterwarnings("ignore", category=FutureWarning, module="simbench")
warnings.filterwarnings("ignore", category=FutureWarning, module="pandapower")
pd.set_option('future.no_silent_downcasting', True)


# monkeypatch: older Simbench nets are missing legacy geodata tables that
# some pandapower plotting helpers still expect
_LEGACY_GEODATA_TABLES = {
    "bus_geodata": ["x", "y"],
    "line_geodata": ["coords"],
}
_original_create_empty_network = pp.create_empty_network

def _patched_create_empty_network(*args, **kwargs):
    net = _original_create_empty_network(*args, **kwargs)
    for table_name, cols in _LEGACY_GEODATA_TABLES.items():
        if table_name not in net or net[table_name] is None:
            net[table_name] = pd.DataFrame(columns=cols)
    return net

pp.create_empty_network = _patched_create_empty_network


from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_heat_demand,
                                             create_controlled_booster_heat_pump, create_controlled_ice_chp,
                                             create_controlled_heat_storage, create_controlled_optimtization)
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries

frequency = "60min"
time_resolution = 3600

project_root = (Path.cwd().parent if Path.cwd().name in ["tutorials", "tutorials_extended"]
                else Path.cwd())

ses_data_file = project_root / "tutorials_extended" / "data" / "ses_data.xlsx"
heat_data_file = project_root / "tutorials_extended" / "data" / "aleja_heat_demand_model_data.xlsx"

GRID_CODE = "1-MV-rural--1-sw"  # urban grids are stiff, so rural grids are preferred for stress-testing

MALL_BUS = 15  # not hard coded in practice: the mall bus is auto-determined, see find_weakest_branch_leaf_bus()

YEAR_START = pd.Timestamp("2025-01-01 00:15:00")


# Grid violation thresholds
v_min_pu_std = 0.90
v_max_pu_std = 1.10
loading_percent_max_std = 100.0

allow_export_to_grid = True

WINDOW_DAYS = 8

# knobs used to push the grid into a violation during calibration
CALIBRATION_DERATE_BOUNDS = (1.0, 0.15)
CALIBRATION_UV_LOAD_SCALE_BOUNDS = (1.0, 30.0)
BISECTION_ITERS = 20


USE_NUMBA = False

# By default the terminal only shows: a live progress bar per scenario, the
# chosen calibration thresholds, and one consolidated summary box per
# scenario at the end (violated hours, resolved vs. remaining, top violated
# elements, tracking error, SOC range). Full hour-by-hour / bisection-step
# detail is always still written to the CSVs
# (grid_opf_timeseries_results_*.csv, grid_violation_details_*.csv,
# grid_flexibility_bounds_*.csv), so nothing is lost by keeping these False --
# flip them to True only when actively debugging.
VERBOSE_CALIBRATION_DEBUG = False
VERBOSE_OPF_FAILURES = False

# reactive-power headroom for the mall load.
# Import scenarios keep the mall load pinned to essentially zero Q freedom
# (matches the original behavior -- import violations here are line-overload
# / undervoltage driven, and P curtailment is the natural lever).
IMPORT_Q_EPS_MVAR = 1e-6


# 2. SES data loading + best-window scanning

def load_full_ses_data(path):
    ses_data = pd.read_excel(path)
    ses_data.columns = ses_data.columns.str.strip()
    ses_data = ses_data.set_index("Timestamp").sort_index()

    required_cols = ["P el sc [kW]", "P pv [kW]"]
    for col in required_cols:
        ses_data[col] = ses_data[col].astype(str).str.replace(",", ".", regex=False)
        ses_data[col] = pd.to_numeric(ses_data[col], errors="coerce")
    ses_data = ses_data.dropna(subset=required_cols)

    ses_data_1h = ses_data[required_cols].resample("60min").mean().dropna(subset=required_cols)
    return ses_data_1h


def scan_ses_windows(ses_data_1h, window_days=WINDOW_DAYS):
    window_hours = window_days * 24
    residual = ses_data_1h["P el sc [kW]"] - ses_data_1h["P pv [kW]"]

    residual_sum = residual.rolling(window_hours).sum()
    residual_peak_import = residual.rolling(window_hours).max()
    residual_peak_export = residual.rolling(window_hours).min()

    starts = residual_sum.index - pd.Timedelta(hours=window_hours - 1)

    scan_df = pd.DataFrame({
        "window_start": starts,
        "window_end": residual_sum.index,
        "residual_sum_kwh": residual_sum.values,
        "residual_peak_import_kw": residual_peak_import.values,
        "residual_peak_export_kw": residual_peak_export.values,
    }).dropna().reset_index(drop=True)

    if scan_df.empty:
        raise RuntimeError("SES data too short to form even one full window.")

    best_export_row = scan_df.loc[scan_df["residual_sum_kwh"].idxmin()]
    best_import_row = scan_df.loc[scan_df["residual_peak_import_kw"].idxmax()]

    return scan_df, best_export_row, best_import_row


def load_and_scan_ses_data(path, window_days=WINDOW_DAYS):
    """Convenience wrapper: load the workbook and scan it in one call,
    returning (ses_data_1h_full, scan_df, best_export_row, best_import_row)."""

    ses_data_1h_full = load_full_ses_data(path)
    scan_df, best_export_row, best_import_row = scan_ses_windows(ses_data_1h_full, window_days=window_days)
    return ses_data_1h_full, scan_df, best_export_row, best_import_row


def build_time_series_data(residual_mall_load_kw, start, n_steps, heat_data_file):
    time_series_data = pd.read_excel(heat_data_file)
    if len(time_series_data) < n_steps:
        repeat_factor = int(np.ceil(n_steps / len(time_series_data)))
        time_series_data = pd.concat([time_series_data] * repeat_factor, ignore_index=True)
    time_series_data = time_series_data.iloc[:n_steps].copy()

    dur = pd.date_range(start=start, periods=n_steps, freq=frequency, tz="utc")
    time_series_data.index = dur

    time_series_data["flex_demand_kw"] = np.zeros(n_steps)
    time_series_data["t_sink_k"] = 350
    time_series_data["cycle"] = 1
    return time_series_data


# 3. pprosumer model (unchanged from the closed-loop model: previous
# controller results and CHP downtime are carried across timesteps)

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
    if previous_controller_results is not None:
        prosumer.controller_results = copy.deepcopy(previous_controller_results)

    if previous_chp_downtime is not None:
        optimization_controller._chp_downtime = copy.deepcopy(previous_chp_downtime)

    return prosumer, period, optimization_controller


# 4. pprosumer run with controller-based bounds

def run_mall_case_with_bounds(time_series_data_base, flex_target_kw, residual_mall_load_kw,
                              start, end, time_resolution, frequency, collect_bounds=False,
                              allow_export=False, init_soc=0.0, previous_controller_results=None,
                              previous_chp_downtime=None, return_state=False, verbose=False):

    prosumer, period, optimization_controller = build_mall_prosumer(time_series_data_base=time_series_data_base, flex_target_kw=flex_target_kw,
                                                                    start=start, end=end, time_resolution=time_resolution,
                                                                    frequency=frequency, collect_bounds=collect_bounds, init_soc=init_soc,
                                                                    previous_controller_results=previous_controller_results,
                                                                    previous_chp_downtime=previous_chp_downtime)

    with suppress_native_stdout():  # to remove the HiGHS banner in the terminal
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

    residual_kw = res_df["residual_mall_load_kw"]
    bounds_df["p_mall_base_kw"] = res_df["p_grid_kw"]
    bounds_df["p_mall_min_kw"] = (residual_kw - bounds_df["p_device_max_support_kw"])
    bounds_df["p_mall_max_kw"] = (residual_kw - bounds_df["p_device_max_absorption_kw"])

    if not allow_export:
        bounds_df["p_mall_base_kw"] = bounds_df["p_mall_base_kw"].clip(lower=0.0)
        bounds_df["p_mall_min_kw"] = bounds_df["p_mall_min_kw"].clip(lower=0.0)
        bounds_df["p_mall_max_kw"] = bounds_df["p_mall_max_kw"].clip(lower=0.0)

    raw_cols = ["p_mall_min_kw", "p_mall_base_kw", "p_mall_max_kw"]

    bounds_df["p_mall_min_mw"] = bounds_df[raw_cols].min(axis=1) / 1000.0
    bounds_df["p_mall_base_mw"] = bounds_df["p_mall_base_kw"] / 1000.0
    bounds_df["p_mall_max_mw"] = bounds_df[raw_cols].max(axis=1) / 1000.0

    bounds_df["flex_down_mw"] = (bounds_df["p_mall_base_mw"] - bounds_df["p_mall_min_mw"])
    bounds_df["flex_up_mw"] = (bounds_df["p_mall_max_mw"] - bounds_df["p_mall_base_mw"])

    if return_state:
        return res_df, bounds_df, state

    return res_df, bounds_df


# 5. pandapower grid preparation + OPF integration

def fix_element_dtypes(net):
    """Fix bool columns pandas may have broken (in_service/controllable),
    and force tap_dependency_table off on trafos."""
    bool_cols = ["in_service", "controllable"]
    for table_name in ["bus", "line", "trafo", "trafo3w", "load", "sgen",
                       "ext_grid", "gen", "shunt", "switch", "storage"]:
        if table_name not in net or net[table_name] is None:
            continue
        table = net[table_name]
        for col in bool_cols:
            if col in table.columns:
                table[col] = table[col].fillna(True).infer_objects(copy=False).astype(bool)

    for table_name in ["trafo", "trafo3w"]:
        if table_name not in net or net[table_name] is None:
            continue
        table = net[table_name]
        if "tap_dependency_table" in table.columns:
            table["tap_dependency_table"] = False


def prepare_grid_for_opf(net, capacity_derate=1.0, derate_line_idx=None):
    if len(net.load):
        net.load["controllable"] = False
    if len(net.sgen):
        net.sgen["controllable"] = False

    net.bus["min_vm_pu"] = v_min_pu_std
    net.bus["max_vm_pu"] = v_max_pu_std
    if len(net.line):
        net.line["max_loading_percent"] = loading_percent_max_std
        if capacity_derate != 1.0:
            target_lines = net.line.index if derate_line_idx is None else pd.Index(derate_line_idx)
            net.line.loc[target_lines, "max_i_ka"] = net.line.loc[target_lines, "max_i_ka"] * capacity_derate
    if len(net.trafo):
        net.trafo["max_loading_percent"] = loading_percent_max_std

    net.ext_grid["min_p_mw"] = -10.0
    net.ext_grid["max_p_mw"] = 10.0
    net.ext_grid["min_q_mvar"] = -10.0
    net.ext_grid["max_q_mvar"] = 10.0

    for eg_bus, eg_vm in zip(net.ext_grid["bus"], net.ext_grid["vm_pu"]):
        net.bus.at[eg_bus, "min_vm_pu"] = eg_vm
        net.bus.at[eg_bus, "max_vm_pu"] = eg_vm


def run_pf(net, context="", print_error=True):
    try:
        pp.runpp(net, algorithm="nr", max_iteration=50, tolerance_mva=1e-8, init="auto", numba=USE_NUMBA)
        return True
    except Exception as exc:
        if print_error:
            print(f"\nPower flow failed: {context}")
            print(f"Reason: {exc}")
        return False


def check_grid_violations(net):
    violations = {"undervoltage": [], "overvoltage": [],
                  "line_overload": [], "trafo_overload": []}
    for bus in net.res_bus.index:
        vm_pu = net.res_bus.at[bus, "vm_pu"]
        if vm_pu < v_min_pu_std:
            violations["undervoltage"].append((bus, vm_pu))
        if vm_pu > v_max_pu_std:
            violations["overvoltage"].append((bus, vm_pu))
    if len(net.line):
        for line in net.res_line.index:
            loading = net.res_line.at[line, "loading_percent"]
            if loading > loading_percent_max_std:
                violations["line_overload"].append((line, loading))
    if len(net.trafo):
        for trafo in net.res_trafo.index:
            loading = net.res_trafo.at[trafo, "loading_percent"]
            if loading > loading_percent_max_std:
                violations["trafo_overload"].append((trafo, loading))
    has_violation = any(len(v) > 0 for v in violations.values())
    return has_violation, violations


def element_label(net, violation_type, element_id):
    try:
        if violation_type == "trafo_overload":
            name = net.trafo.at[element_id, "name"]
            return name if pd.notna(name) and name else f"trafo_{element_id}"
        if violation_type == "line_overload":
            name = net.line.at[element_id, "name"] if "name" in net.line.columns else None
            return name if name is not None and pd.notna(name) and name else f"line_{element_id}"
        if violation_type in ("undervoltage", "overvoltage"):
            name = net.bus.at[element_id, "name"]
            return name if pd.notna(name) and name else f"bus_{element_id}"
    except Exception:
        pass
    return str(element_id)


def record_violation_details(rows_list, hour, phase, violations, net):
    for violation_type, entries in violations.items():
        for element_id, value in entries:
            rows_list.append({
                "time": hour,
                "phase": phase,
                "violation_type": violation_type,
                "element_id": element_id,
                "location": element_label(net, violation_type, element_id),
                "value": value,
            })


def run_mall_opf(net, mall_load, p_base_mw):
    if "poly_cost" in net and len(net.poly_cost):
        net.poly_cost.drop(net.poly_cost.index, inplace=True)

    weight = 1000.0
    pp.create_poly_cost(net, element=mall_load, et="load",
                        cp2_eur_per_mw2=weight,
                        cp1_eur_per_mw=-2.0 * weight * p_base_mw,
                        cp0_eur=weight * p_base_mw**2)
    for eg in net.ext_grid.index:
        pp.create_poly_cost(net, element=eg, et="ext_grid",
                            cp1_eur_per_mw=0.0, cp2_eur_per_mw2=0.0)

    try:
        with suppress_native_stdout():
            pp.runopp(net, calculate_voltage_angles=False, init="pf", numba=USE_NUMBA,
                      verbose=False, suppress_warnings=True,
                      OPF_VIOLATION=1e-4, PDIPM_FEASTOL=1e-4,
                      PDIPM_GRADTOL=1e-4, PDIPM_COMPTOL=1e-4,
                      PDIPM_COSTTOL=1e-4, PDIPM_MAX_IT=100)
    except Exception as exc:
        if VERBOSE_OPF_FAILURES:
            print(f"\nOPF failed: {exc}")
        return None
    if not getattr(net, "OPF_converged", False):
        if VERBOSE_OPF_FAILURES:
            print("\nOPF did not converge.")
        return None

    return net.res_load.at[mall_load, "p_mw"]


# 6. Feeder topology helpers -- locating the weakest branch, walking from
# the ext_grid to a target bus, and finding elements downstream of a bus

def find_bus_feeder_line(net, bus):
    candidates = net.line.index[(net.line.from_bus == bus) | (net.line.to_bus == bus)]
    if len(candidates) == 0:
        raise RuntimeError(f"No line found incident to bus {bus}.")
    return candidates[0]


def find_weakest_branch_leaf_bus(net):
    """Finds the most electrically stressed line in the network, then walks
    outward from it to the leaf bus (dead end) at the far end of that
    branch. Used to pick where to place the mall for a calibration / worst
    case check (typically where voltage problems are worst)."""

    net_check = copy.deepcopy(net)
    fix_element_dtypes(net_check)
    if not run_pf(net_check, context="find_weakest_branch_leaf_bus", print_error=False):
        raise RuntimeError("Base power flow failed: cannot identify the weakest branch.")

    worst_line = net_check.res_line["loading_percent"].idxmax()
    from_bus = net_check.line.at[worst_line, "from_bus"]
    to_bus = net_check.line.at[worst_line, "to_bus"]

    graph = pp_topology.create_nxgraph(net_check, respect_switches=True)

    if to_bus not in graph:
        return to_bus, worst_line

    prev_bus, current_bus = from_bus, to_bus
    visited = {prev_bus}
    while graph.degree[current_bus] > 1:
        visited.add(current_bus)
        neighbors = [n for n in graph.neighbors(current_bus) if n not in visited]
        if not neighbors:
            raise RuntimeError(
                f"find_weakest_branch_leaf_bus: walk from worst line {worst_line} "
                f"got stuck at bus {current_bus} (degree {graph.degree[current_bus]}, "
                "not a leaf) with no unvisited neighbor to continue to. This usually "
                "means the switch respecting topology graph still contains an "
                "unexpected loop inspect net.switch (in_service/closed) before "
                "trusting any branch localized calibration downstream of this call.")
        prev_bus, current_bus = current_bus, neighbors[0]

    assert graph.degree[current_bus] == 1, (
        f"find_weakest_branch_leaf_bus: resolved bus {current_bus} has degree "
        f"{graph.degree[current_bus]}, expected a leaf (degree 1).")

    return current_bus, worst_line


def build_feeder_graph(net):
    """Switch respecting connectivity graph, used by the path/downstream
    walks below. NOTE: this is deliberately different from the graph built
    in compute_hierarchical_layout, which ignores switches (it only needs a
    drawable tree, not an electrically accurate topology)."""

    graph = pp_topology.create_nxgraph(net, respect_switches=True)

    open_line_switch_idx = set()
    if "switch" in net and len(net.switch):
        for _, row in net.switch.iterrows():
            if row.get("et") == "l" and not row.get("closed", True):
                open_line_switch_idx.add(row["element"])

    line_of_edge = {}
    for li, row in net.line.iterrows():
        if row["in_service"] and li not in open_line_switch_idx:
            line_of_edge[(row["from_bus"], row["to_bus"])] = li
            line_of_edge[(row["to_bus"], row["from_bus"])] = li

    open_trafo_switch_idx = set()
    if "switch" in net and len(net.switch):
        for _, row in net.switch.iterrows():
            if row.get("et") == "t" and not row.get("closed", True):
                open_trafo_switch_idx.add(row["element"])

    trafo_of_edge = {}
    if "trafo" in net and len(net.trafo):
        for ti, row in net.trafo.iterrows():
            if row["in_service"] and ti not in open_trafo_switch_idx:
                trafo_of_edge[(row["hv_bus"], row["lv_bus"])] = ti
                trafo_of_edge[(row["lv_bus"], row["hv_bus"])] = ti

    return graph, line_of_edge, trafo_of_edge


def root_bus_path(net, graph, target_bus, target_label="target_bus"):
    """Validates root (ext_grid bus) and target_bus are both connected in
    graph, and returns (root, bus_path) via shortest_path. Shared by
    find_path_lines_to_bus and find_downstream_elements."""

    root = net.ext_grid["bus"].iloc[0]
    if root not in graph:
        raise RuntimeError(f"ext_grid bus {root} has no connectivity (line or trafo) in this net.")
    if target_bus not in graph:
        raise RuntimeError(f"{target_label} {target_bus} has no connectivity (line or trafo) in this net.")
    return root, nx.shortest_path(graph, root, target_bus)


def find_path_lines_to_bus(net, target_bus, max_segments_from_bus=None):
    graph, line_of_edge, _ = build_feeder_graph(net)
    _, bus_path = root_bus_path(net, graph, target_bus, "target_bus")

    line_idx = [line_of_edge[edge] for edge in zip(bus_path[:-1], bus_path[1:]) if edge in line_of_edge]

    if max_segments_from_bus is not None and len(line_idx) > max_segments_from_bus:
        line_idx = line_idx[-max_segments_from_bus:]

    return line_idx


def find_path_trafos_to_bus(net, target_bus):
    """Trafos (if any) sitting on the ext_grid -> target_bus path -- e.g. an
    HV/MV substation trafo or an MV/LV trafo feeding the mall's branch.
    Returns an empty list if the path is all lines, which is common on a
    pure MV feeder where the only trafo sits at the root."""

    graph, _, trafo_of_edge = build_feeder_graph(net)
    _, bus_path = root_bus_path(net, graph, target_bus, "target_bus")
    return [trafo_of_edge[edge] for edge in zip(bus_path[:-1], bus_path[1:]) if edge in trafo_of_edge]


def find_downstream_elements(net, mall_bus):
    """Every load and sgen sitting electrically downstream of mall_bus."""
    graph, _, _ = build_feeder_graph(net)
    _, bus_path = root_bus_path(net, graph, mall_bus, "mall_bus")
    path_buses = set(bus_path)

    graph_no_backedge = graph.copy()
    if len(bus_path) > 1:
        graph_no_backedge.remove_edge(bus_path[-2], bus_path[-1])
    subtree_buses = nx.node_connected_component(graph_no_backedge, mall_bus)

    downstream_buses = path_buses | subtree_buses

    downstream_sgen_idx = list(net.sgen.index[net.sgen["bus"].isin(downstream_buses)])
    downstream_load_idx = list(net.load.index[net.load["bus"].isin(downstream_buses)])

    return downstream_sgen_idx, downstream_load_idx, downstream_buses


def compute_hierarchical_layout(net):
    """Fills in net.bus.geo (in place) for any bus missing geo data, using a
    feeder tree layout rooted at the ext_grid bus, and returns a
    {bus: branch_id} map (branch_id=-1 for the root/trunk) so callers can
    color each outgoing branch differently. Returns an empty dict and makes
    no changes to net if every bus already has geo data."""
    import json as _json

    geo = net.bus.geo
    missing_geo = geo.isna() | (geo.astype(str).str.strip() == "") | (geo.astype(str) == "None")
    if not missing_geo.any():
        return {}

    print(f"[plot] {missing_geo.sum()} bus(es) missing geo data -> "
          f"computing hierarchical feeder tree layout (industry SLD style)")

    # deliberately respect_switches=False: this is a drawing layout, not
    # an electrical topology walk, so open switches shouldn't fragment it.
    mg = pp_topology.create_nxgraph(net, respect_switches=False)

    if len(net.ext_grid):
        root = net.ext_grid["bus"].iloc[0]
    else:
        root = net.bus.index[0]

    levels = {root: 0}
    children_by_parent = {}
    for parent, child in nx.bfs_edges(mg, root):
        levels[child] = levels[parent] + 1
        children_by_parent.setdefault(parent, []).append(child)

    unreached = [b for b in net.bus.index if b not in levels]
    for b in unreached:
        levels[b] = 0

    DEPTH_STEP = 2.0
    LEAF_STEP = 1.0

    y_counter = [0.0]
    pos = {}

    def assign_y(bus):
        kids = children_by_parent.get(bus, [])
        if not kids:
            y = y_counter[0]
            y_counter[0] += LEAF_STEP
            pos[bus] = y
            return y
        child_ys = [assign_y(k) for k in kids]
        y = sum(child_ys) / len(child_ys)
        pos[bus] = y
        return y

    assign_y(root)
    for b in unreached:
        if b not in pos:
            y = y_counter[0]
            y_counter[0] += LEAF_STEP
            pos[b] = y

    for bus, y in pos.items():
        x = levels[bus] * DEPTH_STEP
        net.bus.at[bus, "geo"] = _json.dumps({"type": "Point", "coordinates": [float(x), float(y)]})

    branch_of = {}
    root_children = children_by_parent.get(root, [])
    for i, top_child in enumerate(root_children):
        stack = [top_child]
        while stack:
            b = stack.pop()
            branch_of[b] = i
            stack.extend(children_by_parent.get(b, []))
    branch_of[root] = -1

    return branch_of


# 7. Simbench net template + base net with the mall load attached

_NET_TEMPLATE_CACHE = {}
def get_net_template(grid_code):
    """Caches the Simbench net template per grid_code, since re-loading it
    from Simbench on every scenario/calibration call is expensive."""
    if grid_code not in _NET_TEMPLATE_CACHE:
        net = sb.get_simbench_net(grid_code)
        fix_element_dtypes(net)
        prepare_grid_for_opf(net, capacity_derate=1.0, derate_line_idx=None)
        _NET_TEMPLATE_CACHE[grid_code] = net
    return copy.deepcopy(_NET_TEMPLATE_CACHE[grid_code])


def build_base_net(mall_bus=MALL_BUS, q_mall_base_mvar=0.0, q_eps=1e-3,
                    capacity_derate=1.0, derate_line_idx=None,
                    capacity_derate_trafo=1.0, derate_trafo_idx=None, grid_code=None):
    grid_code = grid_code or GRID_CODE
    net_base = get_net_template(grid_code)

    if capacity_derate != 1.0 and len(net_base.line):
        target_lines = net_base.line.index if derate_line_idx is None else pd.Index(derate_line_idx)
        net_base.line.loc[target_lines, "max_i_ka"] = net_base.line.loc[target_lines, "max_i_ka"] * capacity_derate

    if capacity_derate_trafo != 1.0 and len(net_base.trafo):
        target_trafos = net_base.trafo.index if derate_trafo_idx is None else pd.Index(derate_trafo_idx)
        net_base.trafo.loc[target_trafos, "sn_mva"] = net_base.trafo.loc[target_trafos, "sn_mva"] * capacity_derate_trafo

    if mall_bus not in net_base.bus.index:
        raise RuntimeError(f"mall_bus {mall_bus} not found in grid {grid_code}.")

    mall_load_idx = pp.create_load(net_base, bus=mall_bus,
                                   p_mw=0.0,
                                   q_mvar=q_mall_base_mvar,
                                   name="Shopping Mall load",
                                   controllable=True,
                                   min_p_mw=0.0,
                                   max_p_mw=0.0,
                                   min_q_mvar=q_mall_base_mvar - q_eps,
                                   max_q_mvar=q_mall_base_mvar + q_eps)

    mall_feeder_line_idx = find_bus_feeder_line(net_base, mall_bus)

    return net_base, mall_load_idx, mall_feeder_line_idx


# 8. Simbench profile helpers -- reading absolute value profiles and
# deriving stress signals from them (worst hour, per-window feeder totals)

def apply_scaled_column(net, table_name, col, native_values, scale, scoped_idx):
    """Writes native_values * scale into net[table_name][col]. If
    scoped_idx is given, only elements in it get scale; everything else is
    written unscaled (factor 1.0)."""
    ids = native_values.index
    if scoped_idx is None:
        net[table_name].loc[ids, col] = native_values * scale
    else:
        scoped = set(scoped_idx)
        for eid in ids:
            this_scale = scale if eid in scoped else 1.0
            net[table_name].at[eid, col] = native_values[eid] * this_scale


def apply_simbench_profile_for_hour(net, profiles, idx, hour, load_scale=1.0, sgen_scale=1.0,
                                     scoped_sgen_idx=None, scoped_load_idx=None):
    if idx.tz is not None:
        hour = hour.tz_localize(idx.tz) if hour.tzinfo is None else hour.tz_convert(idx.tz)
    elif hour.tzinfo is not None:
        hour = hour.tz_localize(None)

    step = idx.get_loc(hour)

    apply_scaled_column(net, "load", "p_mw", profiles[("load", "p_mw")].iloc[step], load_scale, scoped_load_idx)
    apply_scaled_column(net, "load", "q_mvar", profiles[("load", "q_mvar")].iloc[step], load_scale, scoped_load_idx)

    if len(profiles[("sgen", "p_mw")].columns):
        apply_scaled_column(net, "sgen", "p_mw", profiles[("sgen", "p_mw")].iloc[step], sgen_scale, scoped_sgen_idx)


def get_feeder_load_sgen_window(load_p_1h, sgen_p_1h, window_start, window_end, sgen_cols=None):
    hourly_idx = load_p_1h.index[(load_p_1h.index >= window_start) & (load_p_1h.index < window_end)]

    feeder_load_mw = load_p_1h.sum(axis=1)
    feeder_load_window = feeder_load_mw.reindex(hourly_idx).to_numpy()

    sgen_scoped = sgen_p_1h
    if sgen_cols is not None:
        sgen_cols = [c for c in sgen_cols if c in sgen_scoped.columns]
        sgen_scoped = sgen_scoped[sgen_cols]

    if len(sgen_scoped.columns):
        feeder_sgen_mw = sgen_scoped.sum(axis=1)
    else:
        feeder_sgen_mw = pd.Series(0.0, index=load_p_1h.index)
    feeder_sgen_window = feeder_sgen_mw.reindex(hourly_idx).to_numpy()

    return hourly_idx, feeder_load_window, feeder_sgen_window


def find_worst_hour_proxy(direction, window_start, window_end, residual_mall_load_kw, load_p_1h, sgen_p_1h):
    hourly_idx, feeder_load_window, feeder_sgen_window = get_feeder_load_sgen_window(
        load_p_1h, sgen_p_1h, window_start, window_end)
    mall_residual_mw = np.asarray(residual_mall_load_kw) / 1000.0

    if direction == "import":
        stress_proxy = feeder_load_window + mall_residual_mw
    elif direction == "export":
        stress_proxy = mall_residual_mw - feeder_sgen_window
    else:
        raise ValueError("direction must be 'import' or 'export'")

    worst_pos = int(np.nanargmax(np.abs(stress_proxy)))
    return hourly_idx[worst_pos]


# 9. Grid stress calibration -- bisecting toward the first violation
#
# Import only (Case 1) by design. Case 2 (export) was removed entirely: the
# mall has no battery and its thermal-storage headroom is not comparable to
# realistic export surpluses, so OPF could never actually resolve an export
# violation.
#
# Case 1 (import) is calibrated as two independent single-axis bisections
# (derate only, load only). Each threshold is a standalone, single-cause
# minimal violation, so there's no risk of the two axes compounding into an
# unresolvable stress point.
#
# A third, optional trafo-derate axis is attempted whenever a trafo sits on
# the mall's ext_grid-to-bus path. If that axis can't be pushed into a
# violation within the tested bounds, it is treated as a legitimate finding
# (the transformer isn't this feeder's bottleneck at this bus and hour)
# rather than an error, and the trafo scenario is skipped.

def run_pf_metrics(net, context):
    if not run_pf(net, context=context, print_error=False):
        return None
    line_load_max = net.res_line["loading_percent"].max() if len(net.res_line) else float("nan")
    trafo_load_max = net.res_trafo["loading_percent"].max() if len(net.res_trafo) else float("nan")
    has_violation, violations = check_grid_violations(net)
    return {"vm_min": net.res_bus["vm_pu"].min(), "vm_max": net.res_bus["vm_pu"].max(),
            "line_load_max": line_load_max, "trafo_load_max": trafo_load_max,
            "max_loading_pct": np.nanmax([line_load_max, trafo_load_max]),
            "has_violation": has_violation, "violations": violations}


def attempt_opf_resolution(net, mall_load, p_mall_base_mw, context):
    """Runs the mall OPF, applies its result, re-runs PF, and reports
    whether the violation is resolved."""
    p_opf_mw = run_mall_opf(net, mall_load, p_mall_base_mw)
    if p_opf_mw is None:
        return False
    net.load.at[mall_load, "p_mw"] = p_opf_mw
    if not run_pf(net, context=context + " after OPF", print_error=False):
        return False
    has_violation_after, _ = check_grid_violations(net)
    return not has_violation_after


def evaluate_calibration_point(direction, worst_hour, bounds_df, mall_bus, profiles, idx,
                                mode, value, derate_line_idx=None, derate_trafo_idx=None,
                                scoped_sgen_idx=None, scoped_load_idx=None,
                                verbose_debug=VERBOSE_CALIBRATION_DEBUG):
    if worst_hour not in bounds_df.index:
        raise RuntimeError(f"Worst hour {worst_hour} not found in prosumer bounds_df.")

    p_mall_min_mw = bounds_df.at[worst_hour, "p_mall_min_mw"]
    p_mall_base_mw = bounds_df.at[worst_hour, "p_mall_base_mw"]
    p_mall_max_mw = bounds_df.at[worst_hour, "p_mall_max_mw"]

    # Case 2/export removed: this function is now only ever called with
    # direction="import".
    q_eps = IMPORT_Q_EPS_MVAR

    if mode == "derate":
        net_base, mall_load, _ = build_base_net(mall_bus=mall_bus, capacity_derate=value,
                                                  derate_line_idx=derate_line_idx, q_eps=q_eps)
        net = copy.deepcopy(net_base)
        apply_simbench_profile_for_hour(net, profiles, idx, worst_hour, load_scale=1.0, sgen_scale=1.0)
    elif mode == "derate_trafo":
        net_base, mall_load, _ = build_base_net(mall_bus=mall_bus, capacity_derate_trafo=value,
                                                  derate_trafo_idx=derate_trafo_idx, q_eps=q_eps)
        net = copy.deepcopy(net_base)
        apply_simbench_profile_for_hour(net, profiles, idx, worst_hour, load_scale=1.0, sgen_scale=1.0)
    elif mode == "scale":
        net_base, mall_load, _ = build_base_net(mall_bus=mall_bus, q_eps=q_eps)
        net = copy.deepcopy(net_base)
        if direction != "import":
            raise ValueError(
                "direction must be 'import': export-direction ('scale' mode with "
                "sgen scaling) calibration was removed along with the rest of Case 2.")
        load_scale, sgen_scale = value, 1.0
        this_scoped_sgen_idx, this_scoped_load_idx = None, scoped_load_idx

        apply_simbench_profile_for_hour(
            net, profiles, idx, worst_hour,
            load_scale=load_scale, sgen_scale=sgen_scale,
            scoped_sgen_idx=this_scoped_sgen_idx,
            scoped_load_idx=this_scoped_load_idx)
    else:
        raise ValueError("mode must be 'derate', 'derate_trafo', or 'scale'")

    net.load.at[mall_load, "p_mw"] = p_mall_base_mw
    net.load.at[mall_load, "min_p_mw"] = p_mall_min_mw
    net.load.at[mall_load, "max_p_mw"] = p_mall_max_mw

    context = f"calibration ({direction}, {mode}={value})"
    metrics = run_pf_metrics(net, context=context)
    if metrics is None:
        return {"value": value, "violated": False, "resolved": False, "pf_failed": True,
                "max_loading_pct": np.nan, "v_min_pu": np.nan, "v_max_pu": np.nan}

    if verbose_debug:
        print(f"    [calib debug] {mode}={value}: vm_pu min={metrics['vm_min']:.4f} max={metrics['vm_max']:.4f} "
              f"(limits {v_min_pu_std:.3f}-{v_max_pu_std:.3f}), "
              f"line loading max={metrics['line_load_max']:.1f}% trafo loading max={metrics['trafo_load_max']:.1f}% "
              f"(limit {loading_percent_max_std}%)")

    if not metrics["has_violation"]:
        return {"value": value, "violated": False, "resolved": False, "pf_failed": False,
                "max_loading_pct": metrics["max_loading_pct"], "v_min_pu": metrics["vm_min"], "v_max_pu": metrics["vm_max"]}

    resolved = attempt_opf_resolution(net, mall_load, p_mall_base_mw, context=context)

    return {"value": value, "violated": True, "resolved": resolved, "pf_failed": False,
            "max_loading_pct": metrics["max_loading_pct"], "v_min_pu": metrics["vm_min"], "v_max_pu": metrics["vm_max"]}


def bisect_to_first_violation(evaluate_fn, bounds=(0.0, 1.0), iters=BISECTION_ITERS,
                               stop_fn=None, raise_on_unbracketed=True):
    """Bisects evaluate_fn over bounds to find the value that first produces
    a grid violation.

    raise_on_unbracketed: if the 'stress' bound doesn't violate at all, the
    bracket is invalid. Historically this silently returned the untested
    stress bound anyway, which once produced a 525%-loading, unresolvable
    scenario. Default is now to raise."""

    low_val, high_val = bounds
    log_rows = []

    def eval_and_log(value):
        row = evaluate_fn(value)
        log_rows.append(row)
        return row

    low_row = eval_and_log(low_val)
    high_row = eval_and_log(high_val)

    if low_row["violated"]:
        print(f"WARNING: the 'safe' bound {low_val} already violates -- "
              "bisection bracket is invalid, treating it as the answer.")
        return low_val, pd.DataFrame(log_rows)

    if not high_row["violated"]:
        msg = (f"the 'stress' bound {high_val} does not violate at all -- the bracket "
               "is invalid, so there is no verified violation anywhere in this range "
               "to bisect toward.")
        if raise_on_unbracketed:
            raise RuntimeError(
                "bisect_to_first_violation: " + msg + " Extend the calibration "
                "bounds, pick a different calibration hour, or pass "
                "raise_on_unbracketed=False to (unsafely) fall back to this "
                "untested value.")
        print(f"WARNING: {msg} Falling back to this value -- UNVALIDATED, treat "
              "with caution.")
        return high_val, pd.DataFrame(log_rows)

    a, b = low_val, high_val
    for _ in range(iters):
        mid = (a + b) / 2.0

        row = eval_and_log(mid)
        if row["violated"]:
            b = mid
            if stop_fn is not None and stop_fn(row):
                return mid, pd.DataFrame(log_rows)
        else:
            a = mid

    return b, pd.DataFrame(log_rows)


def calibrate_import_decoupled(worst_hour_imp, bounds_df_imp, mall_bus, profiles, idx,
                                derate_line_idx, scoped_load_idx, derate_trafo_idx=None,
                                derate_bounds=CALIBRATION_DERATE_BOUNDS,
                                load_scale_bounds=CALIBRATION_UV_LOAD_SCALE_BOUNDS,
                                trafo_derate_bounds=CALIBRATION_DERATE_BOUNDS,
                                iters=BISECTION_ITERS, raise_on_unbracketed=True):
    """derate_trafo_idx may be empty (common on a pure MV feeder where the
    mall's own branch has no trafo on it) -- in that case the trafo axis is
    skipped entirely. If a trafo IS on the path but derating it within
    trafo_derate_bounds still never produces a violation (i.e. the
    transformer just isn't this feeder's bottleneck at the worst import
    hour), that axis is skipped too.

    Returns {"derate_only": (value, log_df), "load_scale_only": (value, log_df),
             "trafo_derate_only": (value_or_None, log_df)}."""

    def evaluate_derate(value):
        return evaluate_calibration_point(
            "import", worst_hour_imp, bounds_df_imp, mall_bus, profiles, idx,
            mode="derate", value=value, derate_line_idx=derate_line_idx)

    derate_threshold, derate_log = bisect_to_first_violation(
        evaluate_derate, bounds=derate_bounds, iters=iters,
        raise_on_unbracketed=raise_on_unbracketed)

    def evaluate_load_scale(value):
        return evaluate_calibration_point(
            "import", worst_hour_imp, bounds_df_imp, mall_bus, profiles, idx,
            mode="scale", value=value, scoped_load_idx=scoped_load_idx)

    load_scale_threshold, load_scale_log = bisect_to_first_violation(
        evaluate_load_scale, bounds=load_scale_bounds, iters=iters,
        raise_on_unbracketed=raise_on_unbracketed)

    if derate_trafo_idx:
        def evaluate_trafo_derate(value):
            return evaluate_calibration_point(
                "import", worst_hour_imp, bounds_df_imp, mall_bus, profiles, idx,
                mode="derate_trafo", value=value, derate_trafo_idx=derate_trafo_idx)

        try:
            trafo_derate_threshold, trafo_derate_log = bisect_to_first_violation(
                evaluate_trafo_derate, bounds=trafo_derate_bounds, iters=iters,
                raise_on_unbracketed=raise_on_unbracketed)
        except RuntimeError as exc:
            print(f"[CASE 1] Trafo-derate axis not binding within bounds "
                  f"{trafo_derate_bounds} at worst_hour_imp={worst_hour_imp} "
                  f"({exc}) -- treating trafo overload as non-binding for this "
                  f"mall_bus/grid_code, skipping the trafo-derate scenario.")
            trafo_derate_threshold, trafo_derate_log = None, pd.DataFrame()
    else:
        print("[CASE 1] No trafo sits on the mall's ext_grid-to-bus path -- "
              "skipping trafo-overload calibration axis.")
        trafo_derate_threshold, trafo_derate_log = None, pd.DataFrame()

    print(f"[CASE 1] derate only threshold = {derate_threshold:.4f} "
          f"(bounds {derate_bounds}); load_scale-only threshold = "
          f"{load_scale_threshold:.4f} (bounds {load_scale_bounds})"
          + (f"; trafo_derate-only threshold = {trafo_derate_threshold:.4f} "
             f"(bounds {trafo_derate_bounds})" if trafo_derate_threshold is not None else
             "; trafo_derate-only: not binding (skipped)"))

    return {"derate_only": (derate_threshold, derate_log),
            "load_scale_only": (load_scale_threshold, load_scale_log),
            "trafo_derate_only": (trafo_derate_threshold, trafo_derate_log)}


def print_calibration_spot_check(calib_df, chosen_value, direction, worst_hour, col="value"):
    matches = calib_df.loc[calib_df[col] == chosen_value]
    if matches.empty:
        print(f"[spot-check:{direction}] chosen value {chosen_value} has no exact log row "
            "(bisection may have converged between logged points) -- skipping detail print.")
        return
    row = matches.iloc[-1]
    print(f"[spot-check:{direction}] worst hour = {worst_hour}, chosen {col} = {chosen_value}, "
          f"violated = {bool(row['violated'])}, resolved by mall flex = {bool(row['resolved'])}, "
          f"power flow failed = {bool(row['pf_failed'])}")


# 10. OPF results row + closed-loop scenario runner

def build_opf_results(selected_time, scenario_label, status,
                        flex_activation_required, p_mall_min_mw, p_mall_base_mw,
                        p_mall_max_mw, p_mall_opf_mw, q_mall_opf_mvar,
                        p_grid_setpoint_kw, p_device_setpoint_kw,
                        mall_bus_vm_pu_before=np.nan, mall_bus_vm_pu_after=np.nan,
                        mall_feeder_line_loading_before_pct=np.nan,
                        mall_feeder_line_loading_after_pct=np.nan,
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
           "scenario": scenario_label,
           "status": status,
           "flex_activation_required": flex_activation_required,
           "p_min_mw": p_mall_min_mw,
           "p_base_mw": p_mall_base_mw,
           "p_max_mw": p_mall_max_mw,
           "p_opf_mw": p_mall_opf_mw,
           "q_opf_mvar": q_mall_opf_mvar,
           "p_grid_setpoint_kw": p_grid_setpoint_kw,
           "p_device_setpoint_kw": p_device_setpoint_kw,
           "grid_support_kw": grid_support_kw,
           "mall_bus_vm_pu_before": mall_bus_vm_pu_before,
           "mall_bus_vm_pu_after": mall_bus_vm_pu_after,
           "mall_feeder_line_loading_before_pct": mall_feeder_line_loading_before_pct,
           "mall_feeder_line_loading_after_pct": mall_feeder_line_loading_after_pct,
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


def run_opf_timeseries_for_scenario(scenario_label, direction, net_base, mall_load, mall_feeder_line_idx,
                                    profiles, idx, time_series_data_base, residual_mall_load_kw,
                                    grid_load_scale, grid_sgen_scale,
                                    q_mall_base_mvar, q_eps, initial_soc=0.0,
                                    scoped_sgen_idx=None, scoped_load_idx=None):
    updated_flex_target_kw = np.zeros(len(time_series_data_base))
    opf_rows = []
    res_base_rows = []
    res_actual_rows = []
    flex_bounds_rows = []
    violation_detail_rows = []

    soc_current = initial_soc
    prev_controller_results = {}
    prev_chp_downtime = {}

    n_hours = len(time_series_data_base)

    time_iter = time_series_data_base.index
    if _HAVE_TQDM:
        time_iter = tqdm(time_iter, desc=scenario_label, unit="hr", total=n_hours)

    for selected_time_idx, selected_time in enumerate(time_iter):
        if not _HAVE_TQDM and (selected_time_idx % 24 == 0 or selected_time_idx == n_hours - 1):
            print(f"[{scenario_label}] hour {selected_time_idx+1}/{n_hours} ({selected_time})", flush=True)

        time_series_t = time_series_data_base.iloc[[selected_time_idx]].copy()
        residual_t_kw = np.asarray([residual_mall_load_kw[selected_time_idx]])
        baseline_target_t_kw = np.array([0.0])

        start_t = selected_time.strftime("%Y-%m-%d %H:%M:%S")
        end_t = start_t

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
        if bounds_feasible:
            p_mall_min_mw = bounds_t.iloc[0]["p_mall_min_mw"]
            p_mall_max_mw = bounds_t.iloc[0]["p_mall_max_mw"]
        else:
            p_mall_min_mw = p_mall_base_mw
            p_mall_max_mw = p_mall_base_mw

        p_grid_setpoint_kw = p_mall_base_mw * 1000.0
        p_device_setpoint_kw = 0.0
        p_mall_opf_mw = p_mall_base_mw
        q_mall_opf_mvar = q_mall_base_mvar

        res_actual_t = res_base_t
        state_actual_t = state_base_t

        net = copy.deepcopy(net_base)
        apply_simbench_profile_for_hour(
            net, profiles, idx, selected_time,
            load_scale=grid_load_scale, sgen_scale=grid_sgen_scale,
            scoped_sgen_idx=scoped_sgen_idx,
            scoped_load_idx=scoped_load_idx)

        net.load.at[mall_load, "p_mw"] = p_mall_base_mw
        net.load.at[mall_load, "q_mvar"] = q_mall_base_mvar
        net.load.at[mall_load, "min_p_mw"] = p_mall_min_mw
        net.load.at[mall_load, "max_p_mw"] = p_mall_max_mw
        net.load.at[mall_load, "min_q_mvar"] = q_mall_base_mvar - q_eps
        net.load.at[mall_load, "max_q_mvar"] = q_mall_base_mvar + q_eps

        if not run_pf(net, context=f"[{scenario_label}] {selected_time} (baseline, mall attached)", print_error=False):
            status = "pf_with_mall_failed"
            flex_activation_required = False
            v_before = None
            violations_before = None
            v_after = None
            violations_after = None
            mall_vm_before = np.nan
            mall_vm_after = np.nan
            mall_line_before = np.nan
            mall_line_after = np.nan
        else:
            v_before = net.res_bus.vm_pu.copy()
            mall_vm_before = net.res_bus.at[net.load.at[mall_load, "bus"], "vm_pu"]
            mall_line_before = net.res_line.at[mall_feeder_line_idx, "loading_percent"]
            has_violation_before, violations_before = check_grid_violations(net)
            if has_violation_before:
                record_violation_details(violation_detail_rows, selected_time, "before", violations_before, net)

            if not has_violation_before:
                status = "no_violation_no_flex_needed"
                flex_activation_required = False
                v_after = v_before
                violations_after = violations_before
                mall_vm_after = mall_vm_before
                mall_line_after = mall_line_before
            elif not bounds_feasible:
                status = "flex_bounds_infeasible"
                flex_activation_required = True
                v_after = v_before
                violations_after = violations_before
                mall_vm_after = mall_vm_before
                mall_line_after = mall_line_before
            else:
                flex_activation_required = True
                p_mall_opf_mw = run_mall_opf(net, mall_load, p_mall_base_mw)

                opf_failed = p_mall_opf_mw is None

                if opf_failed:
                    has_overload = (len(violations_before["line_overload"]) > 0 or
                                     len(violations_before["trafo_overload"]) > 0)
                    pure_overvoltage = (len(violations_before["overvoltage"]) > 0 and
                                        len(violations_before["undervoltage"]) == 0 and
                                        not has_overload)

                    if pure_overvoltage:
                        fallback_candidates = [p_mall_max_mw, p_mall_min_mw]
                    else:
                        fallback_candidates = [p_mall_min_mw, p_mall_max_mw]

                    best_score = np.inf
                    best_p_mw = fallback_candidates[0]
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

                p_grid_setpoint_kw = p_mall_opf_mw * 1000.0
                p_device_setpoint_kw = residual_t_kw[0] - p_grid_setpoint_kw
                updated_flex_target_kw[selected_time_idx] = p_device_setpoint_kw

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

                p_actual_grid_mw = res_actual_t.iloc[0]["p_grid_kw"] / 1000.0
                net.load.at[mall_load, "p_mw"] = p_actual_grid_mw
                net.load.at[mall_load, "q_mvar"] = q_mall_opf_mvar

                if run_pf(net, context=f"[{scenario_label}] {selected_time} after actual dispatch", print_error=False):
                    v_after = net.res_bus.vm_pu.copy()
                    mall_vm_after = net.res_bus.at[net.load.at[mall_load, "bus"], "vm_pu"]
                    mall_line_after = net.res_line.at[mall_feeder_line_idx, "loading_percent"]
                    has_violation_after, violations_after = check_grid_violations(net)
                    if has_violation_after:
                        record_violation_details(violation_detail_rows, selected_time, "after", violations_after, net)

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
                    mall_vm_after = np.nan
                    mall_line_after = np.nan

        soc_current = res_actual_t.iloc[0]["soc_percent"] / 100.0
        prev_controller_results = state_actual_t["controller_results"]
        prev_chp_downtime = state_actual_t["chp_downtime"]

        res_actual_rows.append(res_actual_t.iloc[0])

        opf_rows.append(build_opf_results(selected_time=selected_time,
                                             scenario_label=scenario_label,
                                             status=status,
                                             flex_activation_required=flex_activation_required,
                                             p_mall_min_mw=p_mall_min_mw,
                                             p_mall_base_mw=p_mall_base_mw,
                                             p_mall_max_mw=p_mall_max_mw,
                                             p_mall_opf_mw=p_mall_opf_mw,
                                             q_mall_opf_mvar=q_mall_opf_mvar,
                                             p_grid_setpoint_kw=p_grid_setpoint_kw,
                                             p_device_setpoint_kw=p_device_setpoint_kw,
                                             mall_bus_vm_pu_before=mall_vm_before,
                                             mall_bus_vm_pu_after=mall_vm_after,
                                             mall_feeder_line_loading_before_pct=mall_line_before,
                                             mall_feeder_line_loading_after_pct=mall_line_after,
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

    violation_details_df = pd.DataFrame(
        violation_detail_rows,
        columns=["time", "phase", "violation_type", "element_id", "location", "value"])

    return opf_results_df, updated_flex_target_kw, res_base, res_actual, bounds_df, violation_details_df


# 11. Plotting + terminal summaries

def style_axis(ax, ylabel, title, legend_loc="upper right"):
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc=legend_loc)
    ax.grid(True, alpha=0.3)


def save_and_show(filename):
    plt.tight_layout()
    plt.savefig(filename)
    plt.show()


def print_scenario_summary(scenario_label, opf_results_df, violation_details_df, res_actual,
                            top_n_elements=5):
    """One consolidated box per scenario: how many hours violated, how many
    were resolved vs. remain (reinforcement candidates), tracking error, SOC
    range, total grid support energy, and the top few most frequently
    violated elements. Full hour-by-hour and per-violation detail is still
    available in the CSVs written by run_scenario -- this is a
    terminal-friendly digest, not a replacement for them."""
    status_counts = opf_results_df["status"].value_counts()
    n_total = len(opf_results_df)
    n_no_flex = status_counts.get("no_violation_no_flex_needed", 0)
    n_violated = n_total - n_no_flex
    n_resolved = (status_counts.get("opf_success_violations_resolved", 0)
                  + status_counts.get("opf_failed_fallback_resolved", 0))
    n_remaining = (status_counts.get("opf_success_remaining_violations", 0)
                   + status_counts.get("opf_failed_fallback_violations", 0))
    n_infeasible = status_counts.get("flex_bounds_infeasible", 0)
    n_pf_failed = (status_counts.get("pf_with_mall_failed", 0)
                   + status_counts.get("pf_after_ppros_update", 0))

    violated_pct = (n_violated / n_total * 100.0) if n_total else 0.0
    max_tracking_err = opf_results_df["tracking_error_kw"].abs().max() if "tracking_error_kw" in opf_results_df else np.nan
    soc_min = res_actual["soc_percent"].min() if len(res_actual) else np.nan
    soc_max = res_actual["soc_percent"].max() if len(res_actual) else np.nan
    total_support_mwh = opf_results_df["grid_support_kw"].sum() / 1000.0 if "grid_support_kw" in opf_results_df else np.nan

    print(f"\n{'-'*66}")
    print(f"[{scenario_label}] SCENARIO SUMMARY")
    print(f"{'-'*66}")
    print(f"  Hours processed:         {n_total}")
    print(f"  No flex needed:          {n_no_flex}")
    print(f"  Violated hours:          {n_violated} ({violated_pct:.0f}%)")
    print(f"    - resolved by mall:    {n_resolved}")
    print(f"    - remaining (reinforcement candidates): {n_remaining}")
    print(f"    - flex bounds infeasible: {n_infeasible}")
    if n_pf_failed:
        print(f"    - power-flow failed:   {n_pf_failed}")
    print(f"  Max tracking error:      {max_tracking_err:.3f} kW")
    print(f"  Thermal storage SOC:     {soc_min:.1f}% - {soc_max:.1f}%")
    print(f"  Total grid support:      {total_support_mwh:.2f} MWh")

    if not violation_details_df.empty:
        summary = (violation_details_df
                   .groupby(["violation_type", "location"])
                   .agg(occurrences=("value", "size"), worst_value=("value", "max"))
                   .sort_values("occurrences", ascending=False)
                   .head(top_n_elements))
        print(f"  Top {min(top_n_elements, len(summary))} violated elements "
              f"(full detail in grid_violation_details_{scenario_label}.csv):")
        for (vtype, loc), row in summary.iterrows():
            print(f"    {loc:22s} {vtype:15s} {int(row['occurrences']):4d} occurrence(s), "
                  f"worst = {row['worst_value']:.2f}")
    print(f"{'-'*66}\n")


def plot_single_line_diagram(net, mall_bus=MALL_BUS, savepath="grid_single_line_diagram.png", title=None):
    import json as _json

    if mall_bus in net.bus.index:
        mall_lines = net.line[(net.line.from_bus == mall_bus) | (net.line.to_bus == mall_bus)]
        print(f"\n[mall connection] bus {mall_bus} connects via {len(mall_lines)} line(s):")
        for li, row in mall_lines.iterrows():
            other = row["to_bus"] if row["from_bus"] == mall_bus else row["from_bus"]
            print(f"    line {li} ('{row.get('name', '')}') <-> bus {other}")
        mall_trafos = net.trafo[(net.trafo.hv_bus == mall_bus) | (net.trafo.lv_bus == mall_bus)]
        if len(mall_trafos):
            print(f"    also directly on {len(mall_trafos)} trafo(s): {list(mall_trafos.index)}")

    branch_of = compute_hierarchical_layout(net)

    bus_size = pp_plot.get_collection_sizes(net)["bus"]

    palette = ["tab:blue", "tab:orange", "tab:green", "tab:purple", "tab:brown",
               "tab:olive", "tab:cyan", "tab:pink", "tab:gray", "gold"]

    other_buses = net.bus.index.drop(mall_bus) if mall_bus in net.bus.index else net.bus.index

    collections = [
        pp_plot.create_line_collection(net, lines=net.line.index, color="grey", linewidths=1.0, zorder=1),
    ]

    if branch_of:
        for b in other_buses:
            branch_id = branch_of.get(b, -1)
            color = "black" if branch_id == -1 else palette[branch_id % len(palette)]
            collections.append(
                pp_plot.create_bus_collection(net, buses=[b], size=bus_size, color=color, zorder=2)
            )
    else:
        collections.append(
            pp_plot.create_bus_collection(net, buses=other_buses, size=bus_size, color="tab:blue", zorder=2)
        )

    if len(net.trafo):
        tc, tc_patch = pp_plot.create_trafo_collection(net, trafos=net.trafo.index, size=bus_size * 2, color="black")
        collections += [tc, tc_patch]
    if len(net.load):
        collections.append(pp_plot.create_load_collection(net, loads=net.load.index, size=bus_size * 1.5))
    if len(net.sgen):
        collections.append(pp_plot.create_sgen_collection(net, sgens=net.sgen.index, size=bus_size * 1.5))
    if len(net.ext_grid):
        collections.append(pp_plot.create_ext_grid_collection(net, ext_grids=net.ext_grid.index, size=bus_size * 2))
    if mall_bus in net.bus.index:
        collections.append(pp_plot.create_bus_collection(net, buses=[mall_bus], size=bus_size * 4,
                                                          color="tab:red", zorder=5))

    ax = pp_plot.draw_collections(collections, figsize=(18, 11))

    for bus_idx in net.bus.index:
        geo_str = net.bus.at[bus_idx, "geo"]
        if pd.isna(geo_str):
            continue
        coords = _json.loads(geo_str)["coordinates"]
        ax.annotate(str(bus_idx), xy=(coords[0], coords[1]), xytext=(4, 4),
                    textcoords="offset points", fontsize=7, color="black", zorder=6)

    ax.set_title(title or f"{GRID_CODE} -- mall connected directly at bus {mall_bus} (red)")
    plt.tight_layout()
    plt.savefig(savepath, dpi=130, bbox_inches="tight")
    plt.show()
    return ax


def plot_prosumer_participation(opf_results_df, scenario_label):
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True)

    ax = axes[0]
    ax.plot(opf_results_df.index, opf_results_df["p_base_mw"], label="Baseline import (no flex)",
            linestyle="--", color="tab:gray")
    ax.plot(opf_results_df.index, opf_results_df["p_opf_mw"], label="Actual setpoint (closed loop)",
            color="tab:blue")
    ax.axhline(0, color="black", linewidth=0.8)
    style_axis(
        ax, "Mall grid power [MW]\n(+ import / - export)",
        f"[{scenario_label}] Closed-loop prosumer import/export: baseline vs. flexibility-adjusted")

    ax = axes[1]
    ax.plot(opf_results_df.index, opf_results_df["mall_feeder_line_loading_before_pct"],
            label="Mall feeder line loading before OPF", linestyle="--", color="tab:gray")
    ax.plot(opf_results_df.index, opf_results_df["mall_feeder_line_loading_after_pct"],
            label="Mall feeder line loading after OPF", color="tab:green")
    ax.axhline(100.0, color="tab:red", linestyle=":", label="100% (limit)")
    ax.set_xlabel("Time")
    style_axis(
        ax, "Mall feeder line loading [%]",
        f"[{scenario_label}] Mall's own feeder line loading: before vs. after flexibility")

    save_and_show(f"prosumer_grid_participation_{scenario_label}.png")


def plot_soc_and_tracking(opf_results_df, res_actual, scenario_label):
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

    ax = axes[0]
    ax.plot(res_actual.index, res_actual["soc_percent"], label="Thermal storage SOC", color="tab:purple")
    style_axis(
        ax, "SOC [%]", f"[{scenario_label}] Thermal storage SOC across the closed-loop run")

    ax = axes[1]
    ax.plot(opf_results_df.index, opf_results_df["p_grid_setpoint_kw"], label="OPF/fallback grid setpoint (kW)")
    ax.plot(opf_results_df.index, opf_results_df["p_updated_grid_kw"], linestyle="--",
            label="Actual pandaprosumer grid power (kW)")
    ax.set_xlabel("Time")
    style_axis(
        ax, "Power [kW]", f"[{scenario_label}] Closed-loop setpoint tracking")

    save_and_show(f"prosumer_soc_tracking_{scenario_label}.png")


def plot_scenario_diagnostics(opf_results_df, res_actual, scenario_label):
    """Convenience wrapper: renders both the participation chart and the
    SOC/tracking chart for a scenario in one call."""
    plot_prosumer_participation(opf_results_df, scenario_label)
    plot_soc_and_tracking(opf_results_df, res_actual, scenario_label)


# 12. Scenario runner

def run_scenario(scenario_label, direction, ses_data_1h_full, heat_data_file,
                  window_start, window_end, mall_bus=MALL_BUS,
                  grid_load_scale=1.0, grid_sgen_scale=1.0,
                  mall_pv_scale=1.0, capacity_derate=1.0,
                  capacity_derate_trafo=1.0, derate_trafo_idx=None,
                  profiles=None, idx=None,
                  derate_line_idx=None, scoped_sgen_idx=None, scoped_load_idx=None):

    print(f"\n{'='*70}\nSCENARIO: {scenario_label} (direction={direction})\n"
          f"Window: {window_start} to {window_end} (exclusive)\n"
          f"Mall bus: {mall_bus} on {GRID_CODE} | "
          f"grid_load_scale={grid_load_scale} grid_sgen_scale={grid_sgen_scale} "
          f"mall_pv_scale={mall_pv_scale} capacity_derate={capacity_derate} "
          f"capacity_derate_trafo={capacity_derate_trafo} "
          f"derate_line_idx={derate_line_idx} derate_trafo_idx={derate_trafo_idx} "
          f"scoped_sgen_idx={scoped_sgen_idx} "
          f"scoped_load_idx={scoped_load_idx}\n{'='*70}")

    if ses_data_1h_full.index.min() > window_start or ses_data_1h_full.index.max() < window_end - pd.Timedelta(hours=1):
        raise RuntimeError(f"[{scenario_label}] SES data does not cover the requested window.")

    ses_data_1h = ses_data_1h_full.loc[window_start:window_end - pd.Timedelta(hours=1)]

    start = ses_data_1h.index.min().strftime("%Y-%m-%d %H:%M:%S")
    end = ses_data_1h.index.max().strftime("%Y-%m-%d %H:%M:%S")

    p_el_sc_kw = ses_data_1h["P el sc [kW]"].astype(float).to_numpy()
    p_pv_kw = ses_data_1h["P pv [kW]"].astype(float).to_numpy()
    residual_mall_load_kw = p_el_sc_kw - p_pv_kw * mall_pv_scale
    n_steps = len(residual_mall_load_kw)

    print(f"[{scenario_label}] Start: {start}  End: {end}  Steps: {n_steps}")
    print(f"[{scenario_label}] Residual mall load min/max: "
          f"{residual_mall_load_kw.min():.3f} / {residual_mall_load_kw.max():.3f} kW")

    time_series_data = build_time_series_data(residual_mall_load_kw, start, n_steps, heat_data_file)

    if profiles is None or idx is None:
        net_template = get_net_template(GRID_CODE)
        profiles = sb.get_absolute_values(net_template, profiles_instead_of_study_cases=True)
        idx = pd.date_range(YEAR_START, periods=len(profiles[("load", "p_mw")]), freq="15min")

    q_mall_base_mvar = 0.0
    q_eps = IMPORT_Q_EPS_MVAR
    net_base, mall_load, mall_feeder_line_idx = build_base_net(
        mall_bus=mall_bus, q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps,
        capacity_derate=capacity_derate, derate_line_idx=derate_line_idx,
        capacity_derate_trafo=capacity_derate_trafo, derate_trafo_idx=derate_trafo_idx)

    print(f"[{scenario_label}] Running closed-loop prosumer + grid OPF ({n_steps} hourly steps)...")

    (opf_results_df, updated_flex_target_kw, res_base, res_actual,
     bounds_df, violation_details_df) = run_opf_timeseries_for_scenario(
        scenario_label=scenario_label, direction=direction,
        net_base=net_base, mall_load=mall_load, mall_feeder_line_idx=mall_feeder_line_idx,
        profiles=profiles, idx=idx,
        time_series_data_base=time_series_data,
        residual_mall_load_kw=residual_mall_load_kw,
        grid_load_scale=grid_load_scale, grid_sgen_scale=grid_sgen_scale,
        q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps,
        initial_soc=0.0, scoped_sgen_idx=scoped_sgen_idx, scoped_load_idx=scoped_load_idx)

    opf_results_df["p_updated_grid_kw"] = res_actual["p_grid_kw"].reindex(opf_results_df.index)
    opf_results_df["tracking_error_kw"] = opf_results_df["p_updated_grid_kw"] - opf_results_df["p_grid_setpoint_kw"]

    opf_results_df.to_csv(f"grid_opf_timeseries_results_{scenario_label}.csv")
    bounds_df.to_csv(f"grid_flexibility_bounds_{scenario_label}.csv")
    violation_details_df.to_csv(f"grid_violation_details_{scenario_label}.csv", index=False)

    print_scenario_summary(scenario_label, opf_results_df, violation_details_df, res_actual)

    plot_scenario_diagnostics(opf_results_df, res_actual, scenario_label)

    return opf_results_df, bounds_df, residual_mall_load_kw, violation_details_df


def run_for_grid(ses_data_1h_full, best_import_row, grid_code=None):
    global GRID_CODE
    if grid_code is not None:
        GRID_CODE = grid_code

    print(f"\n{'%'*70}\n{GRID_CODE}\n{'%'*70}")

    net_template = get_net_template(GRID_CODE)
    profiles = sb.get_absolute_values(net_template, profiles_instead_of_study_cases=True)
    idx = pd.date_range(YEAR_START, periods=len(profiles[("load", "p_mw")]), freq="15min")
    load_p_15min = pd.DataFrame(profiles[("load", "p_mw")], index=idx)
    load_p_1h = load_p_15min.resample("60min").mean()   # aligned to match SES's 1h resolution
    sgen_p_15min = pd.DataFrame(profiles[("sgen", "p_mw")], index=idx)
    sgen_p_1h = sgen_p_15min.resample("60min").mean()

    weakest_leaf_bus, weakest_line = find_weakest_branch_leaf_bus(net_template)
    MALL_BUS_RESOLVED = weakest_leaf_bus

    print(f"\n[MALL_BUS RESOLUTION] auto-detected weakest-branch leaf bus: {MALL_BUS_RESOLVED} "
          f"(via most-loaded line {weakest_line}) ")

    derate_line_idx = find_path_lines_to_bus(net_template, MALL_BUS_RESOLVED)
    derate_trafo_idx = find_path_trafos_to_bus(net_template, MALL_BUS_RESOLVED)
    _, downstream_load_idx, downstream_buses = find_downstream_elements(
        net_template, MALL_BUS_RESOLVED)

    print(f"[grid diagnostic] mall's own branch: {len(derate_line_idx)} line(s) from ext_grid to bus "
          f"{MALL_BUS_RESOLVED}: {derate_line_idx}")
    print(f"[grid diagnostic] {len(derate_trafo_idx)} trafo(s) on that same path: {derate_trafo_idx}")
    print(f"[grid diagnostic] {len(downstream_load_idx)} load(s) share the mall's branch "
          f"(downstream buses: {sorted(downstream_buses)})")

    print("\n=== Plotting single-line diagram (mall connection point highlighted) ===")
    plot_single_line_diagram(net_template, mall_bus=MALL_BUS_RESOLVED)

    # CASE 1: import -- two (or three) independent single-axis scenarios
    import_window_end = best_import_row["window_end"] + pd.Timedelta(hours=1)
    import_window_start = best_import_row["window_start"]

    p_el_sc_kw_imp = ses_data_1h_full.loc[import_window_start:import_window_end - pd.Timedelta(hours=1), "P el sc [kW]"].astype(float).to_numpy()
    p_pv_kw_imp = ses_data_1h_full.loc[import_window_start:import_window_end - pd.Timedelta(hours=1), "P pv [kW]"].astype(float).to_numpy()
    residual_mall_load_kw_imp = p_el_sc_kw_imp - p_pv_kw_imp
    n_steps_imp = len(residual_mall_load_kw_imp)
    start_imp = import_window_start.strftime("%Y-%m-%d %H:%M:%S")
    end_imp = (import_window_end - pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    time_series_data_imp = build_time_series_data(residual_mall_load_kw_imp, start_imp, n_steps_imp, heat_data_file)

    print(f"\n=== [CASE 1: import/stress] Computing prosumer flexibility bounds for calibration ===")

    _, bounds_df_imp = run_mall_case_with_bounds(
        time_series_data_base=time_series_data_imp,
        flex_target_kw=np.zeros(n_steps_imp),
        residual_mall_load_kw=residual_mall_load_kw_imp,
        start=start_imp, end=end_imp,
        time_resolution=time_resolution, frequency=frequency,
        collect_bounds=True, allow_export=allow_export_to_grid,
        verbose=False)
    bounds_df_imp.index = bounds_df_imp.index.tz_localize(None)

    worst_hour_imp = find_worst_hour_proxy(
        "import", import_window_start, import_window_end, residual_mall_load_kw_imp, load_p_1h, sgen_p_1h)

    print("\n=== [CASE 1] Calibrating scoped line-capacity derate and scoped real load scale "
          f"INDEPENDENTLY ({len(derate_line_idx)} line(s), {len(downstream_load_idx)} load(s) "
          "on the mall's own branch) -- standalone single-axis violations ===")

    decoupled = calibrate_import_decoupled(
        worst_hour_imp, bounds_df_imp, MALL_BUS_RESOLVED, profiles, idx,
        derate_line_idx=derate_line_idx, scoped_load_idx=downstream_load_idx,
        derate_trafo_idx=derate_trafo_idx)

    chosen_capacity_derate, calib_derate = decoupled["derate_only"]
    chosen_import_load_scale, calib_load = decoupled["load_scale_only"]
    chosen_trafo_derate, calib_trafo_derate = decoupled["trafo_derate_only"]

    print(f"[CASE 1] Chosen capacity_derate (derate-only) = {chosen_capacity_derate:.4f}")
    print(f"[CASE 1] Chosen load_scale (load-only) = {chosen_import_load_scale:.4f}")

    print_calibration_spot_check(calib_derate, chosen_capacity_derate, "import_derate", worst_hour_imp)
    print_calibration_spot_check(calib_load, chosen_import_load_scale, "import_load", worst_hour_imp)

    if chosen_trafo_derate is not None:
        print(f"[CASE 1] Chosen trafo capacity_derate (trafo-derate-only) = {chosen_trafo_derate:.4f}")
        print_calibration_spot_check(calib_trafo_derate, chosen_trafo_derate, "import_trafo_derate", worst_hour_imp)

    run_scenario("import_derate_only_window", "import", ses_data_1h_full, heat_data_file,
                 import_window_start, import_window_end,
                 mall_bus=MALL_BUS_RESOLVED,
                 grid_load_scale=1.0, grid_sgen_scale=1.0,
                 capacity_derate=chosen_capacity_derate,
                 derate_line_idx=derate_line_idx,
                 profiles=profiles, idx=idx)

    run_scenario("import_load_only_window", "import", ses_data_1h_full, heat_data_file,
                 import_window_start, import_window_end,
                 mall_bus=MALL_BUS_RESOLVED,
                 grid_load_scale=chosen_import_load_scale, grid_sgen_scale=1.0,
                 capacity_derate=1.0,
                 scoped_load_idx=downstream_load_idx,
                 profiles=profiles, idx=idx)

    if chosen_trafo_derate is not None:
        run_scenario("import_trafo_derate_only_window", "import", ses_data_1h_full, heat_data_file,
                     import_window_start, import_window_end,
                     mall_bus=MALL_BUS_RESOLVED,
                     grid_load_scale=1.0, grid_sgen_scale=1.0,
                     capacity_derate=1.0,
                     capacity_derate_trafo=chosen_trafo_derate,
                     derate_trafo_idx=derate_trafo_idx,
                     profiles=profiles, idx=idx)
    else:
        print("[CASE 1] Skipping import_trafo_derate_only_window scenario -- "
              "no trafo on the mall's ext_grid-to-bus path, or the trafo axis "
              "was not binding within the tested calibration bounds.")


# 13. Main workflow

def main(grid_codes=None):
    if grid_codes is None:
        grid_codes = [GRID_CODE]

    print("\n=== Scanning full SES year for best 8-day windows ===")
    ses_data_1h_full, scan_df, best_export_row, best_import_row = load_and_scan_ses_data(
        ses_data_file, window_days=WINDOW_DAYS)
    print(f"Best EXPORT window: {best_export_row['window_start']} to {best_export_row['window_end']} "
          f"(summed residual = {best_export_row['residual_sum_kwh']:.1f} kWh, "
          f"peak export = {-best_export_row['residual_peak_export_kw']:.1f} kW) "
          f"-- kept for future reference only; no export scenario is run (Case 2 removed).")
    print(f"Best IMPORT/STRESS window: {best_import_row['window_start']} to {best_import_row['window_end']} "
          f"(peak import = {best_import_row['residual_peak_import_kw']:.1f} kW)")

    for grid_code in grid_codes:
        run_for_grid(ses_data_1h_full, best_import_row, grid_code=grid_code)


if __name__ == "__main__":
    main()