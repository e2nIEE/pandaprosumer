import warnings
import copy
import os
import sys
from pathlib import Path
from contextlib import contextmanager

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import networkx as nx

import pandapower as pp
import pandapower.plotting as pp_plot
import pandapower.topology as pp_topology

from minihyper.run import run_full_job

try:
    from tqdm import tqdm
    _HAVE_TQDM = True
except ImportError:
    _HAVE_TQDM = False


### 1. Terminal / environment setup

@contextmanager
def suppress_native_stdout():
    """Suppresses the HiGHS/PDIPM solver banners that pandapower's OPF
    prints straight to the OS-level stdout."""
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


warnings.filterwarnings("ignore", category=FutureWarning, module="pandapower")
pd.set_option('future.no_silent_downcasting', True)


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
heat_data_file = project_root / "tutorials_extended" / "data" / "aleja_heat_demand_model_data.xlsx"
ses_data_file = project_root / "tutorials_extended" / "data" / "ses_data.xlsx"

NET_LABEL = "Synthetic LV Test Feeder"

N_STEPS = 192                                   # simulation length (hourly steps)
SERIES_START = pd.Timestamp("2025-01-01 00:00:00")
window_start = pd.Timestamp("2025-12-13 00:00:00")
### Grid violation thresholds

v_min_pu_std = 0.90
v_max_pu_std = 1.10
loading_percent_max_std = 100.0

allow_export_to_grid = True

USE_NUMBA = False
VERBOSE_OPF_FAILURES = False

### reactive-power headroom for the mall load (kept ~0 throughout).

MALL_Q_EPS_MVAR = 1e-6

N_BACKGROUND_LOADS = 9
VN_KV = 0.4                          # LV-Netz, bewusst kein Trafo

TRUNK_SEGMENT_LENGTH_KM = 0.05       # ein Verteilleitungs-Segment pro Hintergrundlast
TRUNK_R_OHM_PER_KM = 0.10
TRUNK_X_OHM_PER_KM = 0.08
TRUNK_MAX_I_KA = 0.35                 # Backbone: für Hintergrund allein ok, mit Mall überlastet

MALL_FEEDER_LENGTH_KM = 0.15          # Mall ist letzter Kunde am Strang
MALL_FEEDER_R_OHM_PER_KM = 0.10
MALL_FEEDER_X_OHM_PER_KM = 0.08
MALL_FEEDER_MAX_I_KA = 0.30           # bewusst unterdimensionierte Stichleitung

BACKGROUND_Q_OVER_P_RATIO = 0.2

FEEDER_LOAD_COUNTS = {0: 2, 1: 3, 2: 3}   # Feeder 0: 2 Mainline-Lasten + 1 Lateral-Last = 9 gesamt


LATERAL_SEGMENT_LENGTH_KM = 0.04
LATERAL_R_OHM_PER_KM = 0.12
LATERAL_X_OHM_PER_KM = 0.09
LATERAL_MAX_I_KA = 0.20


BACKGROUND_P_MIN_MW = 0.005            # vorher 0.008 -> "etwas weniger Last"
BACKGROUND_P_MAX_MW = 0.012            # vorher 0.018


SGEN_P_MAX_MW = 0.05
SGEN_Q_MVAR = 0.0


### 2. Synthetic mall demand profile (replaces the SES Excel workbook)

def load_full_ses_data(path):
    """Unveraendert aus dem urspruenglichen Skript."""
    ses_data = pd.read_excel(path)
    ses_data.columns = ses_data.columns.str.strip()
    ses_data = ses_data.set_index("Timestamp").sort_index()

    required_cols = ["P el sc [kW]", "P pv [kW]"]
    for col in required_cols:
        ses_data[col] = ses_data[col].astype(str).str.replace(",", ".", regex=False)
        ses_data[col] = pd.to_numeric(ses_data[col], errors="coerce")
    ses_data = ses_data.dropna(subset=required_cols)

    return ses_data[required_cols].resample("60min").mean().dropna(subset=required_cols)


MALL_LOAD_SES_SCALE = 1.0   # Stellschraube gegen zu viele/wenige Verletzungen
MALL_PV_SES_SCALE = 1.0


def get_mall_residual_load_kw_from_ses(ses_data_1h_full, n_steps, window_start=None,
                                        load_scale=MALL_LOAD_SES_SCALE, pv_scale=MALL_PV_SES_SCALE):
    """Liest P_el_sc - P_pv aus der echten SES-Zeitreihe statt einer
    synthetischen Kurve. window_start=None -> erste n_steps Stunden des
    Datensatzes (bewusst KEINE Worst-Case-Fenstersuche mehr -> weniger,
    moderatere Verletzungen als im urspruenglichen Kalibrierungs-Ansatz)."""
    if window_start is None:
        window = ses_data_1h_full.iloc[:n_steps]
    else:
        window_start = pd.Timestamp(window_start)
        window = ses_data_1h_full.loc[window_start:window_start + pd.Timedelta(hours=n_steps - 1)]

    if len(window) < n_steps:
        raise RuntimeError(
            f"SES-Datensatz liefert nur {len(window)} von {n_steps} angeforderten Stunden "
            "-- window_start anpassen oder n_steps reduzieren.")

    p_el_sc_kw = window["P el sc [kW]"].astype(float).to_numpy() * load_scale
    p_pv_kw = window["P pv [kW]"].astype(float).to_numpy() * pv_scale
    return p_el_sc_kw - p_pv_kw, window.index

def generate_synthetic_background_load_profiles_mw(background_load_idx, n_steps=N_STEPS, seed=7,
                                                     p_min_mw=BACKGROUND_P_MIN_MW,
                                                     p_max_mw=BACKGROUND_P_MAX_MW,
                                                     noise_std_mw=0.0007):
    """Synthetisches Stundenprofil [MW] je Hintergrundlast -- eine eigene,
    leicht phasenverschobene Tagesgangkurve pro Last, damit sie nicht alle
    exakt synchron schwanken. Ersetzt die frueher genutzten
    Simbench-Lastprofile. Selbst im (unwahrscheinlichen) Fall, dass alle
    Hintergrundlasten gleichzeitig ihr Maximum erreichen, bleibt das Netz
    OHNE Mall unterhalb der Grenzwerte -- die Verletzung entsteht
    ausschliesslich durch die Mall.

    Returns: DataFrame, Index=0..n_steps-1, Spalten=background_load_idx.
    """
    rng = np.random.default_rng(seed)
    hour_of_day = np.arange(n_steps, dtype=float) % 24.0

    profiles = {}
    for load_idx in background_load_idx:
        phase_h = rng.uniform(-2.0, 2.0)
        scale = rng.uniform(0.85, 1.15)
        shape = np.clip(0.5 + 0.5 * np.sin(2 * np.pi * (hour_of_day - 18.0 + phase_h) / 24.0), 0.0, 1.0)
        base_mw = (p_min_mw + (p_max_mw - p_min_mw) * shape) * scale
        noise_mw = rng.normal(0.0, noise_std_mw, size=n_steps)
        profiles[load_idx] = np.clip(base_mw + noise_mw, 0.3 * p_min_mw, 1.3 * p_max_mw)

    return pd.DataFrame(profiles)

def generate_synthetic_sgen_profile_mw(sgen_idx, n_steps=N_STEPS, seed=11,
                                        p_max_mw=SGEN_P_MAX_MW, noise_std_mw=0.003):
    """Tagesabhaengiges PV-Einspeiseprofil (Glockenkurve um die Mittagsstunde,
    nachts 0) fuer den einen sgen im Netz."""
    rng = np.random.default_rng(seed)
    hour_of_day = np.arange(n_steps, dtype=float) % 24.0

    solar_shape = np.clip(np.cos(2 * np.pi * (hour_of_day - 12.0) / 24.0), 0.0, 1.0) ** 2
    p_mw = p_max_mw * solar_shape + rng.normal(0.0, noise_std_mw, size=n_steps)
    return pd.Series(np.clip(p_mw, 0.0, p_max_mw), name=sgen_idx)


def apply_sgen_profile_for_hour(net, sgen_profile_mw, sgen_idx, step_idx):
    net.sgen.at[sgen_idx, "p_mw"] = float(sgen_profile_mw.iat[step_idx])

def apply_background_profile_for_hour(net, background_profile_mw, background_load_idx, step_idx):
    """Schreibt den synthetischen P-Wert dieser Stunde (plus Q ueber
    konstanten Leistungsfaktor) in die Hintergrundlasten. Die Mall-Last
    wird hier NICHT beruehrt -- sie kommt ausschliesslich aus dem
    pandaprosumer-Regelkreis weiter unten in der Zeitschleife
    (p_mall_base_mw / p_mall_opf_mw)."""
    for load_idx in background_load_idx:
        p_mw = float(background_profile_mw.at[step_idx, load_idx])
        net.load.at[load_idx, "p_mw"] = p_mw
        net.load.at[load_idx, "q_mvar"] = BACKGROUND_Q_OVER_P_RATIO * p_mw

def build_time_series_data(residual_mall_load_kw, start, n_steps, heat_data_file):
    """Unchanged: builds the prosumer's heat-demand time series (from the
    Excel workbook) for n_steps. residual_mall_load_kw is accepted for
    interface compatibility but (as before) unused inside this function."""
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


### 3. pprosumer model (unchanged)

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

    q_capacity_kwh = 20000
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


### 4. pprosumer run with controller-based bounds (unchanged)

def run_mall_case_with_bounds(time_series_data_base, flex_target_kw, residual_mall_load_kw,
                              start, end, time_resolution, frequency, collect_bounds=False,
                              allow_export=False, init_soc=0.0, previous_controller_results=None,
                              previous_chp_downtime=None, return_state=False, verbose=False):

    prosumer, period, optimization_controller = build_mall_prosumer(time_series_data_base=time_series_data_base, flex_target_kw=flex_target_kw,
                                                                    start=start, end=end, time_resolution=time_resolution,
                                                                    frequency=frequency, collect_bounds=collect_bounds, init_soc=init_soc,
                                                                    previous_controller_results=previous_controller_results,
                                                                    previous_chp_downtime=previous_chp_downtime)

    with suppress_native_stdout():
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


### 5. pandapower grid preparation + OPF integration

def fix_element_dtypes(net):
    """Fixes bool columns pandas may have broken (in_service/controllable),
    and forces tap_dependency_table off on trafos (if any)."""
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


def prepare_grid_for_opf(net):
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


### 6. Layout helper (only used for the single-line-diagram plot)

def compute_hierarchical_layout(net):
    """Fills in net.bus.geo (in place) for any bus missing geo data, using a
    feeder tree layout rooted at the ext_grid bus, and returns a
    {bus: branch_id} map (branch_id=-1 for the root/trunk)."""
    import json as _json

    geo = net.bus.geo
    missing_geo = geo.isna() | (geo.astype(str).str.strip() == "") | (geo.astype(str) == "None")
    if not missing_geo.any():
        return {}

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


### 7. Synthetic net (replaces the Simbench net + weakest-branch detection)




def _add_feeder(net, slack_bus, feeder_id, n_loads):
    """Baut einen radialen Feeder-Strang mit n_loads Lasten (jede an ihrem
    eigenen Trunk-Bus, in Reihe). Gibt (load_idx_list, last_bus) zurueck."""
    load_idx_list = []
    prev_bus = slack_bus
    for i in range(n_loads):
        bus = pp.create_bus(net, vn_kv=VN_KV, name=f"Feeder {feeder_id} bus {i + 1}")
        pp.create_line_from_parameters(
            net, from_bus=prev_bus, to_bus=bus, length_km=TRUNK_SEGMENT_LENGTH_KM,
            r_ohm_per_km=TRUNK_R_OHM_PER_KM, x_ohm_per_km=TRUNK_X_OHM_PER_KM,
            c_nf_per_km=250.0, max_i_ka=TRUNK_MAX_I_KA,
            name=f"Feeder {feeder_id} line {i + 1}")

        load_idx = pp.create_load(net, bus=bus, p_mw=0.0, q_mvar=0.0,
                                   name=f"Feeder {feeder_id} load {i + 1}")
        load_idx_list.append(load_idx)
        prev_bus = bus
    return load_idx_list, prev_bus


def build_base_net(q_mall_base_mvar=0.0, q_eps=1e-3):
    """Baut ein verzweigtes synthetisches NS-Netz: 3 Feeder ab dem Slack-Bus,
    Feeder 0 hat zusaetzlich einen Lateral-Abzweig (1 Last + 1 sgen), und am
    Ende von Feeder 2 haengt die Mall ueber eine bewusst unterdimensionierte
    Stichleitung. Kein Transformator -- ext_grid liegt direkt auf NS-Ebene.

    Returns: (net, mall_load_idx, mall_feeder_line_idx, background_load_idx, sgen_idx)
    """
    net = pp.create_empty_network(f_hz=50.0, sn_mva=1.0)

    slack_bus = pp.create_bus(net, vn_kv=VN_KV, name="Feeder head (ext_grid)")
    pp.create_ext_grid(net, bus=slack_bus, vm_pu=1.0, name="Grid Connection")

    background_load_idx = []

    # Feeder 0 -- bekommt zusaetzlich einen Lateral-Abzweig (mehr Verzweigung)
    feeder0_loads, _ = _add_feeder(net, slack_bus, feeder_id=0, n_loads=FEEDER_LOAD_COUNTS[0])
    background_load_idx += feeder0_loads

    lateral_tap_bus = net.load.at[feeder0_loads[-1], "bus"]
    lateral_bus = pp.create_bus(net, vn_kv=VN_KV, name="Feeder 0 lateral bus")
    pp.create_line_from_parameters(
        net, from_bus=lateral_tap_bus, to_bus=lateral_bus, length_km=LATERAL_SEGMENT_LENGTH_KM,
        r_ohm_per_km=LATERAL_R_OHM_PER_KM, x_ohm_per_km=LATERAL_X_OHM_PER_KM,
        c_nf_per_km=250.0, max_i_ka=LATERAL_MAX_I_KA, name="Feeder 0 lateral line")

    lateral_load_idx = pp.create_load(net, bus=lateral_bus, p_mw=0.0, q_mvar=0.0,
                                       name="Feeder 0 lateral load")
    background_load_idx.append(lateral_load_idx)

    sgen_idx = pp.create_sgen(net, bus=lateral_bus, p_mw=0.0, q_mvar=SGEN_Q_MVAR,
                               max_p_mw=SGEN_P_MAX_MW, min_p_mw=0.0, name="Background PV")

    # Feeder 1 -- einfacher radialer Strang
    feeder1_loads, _ = _add_feeder(net, slack_bus, feeder_id=1, n_loads=FEEDER_LOAD_COUNTS[1])
    background_load_idx += feeder1_loads

    # Feeder 2 -- an dessen Ende die Mall haengt
    feeder2_loads, feeder2_last_bus = _add_feeder(net, slack_bus, feeder_id=2, n_loads=FEEDER_LOAD_COUNTS[2])
    background_load_idx += feeder2_loads

    mall_bus = pp.create_bus(net, vn_kv=VN_KV, name="Mall connection bus")
    mall_feeder_line_idx = pp.create_line_from_parameters(
        net, from_bus=feeder2_last_bus, to_bus=mall_bus, length_km=MALL_FEEDER_LENGTH_KM,
        r_ohm_per_km=MALL_FEEDER_R_OHM_PER_KM, x_ohm_per_km=MALL_FEEDER_X_OHM_PER_KM,
        c_nf_per_km=250.0, max_i_ka=MALL_FEEDER_MAX_I_KA, name="Mall feeder line (undersized)")

    fix_element_dtypes(net)
    prepare_grid_for_opf(net)

    mall_load_idx = pp.create_load(net, bus=mall_bus,
                                    p_mw=0.0, q_mvar=q_mall_base_mvar,
                                    name="Shopping Mall load", controllable=True,
                                    min_p_mw=0.0, max_p_mw=0.0,
                                    min_q_mvar=q_mall_base_mvar - q_eps,
                                    max_q_mvar=q_mall_base_mvar + q_eps)

    return net, mall_load_idx, mall_feeder_line_idx, background_load_idx, sgen_idx


### 8. OPF results row + closed-loop timeseries runner

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


def run_opf_timeseries_for_scenario(scenario_label, net_base, mall_load, mall_feeder_line_idx,
                                     background_profile_mw, background_load_idx,
                                     sgen_profile_mw, sgen_idx,                      # NEU
                                     time_series_data_base, residual_mall_load_kw,
                                     q_mall_base_mvar, q_eps, initial_soc=0.0):
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
    violated_nets_dict = {}

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
        apply_background_profile_for_hour(net, background_profile_mw, background_load_idx,
                                          selected_time_idx)
        apply_sgen_profile_for_hour(net, sgen_profile_mw, sgen_idx, selected_time_idx)  # NEU

        net.load.at[mall_load, "p_mw"] = p_mall_base_mw
        # background loads are already fixed inside net_base and stay
        # constant across the run -- only the mall load below changes
        # per timestep in this simplified synthetic scenario.

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

                    if has_violation_after:
                        violated_nets_dict[time_series_t.index[0]] = net
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

    return opf_results_df, updated_flex_target_kw, res_base, res_actual, bounds_df, violation_details_df, violated_nets_dict


### 9. Plotting + terminal summaries (unchanged)

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


def plot_single_line_diagram(net, mall_bus, savepath="grid_single_line_diagram.png", title=None):
    import json as _json

    if mall_bus in net.bus.index:
        mall_lines = net.line[(net.line.from_bus == mall_bus) | (net.line.to_bus == mall_bus)]
        print(f"\n[mall connection] bus {mall_bus} connects via {len(mall_lines)} line(s):")
        for li, row in mall_lines.iterrows():
            other = row["to_bus"] if row["from_bus"] == mall_bus else row["from_bus"]
            print(f"    line {li} ('{row.get('name', '')}') <-> bus {other}")

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

    ax = pp_plot.draw_collections(collections, figsize=(14, 9))

    for bus_idx in net.bus.index:
        geo_str = net.bus.at[bus_idx, "geo"]
        if pd.isna(geo_str):
            continue
        coords = _json.loads(geo_str)["coordinates"]
        ax.annotate(str(bus_idx), xy=(coords[0], coords[1]), xytext=(4, 4),
                    textcoords="offset points", fontsize=7, color="black", zorder=6)

    ax.set_title(title or f"{NET_LABEL} -- mall connected directly at bus {mall_bus} (red)")
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
    plot_prosumer_participation(opf_results_df, scenario_label)
    plot_soc_and_tracking(opf_results_df, res_actual, scenario_label)

def _collect_scaling_loadcases(net_dict: dict, keys: list, element: str, ref_idx: pd.Index) -> pd.Series:
    """Sammelt p_mw-Werte von `element` (z.B. 'load' oder 'sgen') aus allen
    Netzen und gibt je Zeile eine Liste über alle Lastfälle zurück."""
    p_mw_matrix = pd.DataFrame(index=ref_idx, columns=keys, dtype=float)

    for k in keys:
        el_k = getattr(net_dict[k], element)
        if not el_k.index.equals(ref_idx):
            raise ValueError(f"Index von '{element}' in Netz '{k}' weicht vom Basisnetz ab.")
        p_mw_matrix[k] = el_k["p_mw"].to_numpy()

    return p_mw_matrix.apply(list, axis=1)


def merge_loadcases(net_dict: dict, sort_keys: bool = False,
                     elements: tuple = ("load", "sgen")) -> pp.pandapowerNet:
    """
    Fasst mehrere Netze mit identischer Topologie, aber unterschiedlichen
    Lastfällen (p_mw) zu einem Netz zusammen (für load UND sgen).

    - p_mw wird auf 1.0 gesetzt
    - die ursprünglichen p_mw-Werte aller Fälle werden als Liste in
      <element>.scaling_loadcases abgelegt (Reihenfolge = dict-Reihenfolge)
    """
    keys = sorted(net_dict) if sort_keys else list(net_dict)
    net_out = copy.deepcopy(net_dict[keys[0]])

    for element in elements:
        el_out = getattr(net_out, element)
        if el_out.empty:
            continue  # z.B. keine sgen im Netz -> nichts zu tun

        el_out["scaling_loadcases"] = _collect_scaling_loadcases(
            net_dict, keys, element, el_out.index
        )
        el_out["p_mw"] = 1.0

    return net_out
### 10. Scenario runner

# def run_synthetic_scenario(scenario_label="synthetic_mall_stress_test", n_steps=N_STEPS):
n_steps = N_STEPS
scenario_label="synthetic_mall_stress_test"
print(f"\n{'='*70}\nSCENARIO: {scenario_label}\n"
          f"{NET_LABEL} | {n_steps} hourly steps\n{'='*70}")

ses_data_1h_full = load_full_ses_data(ses_data_file)
residual_mall_load_kw, mall_index = get_mall_residual_load_kw_from_ses(
    ses_data_1h_full, n_steps=n_steps, window_start=window_start)

print(f"[{scenario_label}] Mall window: {mall_index[0]} to {mall_index[-1]}")
print(f"[{scenario_label}] Residual mall load min/max: "
      f"{residual_mall_load_kw.min():.1f} / {residual_mall_load_kw.max():.1f} kW")

start = mall_index[0].strftime("%Y-%m-%d %H:%M:%S")
time_series_data = build_time_series_data(residual_mall_load_kw, start, n_steps, heat_data_file)

q_mall_base_mvar = 0.0
q_eps = MALL_Q_EPS_MVAR
net_base, mall_load, mall_feeder_line_idx, background_load_idx, sgen_idx = build_base_net(
    q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps)

background_profile_mw = generate_synthetic_background_load_profiles_mw(background_load_idx, n_steps=n_steps)
sgen_profile_mw = generate_synthetic_sgen_profile_mw(sgen_idx, n_steps=n_steps)

mall_bus = net_base.load.at[mall_load, "bus"]
print("\n=== Plotting single-line diagram (mall connection point highlighted) ===")
plot_single_line_diagram(net_base, mall_bus=mall_bus)

print(f"[{scenario_label}] Running closed-loop prosumer + grid OPF ({n_steps} hourly steps)...")

(opf_results_df, updated_flex_target_kw, res_base, res_actual,
 bounds_df, violation_details_df, violated_nets) = run_opf_timeseries_for_scenario(
    scenario_label=scenario_label,
    net_base=net_base, mall_load=mall_load, mall_feeder_line_idx=mall_feeder_line_idx,
    background_profile_mw=background_profile_mw, background_load_idx=background_load_idx,
    sgen_profile_mw=sgen_profile_mw, sgen_idx=sgen_idx,
    time_series_data_base=time_series_data,
    residual_mall_load_kw=residual_mall_load_kw,
    q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps,
    initial_soc=0.0)

opf_results_df["p_updated_grid_kw"] = res_actual["p_grid_kw"].reindex(opf_results_df.index)
opf_results_df["tracking_error_kw"] = opf_results_df["p_updated_grid_kw"] - opf_results_df["p_grid_setpoint_kw"]

opf_results_df.to_csv(f"grid_opf_timeseries_results_{scenario_label}.csv")
bounds_df.to_csv(f"grid_flexibility_bounds_{scenario_label}.csv")
violation_details_df.to_csv(f"grid_violation_details_{scenario_label}.csv", index=False)

print_scenario_summary(scenario_label, opf_results_df, violation_details_df, res_actual)
plot_scenario_diagnostics(opf_results_df, res_actual, scenario_label)

# net_merged = merge_loadcases(violated_nets)
from minihyper.config import GridConfig
# cfg = GridConfig()
# cfg.solver.time_limit_s = 300
#
#
# job, result_mh = run_full_job(net_merged, config=cfg)
# #
# # import copy
# # import numpy as np
# # import pandapower as pp
# #
MAX_REINFORCEMENT_ITERS = 15
MIN_EXPANSION_MVA = 1e-6


def get_expansion_by_line(job):
    """Extrahiert {line_idx: expansion_mva} aus dem geloesten Pyomo-Modell."""
    from pyomo.environ import value
    capacity = {key[-1]: value(var)
    for key, var in job.model.line_s_max_mva.items()}
    expansion = {key[-1]: value(var)
    for key, var in job.model.line_s_expansion_mva.items()}
    return expansion, capacity



def apply_line_reinforcement(net, expansion_by_line, min_expansion_mva=MIN_EXPANSION_MVA,
                              mode="scale_impedance"):
    """Wendet die berechnete Kapazitaetserweiterung auf net.line an (siehe
    vorherige Erklaerung: additiv zum Bestand, Impedanz mitskaliert)."""
    net = copy.deepcopy(net)
    n_reinforced = 0

    for line_idx, expansion_mva in expansion_by_line.items():
        if expansion_mva <= min_expansion_mva or line_idx not in net.line.index:
            continue

        from_bus = net.line.at[line_idx, "from_bus"]
        vn_kv = net.bus.at[from_bus, "vn_kv"]
        parallel = net.line.at[line_idx, "parallel"]

        s_existing_mva = np.sqrt(3) * vn_kv * net.line.at[line_idx, "max_i_ka"] * parallel
        s_new_mva = s_existing_mva + expansion_mva
        scale = s_new_mva * 1.1 / s_existing_mva

        net.line.at[line_idx, "max_i_ka"] *= scale
        if mode == "scale_impedance":
            net.line.at[line_idx, "r_ohm_per_km"] /= scale
            net.line.at[line_idx, "x_ohm_per_km"] /= scale

        n_reinforced += 1

    return net, n_reinforced

def resimulate_and_collect_violations(net_reinforced, mall_feeder_line_idx,
                                       background_profile_mw, background_load_idx,
                                       sgen_profile_mw, sgen_idx, mall_load, residual_mall_load_kw,
                                       time_series_data_base, q_mall_base_mvar, q_eps):
    """Führt den kompletten Prosumer+OPF-Zeitschleifenlauf auf dem
    verstärkten Netz erneut aus und liefert die neuen violated_nets für
    die nächste Iteration."""
    (opf_results_df, updated_flex_target_kw, res_base, res_actual,
     bounds_df, violation_details_df, violated_nets_new) = run_opf_timeseries_for_scenario(
        scenario_label="reinforcement_iter",
        net_base=net_reinforced, mall_load=mall_load, mall_feeder_line_idx=mall_feeder_line_idx,
        background_profile_mw=background_profile_mw, background_load_idx=background_load_idx,
        sgen_profile_mw=sgen_profile_mw, sgen_idx=sgen_idx,
        time_series_data_base=time_series_data_base,
        residual_mall_load_kw=residual_mall_load_kw,
        q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps,
        initial_soc=0.0)

    print_scenario_summary(scenario_label, opf_results_df, violation_details_df, res_actual)
    return violated_nets_new, violation_details_df


def run_reinforcement_loop(net_base_initial, violated_nets_initial, mall_feeder_line_idx,
                            background_profile_mw, background_load_idx,
                            sgen_profile_mw, sgen_idx, mall_load,
                            residual_mall_load_kw, time_series_data_base,
                            q_mall_base_mvar, q_eps, cfg,
                            max_iters=MAX_REINFORCEMENT_ITERS):
    """Iteratives Netzausbau-Loop:
        1. merge_loadcases + run_full_job auf den aktuell verletzten Netzen
        2. line_s_expansion_mva extrahieren und auf das Basisnetz anwenden
        3. gesamten Zeitreihenlauf mit dem verstärkten Netz neu simulieren
        4. wenn keine violated_nets mehr -> fertig, sonst weiter zu 1.
    """
    net_base_current = copy.deepcopy(net_base_initial)   # <- VOR dem Loop initialisiert
    violated_nets = violated_nets_initial
    history = []

    for iteration in range(1, max_iters + 1):
        print(f"\n{'='*70}\nREINFORCEMENT-ITERATION {iteration}\n{'='*70}")

        if not violated_nets:
            print(f"Keine Verletzungen mehr -- Loop beendet nach {iteration - 1} Iteration(en).")
            break

        print(f"[Iter {iteration}] {len(violated_nets)} verletzte Zeitschritte "
              "-> merge_loadcases + run_full_job")
        net_merged = merge_loadcases(violated_nets)

        job, result_mh = run_full_job(net_merged, config=cfg)

        expansion_by_line, capacity_by_line = get_expansion_by_line(job)
        print(expansion_by_line)
        print(capacity_by_line)
        n_expanded_this_iter = sum(1 for v in expansion_by_line.values() if v > MIN_EXPANSION_MVA)
        print(f"[Iter {iteration}] {n_expanded_this_iter} Leitung(en) werden verstärkt")

        if n_expanded_this_iter == 0:
            print(f"[Iter {iteration}] WARNUNG: keine Verstärkung vorgeschlagen, aber noch "
                  "Verletzungen vorhanden -- Loop wird abgebrochen (prüfe MIPGap/Konvergenz).")
            history.append({"iteration": iteration, "n_violated_before": len(violated_nets),
                            "n_lines_expanded": 0, "n_violated_after": len(violated_nets),
                            "stopped_reason": "no_expansion_proposed"})
            break

        net_base_current, _ = apply_line_reinforcement(net_base_current, expansion_by_line)

        violated_nets_new, violation_details_df = resimulate_and_collect_violations(
            net_base_current, mall_feeder_line_idx,
            background_profile_mw, background_load_idx,
            sgen_profile_mw, sgen_idx, mall_load, residual_mall_load_kw,
            time_series_data_base, q_mall_base_mvar, q_eps)

        print(f"[Iter {iteration}] Nach Resimulation: {len(violated_nets_new)} verletzte "
              f"Zeitschritte (vorher {len(violated_nets)})")

        history.append({"iteration": iteration, "n_violated_before": len(violated_nets),
                        "n_lines_expanded": n_expanded_this_iter,
                        "n_violated_after": len(violated_nets_new),
                        "stopped_reason": None})

        violated_nets = violated_nets_new
    else:
        print(f"\nWARNUNG: max_iters={max_iters} erreicht, ohne Verletzungsfreiheit zu erzielen.")

    return net_base_current, history


cfg = GridConfig()
cfg.solver.time_limit_s = 300

net_base_final, reinforcement_history = run_reinforcement_loop(
    net_base_initial=net_base,
    violated_nets_initial=violated_nets,
    mall_feeder_line_idx=mall_feeder_line_idx,
    background_profile_mw=background_profile_mw,
    background_load_idx=background_load_idx,
    sgen_profile_mw=sgen_profile_mw,
    sgen_idx=sgen_idx,
    mall_load=mall_load,
    residual_mall_load_kw=residual_mall_load_kw,
    time_series_data_base=time_series_data,
    q_mall_base_mvar=q_mall_base_mvar,
    q_eps=q_eps,
    cfg=cfg,
    max_iters=5)   # siehe Hinweis unten

print(pd.DataFrame(reinforcement_history))