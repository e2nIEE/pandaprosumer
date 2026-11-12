#  Future statements
from __future__ import annotations

#  Standard library imports
import base64
import copy
import html as html_lib
import importlib
import io
import json as json
import math
import os
import pickle
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path

#  Third-party library imports
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import simbench as sb
from matplotlib.cm import ScalarMappable  # shared colourbars in the before/after violation maps
from matplotlib.lines import Line2D
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

#  Domain-specific / Power systems imports (pandapower & pandaprosumer)
import pandapower as pp
import pandapower.networks as pn
import pandapower.plotting as pp_plot
import pandapower.topology as pp_topology
from pandapower.grid_equivalents.get_equivalent import get_equivalent as pp_get_equivalent
from pandapower.grid_equivalents.toolbox import get_connected_switch_buses_groups
from pandapower.plotting import cmap_continuous  # discrete/continuous colormaps for violation maps
from pandapower.timeseries.data_sources.frame_data import DFData
from pandapower.topology import create_nxgraph
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (
    create_controlled_booster_heat_pump,
    create_controlled_const_profile,
    create_controlled_heat_demand,
    create_controlled_heat_storage,
    create_controlled_ice_chp,
    create_controlled_optimtization,
)
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries

#  Environment & Library Tweaks
try:
    from tqdm import tqdm
    _HAVE_TQDM = True
except ImportError:
    _HAVE_TQDM = False

warnings.filterwarnings("ignore", category=FutureWarning, module="simbench")
warnings.filterwarnings("ignore", category=FutureWarning, module="pandapower")
pd.set_option('future.no_silent_downcasting', True)
USE_NUMBA = False
VERBOSE_OPF_FAILURES = False

# Context manager to suppress native stdout
@contextmanager
def suppress_native_stdout():
    """Terminal / environment setup to suppress the HiGHS solver banner that pandapower's OPF prints to stdout."""
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

# monkeypatch: 
# older Simbench nets are missing legacy geodata tables that some pandapower plotting helpers still expect
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

# Simulation Configurations & File Paths
frequency = "60min"
time_resolution = 3600
YEAR_START = pd.Timestamp("2025-01-01 00:15:00")
WINDOW_DAYS = 8

# Where the two 8-day windows come from:
# "grid" : from the GRID profiles (total generation minus total load of the CIGRE net);
#          export window -> overvoltage, import window -> the three import-type scenarios.
#          Mall SES + heat data are then taken from the SAME calendar dates.
# "mall" : from the mall's own SES data 
WINDOW_SOURCE = "grid"

project_root = (Path.cwd().parent if Path.cwd().name in ["tutorials", "tutorials_extended"]
                else Path.cwd())
ses_data_file = project_root / "tutorials_extended" / "data" / "ses_data.xlsx"
heat_data_file = project_root / "tutorials_extended" / "data" / "aleja_heat_demand_model_data_2025.xlsx"

# Engineering Constants (Grid & SLD)
 
GRID_CODE = "cigre_mv"          # pandapower.networks.create_cigre_network_mv(); 
SUPPORTED_GRID_CODE = "cigre_mv"
CIGRE_WITH_DER = "all"          # False | "pv_wind" | "all" (distributed generation of the CIGRE benchmark)
MALL_BUS_OVERRIDE = None        # None = auto (deepest end of the most loaded branch); or an int bus id 2..14
MALL_BUS = None
EXT_GRID_LIMIT_MVA = 200.0      # OPF bound on ext_grid P/Q (substation is 2 x 25 MVA)
IMPORT_Q_EPS_MVAR = 1e-6        # reactive-power headroom for the mall load.
allow_export_to_grid = True

# Grid violation thresholds
v_min_pu_std = 0.90
v_max_pu_std = 1.10
loading_percent_max_std = 100.0

##### Grid source  CIGRE MV net (pandapower.networks) + SimBench profile shapes
# The CIGRE net ships no profiles. The shapes come from SimBench (SIMBENCH_CODES) and are mapped to the CIGRE
# elements by type, then scaled to the nominal values of the CIGRE net:
# The profile of every element is  nominal_value x shape(t)  with shape(t) in [0, 1]: loads are normalised to
# their own annual maximum of exactly 1 (a load never exceeds its nominal peak value), sgens are in per unit of
# installed power. GRID_PROFILE_SEED only fixes which SimBench profile is assigned to which CIGRE element.

GRID_PROFILE_SEED = 42        # same seed -> same SimBench profile-to-element assignment, run after run
PROFILE_STEPS = 35136         # 366 x 96 quarter hours (identical length to a SimBench year)
GRID_LOAD_PEAK_SCALE = 1.0    # global knob: multiplies every load profile (e.g. 1.2 = +20 % load)
_GRID_NOMINAL_CACHE = {}      # grid_code -> {"load_p","load_q","sgen_p"} (pd.Series by element id)
_GRID_PROFILE_CACHE = {}      # grid_code -> profiles dict

SIMBENCH_CODES = ("1-MV-semiurb--0-no_sw",)   # SimBench MV grids whose PROFILES are pooled 
                                            #"1-MV-urban--0-no_sw", "1-MV-rural--0-no_sw", , "1-MV-comm--0-no_sw"                                        
SIMBENCH_EXCLUDE_KEYS = ("lv_rural1", "bl-h")   # lowercase; for scenarios 1 & 2 also add "apls", "air_", "soil_"
SIMBENCH_YEAR_START = pd.Timestamp("2016-01-01 00:00")   # SimBench profile year: 366 d x 96 = 35136 steps (Friday)
SIMBENCH_RESIDENTIAL_KEYS = ("lv_", "h0", "hh")          # load profile names -> residential (lv_* = aggregated LV grids)
SIMBENCH_PV_KEYS = ("pv", "solar")                       # sgen "profile"/"type" text -> PV
SIMBENCH_WIND_KEYS = ("wind", "wp", "wt")                # ... -> wind
SIMBENCH_PV_FALLBACK_KEYS = ("lv_res",)                  # aggregated LV renewable feed-in; used for PV ONLY if no explicit PV profile exists
_SIMBENCH_POOL_CACHE = {}                                # codes -> {"load": {kind: DataFrame}, "sgen": {kind: DataFrame}}

#  Scenario-driven study 
######
# The load_scale, sgen_scale, and branch_load_scale parameters can be adjusted to simulate different levels of demand and distributed generation. 

# The expected_violation_type parameter indicates the type of violation that is expected to occur under the given scenario.
SCENARIO_CONFIGS = {
    "overvoltage": {
        "description": "High distributed generation during light demand",
        "load_scale": 0.30, "sgen_scale": 3.5, "branch_load_scale": 1.0,
        "expected_violation_type": "overvoltage",
    }, 
    #Minimum demand is 30% of peak, representing a sunny spring weekend. DG capacity is scaled to 2.5× the base installation to represent 
    # a high future PV penetration scenario. Under these conditions, reverse power flow causes both overvoltage and line thermal overloading.
    "undervoltage": {
        "description": "High coincident demand with reduced distributed generation",
        "load_scale": 1.4, "sgen_scale": 0.1, "branch_load_scale": 1.0,
        "expected_violation_type": "undervoltage",
    },
    # e.g. winter heating, EV charging, and electrified heating. 
    # DG output is reduced to 10% because solar and wind availability are low. The resulting voltage drop along the feeder causes undervoltage.
    "line_overloading": {
        "description": "Elevated demand concentrated downstream of the mall connection",
        "load_scale": 1.5, "sgen_scale": 0.50, "branch_load_scale": 1.3,
        "expected_violation_type": "line_overload",
    },
    "transformer_overloading": {
        "description": "High coincident demand across the entire MV grid",
        "load_scale": 1.5, "sgen_scale": 0.30, "branch_load_scale": 1.0,
        "expected_violation_type": "trafo_overload",
    },
}
# Mall prosumer physical model parameters 
###### 
# This can be adjusted to represent different mall configurations and their impact on grid flexibility.
BASE_MALL_CHP_KW = 350.0         # the mall's actual CHP (electrical kW)
BASE_MALL_BHP_Q_MAX_KW = 1550.0  # thermal; was 800 (CHP + HP ~ 2.1 MW vs 2.13 MW heat peak)
BASE_MALL_STORAGE_KWH = 8000.0   # was 50000 (coldest day needs 11.7 MWh)
INIT_SOC = 0.4                   # initial state of charge of the mall's heat storage (fraction of capacity)

# Status Constants
STATUS_RESOLVED = "Resolved"
STATUS_STILL_VIOLATING = "Still violating"
STATUS_PF_FAILED = "PF failed"
STATUS_FLEX_INFEASIBLE = "Flexibility infeasible"
STATUS_NOT_EVALUATED = "Not evaluated"

# Status Processing
def _canonical_status(old_status, residual_violation_count, flex_infeasible=False):
    
    old = "" if old_status is None or pd.isna(old_status) else str(old_status).strip().lower()
    # True power-flow failures from the runner all start with "pf_" (pf_with_mall_failed,
    # pf_after_infeasible_flexibility_failed, pf_after_ppros_update). A plain substring test
    # for "pf" also matches "opf_failed_fallback_*", which is NOT a power-flow failure.
    if old.startswith("pf_"):
        return STATUS_PF_FAILED
    if flex_infeasible or "infeasible" in old:
        return STATUS_FLEX_INFEASIBLE
    if residual_violation_count and residual_violation_count > 0:
        return STATUS_STILL_VIOLATING
    if old in {
        "resolved",
        "no_violation_no_flex_needed",
        "opf_success_violations_resolved",
        "opf_failed_fallback_resolved",
    }:
        # An OPF failure may still lead to a resolved electrical outcome if the
        # fallback dispatch was applied and a valid post-dispatch PF passed limits.
        return STATUS_RESOLVED
    if old in ("", "nan", "none"):
        return STATUS_NOT_EVALUATED
    # Unknown states must never be silently promoted to a successful resolution.
    return STATUS_NOT_EVALUATED

def _normalise_scenario_results(results_df, violation_details_df, scenario_label):
    """Attach explicit initial/residual counts and canonical status per time step."""
    out = results_df.copy()
    details = violation_details_df.copy() if violation_details_df is not None else pd.DataFrame()
    if "time" in details.columns:
        details["time"] = pd.to_datetime(details["time"])
    before_counts, after_counts = {}, {}
    if not details.empty and {"time", "phase"}.issubset(details.columns):
        before_counts = details[details.phase.eq("before")].groupby("time").size().to_dict()
        after_counts = details[details.phase.eq("after")].groupby("time").size().to_dict()
    out["scenario"] = scenario_label
    out["initial_violation_count"] = [int(before_counts.get(pd.Timestamp(t), 0)) for t in out.index]
    out["residual_violation_count"] = [int(after_counts.get(pd.Timestamp(t), 0)) for t in out.index]
    old_status_col = "status" if "status" in out.columns else None
    statuses = []
    for t, row in out.iterrows():
        old = row[old_status_col] if old_status_col else ""
        # Flexibility infeasibility is recorded explicitly by the legacy runner when present.
        flex_bad = "infeasible" in str(old).lower()
        statuses.append(_canonical_status(old, int(after_counts.get(pd.Timestamp(t), 0)), flex_bad))
    out["status"] = statuses
    return out

def _status_summary_counts(results_df):
    """Count hours per canonical status (same logic as the Excel report).
    Expects the DataFrame produced by _normalise_scenario_results, i.e. a
    five-state 'status' column plus 'initial_violation_count'."""
    n_total = len(results_df)
    if "status" in results_df.columns:
        status = results_df["status"]
    else:
        status = pd.Series(STATUS_NOT_EVALUATED, index=results_df.index)
    if "initial_violation_count" in results_df.columns:
        initial = pd.to_numeric(results_df["initial_violation_count"], errors="coerce").fillna(0)
    else:
        initial = pd.Series(0, index=results_df.index, dtype=float)
    evaluated = ~status.isin([STATUS_PF_FAILED, STATUS_NOT_EVALUATED])
    return {
        "n_total": n_total,
        "n_no_flex": int(((initial == 0) & evaluated).sum()),
        "n_violated": int((initial > 0).sum()),
        "n_resolved": int(((status == STATUS_RESOLVED) & (initial > 0)).sum()),
        "n_remaining": int((status == STATUS_STILL_VIOLATING).sum()),
        "n_infeasible": int((status == STATUS_FLEX_INFEASIBLE).sum()),
        "n_pf_failed": int((status == STATUS_PF_FAILED).sum()),
        "n_not_evaluated": int((status == STATUS_NOT_EVALUATED).sum()),
    }

# One HyperCAP case per violating (scenario, hour) snapshot. Only hours with residual violations (phase="after") are exported. 
# The buses directly involved in a snapshot's violations define its detailed target region;
# boundary buses are the buses immediately outside that region on the
# pandapower topology graph. The actual electrical reduction is performed
# only by pandapower's get_equivalent(..., eq_type="ward", ...) 
# VALIDATION TOLERANCES (tighten if you want a stricter equivalence check --
# see the notes below build_hypercap_case_dict for why these are conservative)
HYPERCAP_VOLTAGE_TOLERANCE_PU = 1e-4
HYPERCAP_ANGLE_TOLERANCE_DEG = 0.05
HYPERCAP_POWER_TOLERANCE_MW = 1e-1  
HYPERCAP_POWER_TOLERANCE_MVAR = 1e-1 
HYPERCAP_LOADING_TOLERANCE_PERCENT = 0.5

# SLD (single-line diagram) styling knobs
SLD_LEAF_STEP = 2.8     # vertical spacing between sibling leaves
SLD_DEPTH_STEP = 3.6    # horizontal spacing per tree depth level
# SLD color scheme 
SLD_BUSBAR_COLOR = "#000000"     # black - busbars stay black
SLD_MALL_COLOR = "#7b1fa2"       # purple - mall bus / point of interest
SLD_LINE_COLOR = "#4d4d4d"       # dark grey - feeders/lines
SLD_LOAD_COLOR = "#1f4e8c"       # dark blue - load arrows
SLD_SGEN_COLOR = "#2e8b57"       # sea green - generation (PV/sgen)
SLD_TRAFO_COLOR = "#555555"      # medium grey - transformer symbol
SLD_EXTGRID_COLOR = "#000000"    # black hatch - ext grid
SLD_SWITCH_COLOR = "#1f77b4"     # blue - closed bus-bus switches
SLD_IMPEDANCE_COLOR = "#9467bd"  # purple dashed - Ward eq_impedance between two boundary buses
# SLD symbol sizes, expressed in LAYOUT UNITS 
SLD_SYM_TRAFO = 0.26     # trafo symbol size in layout units
SLD_SYM_EXTGRID = 0.30   # ext-grid box size

# Module level (used by SldPlotter.build_sld_collections) so that
# _build_sld_legend() can label them with the exact same colors they are drawn in. 
SLD_OOS_COLOR = "#a0a0a0"            # out of service
SLD_DCLINE_COLOR = "#393b79"
SLD_GEN_COLOR = "#8c564b"            # controllable generator
SLD_STORAGE_COLOR = "#e377c2"        # storage (the pink "plus" markers)
SLD_SHUNT_COLOR = "#7f7f7f"
SLD_WARD_COLOR = "#17becf"
SLD_XWARD_COLOR = "#bcbd22"
SLD_SVC_COLOR = "#ff7f0e"
SLD_SSC_COLOR = "#ff9896"
SLD_TCSC_COLOR = "#c49c94"
SLD_SWITCH_CLOSED_COLOR = "#1a1a1a"  # filled square = closed line/trafo switch
# hollow square = open line/trafo switch
SLD_SWITCH_OPEN_EDGE = "#6e6e6e"    

###### Grid violation maps -- BEFORE vs AFTER mall flexibility

VIOL_BASE_LINE_COLOR = "#cfcfcf"   # grey background network
VIOL_BASE_BUS_COLOR = "#9e9e9e"
VIOL_MALL_COLOR = "#7b1fa2"        # purple - mall bus (red is reserved for "violation")
VIOL_RESOLVED_COLOR = "#2e7d32"    # green - violated before, fine after the mall reacted
VIOLATION_MAP_TOP_HOURS = 5        # how many of the worst hours get their own before/after pair
#( change it if you want to see more than 5 worst hours in the report)
_VIOL_TYPES = ("undervoltage", "overvoltage", "line_overload", "trafo_overload")
_VIOL_LABEL = {"undervoltage": ("under-voltage bus", "under-voltage buses"),
               "overvoltage": ("over-voltage bus", "over-voltage buses"),
               "line_overload": ("overloaded line", "overloaded lines"),
               "trafo_overload": ("overloaded trafo", "overloaded trafos")}

SLD_DOMINANT_VIOLATION_COLOR = "#d62728"  # Red: dominant violation
SLD_OTHER_VIOLATION_COLOR = "#ffbf00"     # Amber: secondary violations
SLD_OUTCOME_IMPROVED_COLOR = "#137333"    # Green: constraint condition improved
SLD_OUTCOME_DEGRADED_COLOR = "#b3261e"    # Red: constraint condition degraded
SLD_OUTCOME_RESOLVED_COLOR = "#137333"    # Green: previous violation resolved
SLD_OUTCOME_NEW_COLOR = "#b3261e"         # Red: newly created violation
SLD_OUTCOME_UNCHANGED_COLOR = "#555555"   # Grey: no material change
SLD_OUTCOME_NE_COLOR = "#174ea6"          # Blue: not evaluated


##### HTML Scenario Report

_STATUS_ROW_COLOR = {
    STATUS_RESOLVED: "#e8f5e9",
    STATUS_STILL_VIOLATING: "#ffcdd2",
    STATUS_PF_FAILED: "#e0e0e0",
    STATUS_FLEX_INFEASIBLE: "#ffe0b2",
    STATUS_NOT_EVALUATED: "#eeeeee",
}
_STATUS_LABEL = {
    STATUS_RESOLVED: "Resolved",
    STATUS_STILL_VIOLATING: "Still violating",
    STATUS_PF_FAILED: "PF failed",
    STATUS_FLEX_INFEASIBLE: "Flexibility infeasible",
    STATUS_NOT_EVALUATED: "Not evaluated",
}

#####    SES & Heat data loading + best-window scanning
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
    
    best_export_row = scan_df.loc[scan_df["residual_peak_export_kw"].idxmin()]
    best_import_row = scan_df.loc[scan_df["residual_peak_import_kw"].idxmax()]
    return scan_df, best_export_row, best_import_row

def load_and_scan_ses_data(path, window_days=WINDOW_DAYS):
    """Convenience wrapper: load the workbook and scan it in one call,
    returning (ses_data_1h_full, scan_df, best_export_row, best_import_row)."""

    ses_data_1h_full = load_full_ses_data(path)
    scan_df, best_export_row, best_import_row = scan_ses_windows(ses_data_1h_full, window_days=window_days)
    return ses_data_1h_full, scan_df, best_export_row, best_import_row

def _heat_hours_on_profile_year(heat_data_file):
    """Hourly timestamps of the heat file, mapped onto the grid-profile year (same calendar
    date/time). build_time_series_data() maps the window start onto the heat year the same way."""
    heat_dt = pd.to_datetime(pd.read_excel(heat_data_file)["DateTime"]).dropna()
    shift_years = YEAR_START.year - int(heat_dt.min().year)
    shifted = pd.DatetimeIndex(heat_dt) + pd.DateOffset(years=shift_years)
    return pd.DatetimeIndex(shifted).floor("60min").unique()

def build_time_series_data(start, n_steps, heat_data_file):
    """Heat/prosumer input series for the window beginning at `start`.
    The heat data is sliced by DATE (same dates as the  window)
    """
    heat = pd.read_excel(heat_data_file)          # first sheet: 'model data', hourly 2025
    heat["DateTime"] = pd.to_datetime(heat["DateTime"])
    heat = heat.sort_values("DateTime").reset_index(drop=True)

    start_ts = pd.Timestamp(start).tz_localize(None) if pd.Timestamp(start).tzinfo else pd.Timestamp(start)
    # map the window start onto the heat year (heat file is 2025; same calendar timestamp)
    year0 = heat["DateTime"].iloc[0].year
    try:
        start_ts = start_ts.replace(year=year0)
    except ValueError:                             # 29 Feb
        start_ts = start_ts.replace(year=year0, day=28)
    pos = int(heat["DateTime"].searchsorted(start_ts))
    if pos >= len(heat):
        raise RuntimeError(f"Heat data does not contain the window start {start_ts}.")
    # wrap around the year end if the window runs past it
    needed = pos + n_steps
    if needed > len(heat):
        reps = int(np.ceil(needed / len(heat)))
        heat = pd.concat([heat] * reps, ignore_index=True)
    time_series_data = heat.iloc[pos:pos + n_steps].drop(columns=["DateTime"]).copy()
    dur = pd.date_range(start=start, periods=n_steps, freq=frequency, tz="utc")
    time_series_data.index = dur
    time_series_data["flex_demand_kw"] = np.zeros(n_steps)
    time_series_data["t_sink_k"] = 350
    time_series_data["cycle"] = 1
    return time_series_data

def scan_grid_windows(profiles, idx, ses_data_1h_full, heat_hours, window_days=WINDOW_DAYS):
    """Select the export and import windows from the GRID profiles.

    net import of the grid = sum(load P) - sum(sgen P)   (positive = import, negative = export)
    The same peak-based rule as scan_ses_windows() (PM_1) is applied to it:
      export window = 30-day window with the most negative hourly net import (largest net export)
      import window = 30-day window with the highest hourly net import (peak demand)
    Only windows in which EVERY hour is present in the SES data and in the heat data
    (mapped to the profile year) are candidates, so the mall data always matches the grid dates.
    Returns (best_export_row, best_import_row, scan_df); values in scan_df are grid kW.
    """
    window_hours = window_days * 24
    load_kw = profiles[("load", "p_mw")].sum(axis=1).to_numpy(dtype=float) * 1000.0
    sgen = profiles[("sgen", "p_mw")]
    gen_kw = (sgen.sum(axis=1).to_numpy(dtype=float) * 1000.0 if len(sgen.columns)
              else np.zeros(len(idx)))

    # Same column names as the SES frame, so scan_ses_windows() can be reused:
    # "P el sc [kW]" = grid load, "P pv [kW]" = grid generation  ->  residual = load - generation.
    frame = pd.DataFrame({"P el sc [kW]": load_kw, "P pv [kW]": gen_kw}, index=idx)
    frame = frame.resample("60min").mean()
    # The profile index runs into the next year (366 x 96 steps); heat/SES data are one calendar year.
    frame = frame.loc[frame.index.year == YEAR_START.year]

    scan_df, _, _ = scan_ses_windows(frame, window_days=window_days)

    # Candidate windows: every hour available in SES data AND heat data.
    avail = pd.Series(frame.index.isin(ses_data_1h_full.index) & frame.index.isin(heat_hours),
                      index=frame.index).astype(int)
    fully_covered = avail.rolling(window_hours).sum().eq(window_hours)
    scan_df["covered_by_mall_data"] = fully_covered.reindex(
        pd.DatetimeIndex(scan_df["window_end"])).to_numpy()

    candidates = scan_df[scan_df["covered_by_mall_data"]]
    if candidates.empty:
        raise RuntimeError(
            "No 30-day grid window is fully covered by both the SES data and the heat data. "
            "Check that the SES/heat files span the profile year "
            f"({YEAR_START.year}) without gaps.")
    best_export_row = candidates.loc[candidates["residual_peak_export_kw"].idxmin()]
    best_import_row = candidates.loc[candidates["residual_peak_import_kw"].idxmax()]
    return best_export_row, best_import_row, scan_df

def check_window_coverage(label, window_start, window_end, ses_data_1h_full, heat_hours):
    """Fail early if the SES or heat data miss any hour of [window_start, window_end)."""
    hours = pd.date_range(window_start, window_end - pd.Timedelta(hours=1), freq="60min")
    miss_ses = hours.difference(ses_data_1h_full.index)
    if len(miss_ses):
        raise RuntimeError(f"[{label}] SES data misses {len(miss_ses)} of {len(hours)} hours in "
                           f"{window_start} .. {window_end} (first gap: {miss_ses[0]}).")
    miss_heat = hours.difference(heat_hours)
    if len(miss_heat):
        raise RuntimeError(f"[{label}] heat data misses {len(miss_heat)} of {len(hours)} hours in "
                           f"{window_start} .. {window_end} (first gap: {miss_heat[0]}).")

#####   Prosumer model & #  Prosumer run with controller-based bounds
#PM_3: TODO: check if the addition of the el. battery storage would make sense for case when mall flex is insufficient
def mall_components():
    """Return the fixed equipment sizes of the mall."""
    return {
        "chp_size_kw": BASE_MALL_CHP_KW,
        "bhp_q_max_kw": BASE_MALL_BHP_Q_MAX_KW,
        "q_capacity_kwh": BASE_MALL_STORAGE_KWH,
    }

def build_mall_prosumer(time_series_data_base, flex_target_kw, start,
                        end, time_resolution, frequency, collect_bounds=False, init_soc=INIT_SOC,
                        previous_controller_results=None, previous_chp_downtime=None, tz="utc"):
    comp = mall_components()
    prosumer = create_empty_prosumer_container(check_order=False)

    time_series_data_mall = time_series_data_base.copy()
    time_series_data_mall["flex_demand_kw"] = np.asarray(flex_target_kw)
    time_series_data_mall["t_sink_k"] = 350
    time_series_data_mall["cycle"] = 1

    time_index = pd.date_range(
        start=start,
        periods=len(time_series_data_mall),
        freq=frequency,
        tz=tz
    )
    time_series_data_mall.index = time_index
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
    max_thermal_power_kw = comp["bhp_q_max_kw"]

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
    size_kw = comp["chp_size_kw"]
    fuel = 'ng'
    altitude_m = 0

    ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=2, order=1)

    q_capacity_kwh = comp["q_capacity_kwh"]

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

def run_mall_case_with_bounds(time_series_data_base, flex_target_kw, residual_mall_load_kw,
                              start, end, time_resolution, frequency, collect_bounds=False,
                              allow_export=False, init_soc=INIT_SOC, previous_controller_results=None,
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

##### Grid operations and feeder topology
class GridOps:
    @staticmethod
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

    @staticmethod
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

        net.ext_grid["min_p_mw"] = -EXT_GRID_LIMIT_MVA          
        net.ext_grid["max_p_mw"] = EXT_GRID_LIMIT_MVA
        net.ext_grid["min_q_mvar"] = -EXT_GRID_LIMIT_MVA
        net.ext_grid["max_q_mvar"] = EXT_GRID_LIMIT_MVA

        for eg_bus, eg_vm in zip(net.ext_grid["bus"], net.ext_grid["vm_pu"]):
            net.bus.at[eg_bus, "min_vm_pu"] = eg_vm
            net.bus.at[eg_bus, "max_vm_pu"] = eg_vm

    @staticmethod
    def run_pf(net, context="", print_error=True):
        try:
            pp.runpp(net, algorithm="nr", max_iteration=50, tolerance_mva=1e-8, init="auto", numba=USE_NUMBA)
            return True
        except Exception as exc:
            if print_error:
                print(f"\nPower flow failed: {context}")
                print(f"Reason: {exc}")
            return False

    @staticmethod
    def check_grid_violations(net):
        violations = {"undervoltage": [], "overvoltage": [],
                      "line_overload": [], "trafo_overload": []}
        for bus in net.res_bus.index:
            vm_pu = float(net.res_bus.at[bus, "vm_pu"])
            min_v = (float(net.bus.at[bus, "min_vm_pu"])
                     if "min_vm_pu" in net.bus.columns and pd.notna(net.bus.at[bus, "min_vm_pu"])
                     else v_min_pu_std)
            max_v = (float(net.bus.at[bus, "max_vm_pu"])
                     if "max_vm_pu" in net.bus.columns and pd.notna(net.bus.at[bus, "max_vm_pu"])
                     else v_max_pu_std)
            if vm_pu < min_v:
                violations["undervoltage"].append((bus, vm_pu))
            if vm_pu > max_v:
                violations["overvoltage"].append((bus, vm_pu))
        if len(net.line):
            for line in net.res_line.index:
                loading = float(net.res_line.at[line, "loading_percent"])
                limit = (float(net.line.at[line, "max_loading_percent"])
                         if "max_loading_percent" in net.line.columns and pd.notna(net.line.at[line, "max_loading_percent"])
                         else loading_percent_max_std)
                if loading > limit:
                    violations["line_overload"].append((line, loading))
        if len(net.trafo):
            for trafo in net.res_trafo.index:
                loading = float(net.res_trafo.at[trafo, "loading_percent"])
                limit = (float(net.trafo.at[trafo, "max_loading_percent"])
                         if "max_loading_percent" in net.trafo.columns and pd.notna(net.trafo.at[trafo, "max_loading_percent"])
                         else loading_percent_max_std)
                if loading > limit:
                    violations["trafo_overload"].append((trafo, loading))
        has_violation = any(len(v) > 0 for v in violations.values())
        return has_violation, violations

    @staticmethod
    def element_label(net, violation_type, element_id):
        try:
            if violation_type == "trafo_overload":
                name = net.trafo.at[element_id, "name"]
                return str(name) if pd.notna(name) and name else f"trafo_{element_id}"
            if violation_type == "line_overload":
                name = net.line.at[element_id, "name"] if "name" in net.line.columns else None
                return str(name) if name is not None and pd.notna(name) and name else f"line_{element_id}"
            if violation_type in ("undervoltage", "overvoltage"):
                name = net.bus.at[element_id, "name"]
                return str(name) if pd.notna(name) and name else f"bus_{element_id}"
        except Exception:
            pass
        return str(element_id)

    @staticmethod
    def record_violation_details(rows_list, hour, phase, violations, net):
        for violation_type, entries in violations.items():
            for element_id, value in entries:
                # PM_7: distance beyond the limit (positive = violating)
                if violation_type == "undervoltage":
                    limit = (float(net.bus.at[element_id, "min_vm_pu"])
                             if "min_vm_pu" in net.bus.columns and pd.notna(net.bus.at[element_id, "min_vm_pu"])
                             else v_min_pu_std)
                    excess = limit - value
                elif violation_type == "overvoltage":
                    limit = (float(net.bus.at[element_id, "max_vm_pu"])
                             if "max_vm_pu" in net.bus.columns and pd.notna(net.bus.at[element_id, "max_vm_pu"])
                             else v_max_pu_std)
                    excess = value - limit
                elif violation_type == "line_overload":
                    limit = (float(net.line.at[element_id, "max_loading_percent"])
                             if "max_loading_percent" in net.line.columns and pd.notna(net.line.at[element_id, "max_loading_percent"])
                             else loading_percent_max_std)
                    excess = value - limit
                else:  # trafo_overload
                    limit = (float(net.trafo.at[element_id, "max_loading_percent"])
                             if "max_loading_percent" in net.trafo.columns and pd.notna(net.trafo.at[element_id, "max_loading_percent"])
                             else loading_percent_max_std)
                    excess = value - limit
                normalized_severity_pct = (
                    abs(float(excess)) / abs(float(limit)) * 100.0
                    if pd.notna(limit) and abs(float(limit)) > 1e-12
                    else np.nan
                )
                rows_list.append({
                    "time": hour,
                    "phase": phase,
                    "violation_type": violation_type,
                    "element_id": element_id,
                    "location": GridOps.element_label(net, violation_type, element_id),
                    "value": value,
                    "limit": limit,
                    "excess": excess,
                    # Unitless severity: excess as a percentage of the applicable limit.
                    "normalized_severity_pct": normalized_severity_pct,
                })

    @staticmethod
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

class FeederTopology:
    @staticmethod
    def find_bus_feeder_line(net, bus):
        candidates = net.line.index[(net.line.from_bus == bus) | (net.line.to_bus == bus)]
        if len(candidates) == 0:
            raise RuntimeError(f"No line found incident to bus {bus}.")
        return candidates[0]

    @staticmethod
    def find_weakest_branch_leaf_bus(net):
        """Finds the most loaded line"""
        net_check = copy.deepcopy(net)
        GridOps.fix_element_dtypes(net_check)
        if not GridOps.run_pf(net_check, context="find_weakest_branch_leaf_bus", print_error=False):
            raise RuntimeError("Base power flow failed: cannot identify the weakest branch.")

        worst_line = net_check.res_line["loading_percent"].idxmax()
        from_bus = int(net_check.line.at[worst_line, "from_bus"])
        to_bus = int(net_check.line.at[worst_line, "to_bus"])

        graph = pp_topology.create_nxgraph(net_check, respect_switches=True)
        root = int(net_check.ext_grid["bus"].iloc[0])

        if root not in graph or from_bus not in graph or to_bus not in graph:
            return to_bus, worst_line
        # hop count from the ext_grid bus (weight=None -> every branch counts 1); unreachable buses are inf
        hops = pp_topology.calc_distance_to_bus(net_check, root, respect_switches=True, weight=None)
        dist = {int(b): int(d) for b, d in hops.items() if np.isfinite(d)}
        if from_bus not in dist or to_bus not in dist:
            return to_bus, worst_line

        if dist[from_bus] > dist[to_bus]:                       # orient the line away from the root
            from_bus, to_bus = to_bus, from_bus

        tree = nx.bfs_tree(graph, root)
        order = list(tree.nodes)                                # BFS order
        reach = {}
        for node in reversed(order):                            # farthest hop distance inside each subtree
            kids = list(tree.successors(node))
            reach[node] = max([dist[node]] + [reach[k] for k in kids])

        current = to_bus
        while True:
            kids = list(tree.successors(current))
            if not kids:
                break
            current = max(kids, key=lambda k: (reach[k], -int(k)))

        # the leaf must carry a line (a bus that only hangs on a trafo cannot host the mall load)
        has_line = set(net_check.line["from_bus"].astype(int)) | set(net_check.line["to_bus"].astype(int))
        while current not in has_line:
            preds = list(tree.predecessors(current))
            if not preds:
                raise RuntimeError("find_weakest_branch_leaf_bus: no bus with an incident line found.")
            current = preds[0]

        return int(current), worst_line

    @staticmethod
    def root_bus_path(net, graph, target_bus, target_label="target_bus"):
        """Validates root (ext_grid bus) and target_bus are both connected in
    graph, and returns (root, bus_path) via shortest_path. Used by
    find_downstream_elements."""

        root = net.ext_grid["bus"].iloc[0]
        if root not in graph:
            raise RuntimeError(f"ext_grid bus {root} has no connectivity (line or trafo) in this net.")
        if target_bus not in graph:
            raise RuntimeError(f"{target_label} {target_bus} has no connectivity (line or trafo) in this net.")
        return root, nx.shortest_path(graph, root, target_bus)

    @staticmethod
    def find_downstream_elements(net, mall_bus):
        """Every load and sgen sitting electrically on the mall_bus.
    Switch-respecting graph and the subtree walk both come from pandapower.topology
    (create_nxgraph already honours open switches and out-of-service elements)."""
        graph = pp_topology.create_nxgraph(net, respect_switches=True)
        _, bus_path = FeederTopology.root_bus_path(net, graph, mall_bus, "mall_bus")

        # buses reachable from mall_bus without stepping back through its parent on the root path
        blocked = [bus_path[-2]] if len(bus_path) > 1 else []
        subtree_buses = set(pp_topology.connected_component(graph, mall_bus, notravbuses=blocked))

        downstream_buses = set(bus_path) | subtree_buses

        downstream_sgen_idx = list(net.sgen.index[net.sgen["bus"].isin(downstream_buses)])
        downstream_load_idx = list(net.load.index[net.load["bus"].isin(downstream_buses)])

        return downstream_sgen_idx, downstream_load_idx, downstream_buses

    @staticmethod
    def compute_hierarchical_layout(net, leaf_step=SLD_LEAF_STEP, depth_step=SLD_DEPTH_STEP):
        """
        Creates a schematic feeder layout using actual line lengths for
        horizontal spacing and a hierarchical layout for vertical spacing.
        Writes the calculated positions into net.bus.geo and returns a
        {bus: branch_id} map, with branch_id=-1 for the root bus.
        """
        geo = net.bus.geo 
        missing_geo = (
            geo.isna()
            | (geo.astype(str).str.strip() == "")
            | (geo.astype(str) == "None")
        )
        if not missing_geo.any():
            return {}
        print(
            f"[plot] {missing_geo.sum()} bus(es) missing geo data "
            "-> computing length-scaled feeder layout"
        )
        mg = pp_topology.create_nxgraph(net, respect_switches=False)
        if len(net.ext_grid):
            root = net.ext_grid["bus"].iloc[0]
        else:
            root = net.bus.index[0]
        # Build a feeder tree rooted at the external grid.
        levels = {root: 0}
        children_by_parent = {}
        bfs_edges = list(nx.bfs_edges(mg, root))

        for parent, child in bfs_edges:
            levels[child] = levels[parent] + 1
            children_by_parent.setdefault(parent, []).append(child)

        # Find a typical line length for connections without a matching line.
        if len(net.line) and "length_km" in net.line.columns:
            valid_lengths = pd.to_numeric(
                net.line["length_km"], errors="coerce"
            )
            valid_lengths = valid_lengths[
                valid_lengths.notna() & (valid_lengths > 0)
            ]
        else:
            valid_lengths = pd.Series(dtype=float)

        reference_length_km = (
            float(valid_lengths.median())
            if not valid_lengths.empty
            else 1.0
        )
        # Keep the typical line approximately depth_step units long.
        length_scale = depth_step / reference_length_km
        # Calculate horizontal positions using line lengths.
        x_pos = {root: 0.0}
        for parent, child in bfs_edges:
            matching_lines = net.line[
                (
                    (net.line["from_bus"] == parent)
                    & (net.line["to_bus"] == child)
                )
                | (
                    (net.line["from_bus"] == child)
                    & (net.line["to_bus"] == parent)
                )
            ]
            if not matching_lines.empty:
                edge_lengths = pd.to_numeric(
                    matching_lines["length_km"], errors="coerce"
                )
                edge_lengths = edge_lengths[
                    edge_lengths.notna() & (edge_lengths > 0)
                ]

                edge_length_km = (
                    float(edge_lengths.iloc[0])
                    if not edge_lengths.empty
                    else reference_length_km
                )
            else:
                # For example, a transformer connection without a line.
                edge_length_km = reference_length_km

            x_pos[child] = (
                x_pos[parent] + edge_length_km * length_scale
            )

        # Place buses not reachable from the root separately.
        unreached = [b for b in net.bus.index if b not in levels]

        for bus in unreached:
            levels[bus] = 0
            x_pos[bus] = 0.0

        # Calculate vertical positions so branches are spread out clearly.
        y_counter = [0.0]
        y_pos = {}

        def assign_y(bus):
            children = children_by_parent.get(bus, [])

            if not children:
                y = y_counter[0]
                y_counter[0] += leaf_step
                y_pos[bus] = y
                return y

            child_ys = [assign_y(child) for child in children]
            y = sum(child_ys) / len(child_ys)
            y_pos[bus] = y
            return y

        assign_y(root)

        for bus in unreached:
            if bus not in y_pos:
                y_pos[bus] = y_counter[0]
                y_counter[0] += leaf_step

        # Save all calculated coordinates in pandapower's geo column.
        for bus in net.bus.index:
            x = x_pos.get(bus, 0.0)
            y = y_pos.get(bus, 0.0)

            net.bus.at[bus, "geo"] = json.dumps({
                "type": "Point",
                "coordinates": [float(x), float(y)],
            })

        # Assign a branch ID based on the first branch leaving the root.
        branch_of = {}
        root_children = children_by_parent.get(root, [])

        for i, top_child in enumerate(root_children):
            stack = [top_child]

            while stack:
                bus = stack.pop()
                branch_of[bus] = i
                stack.extend(children_by_parent.get(bus, []))

        branch_of[root] = -1

        return branch_of

#####    Profile generation and network construction
class SimbenchProfiles:
    @staticmethod
    def _has_key(text, keys):
        text = str(text).lower()
        return any(k in text for k in keys)

    @staticmethod
    def _load_pool(codes, verbose=True):
        """Loads the SimBench grids once and collects ONE normalised shape per distinct profile name
        (elements with the same SimBench profile name have identical shapes, so duplicates are dropped)."""
        key = tuple(codes)
        if key in _SIMBENCH_POOL_CACHE:
            return _SIMBENCH_POOL_CACHE[key]
        has = SimbenchProfiles._has_key
        load_pool = {"residential": {}, "commercial": {}}
        sgen_pool = {"pv": {}, "wind": {}, "pv_fallback": {}}
        for code in key:
            try:
                sb_net = sb.get_simbench_net(code)
                absvals = sb.get_absolute_values(sb_net, profiles_instead_of_study_cases=True)
            except Exception as exc:                          # unknown code / missing data: skip this grid
                print(f"[SimBench] WARNING: could not load {code}: {exc}")
                continue

            # loads: shape = profile / its own annual maximum (a load never exceeds its nominal value)
            p_load = absvals[("load", "p_mw")].astype(float)
            p_load = p_load.loc[:, p_load.max() > 0.0]
            names = sb_net.load["profile"].reindex(p_load.columns).astype(str)
            for col, name in names.items():
                if has(name, SIMBENCH_EXCLUDE_KEYS):
                   continue
                kind = "residential" if has(name, SIMBENCH_RESIDENTIAL_KEYS) else "commercial"
                if name not in load_pool[kind]:
                    load_pool[kind][name] = (p_load[col] / p_load[col].max()).to_numpy(dtype=float)

            # sgens: shape = profile / installed power (per unit); max-normalised if p_mw is not the rating
            p_sgen = absvals[("sgen", "p_mw")].astype(float)
            p_sgen = p_sgen.loc[:, p_sgen.max() > 0.0]
            inst = sb_net.sgen["p_mw"].reindex(p_sgen.columns).astype(float)
            for col in p_sgen.columns:
                name = str(sb_net.sgen["profile"][col])
                text = name + (" " + str(sb_net.sgen["type"][col]) if "type" in sb_net.sgen.columns else "")
                if has(text, SIMBENCH_PV_KEYS):
                    kind = "pv"
                elif has(text, SIMBENCH_WIND_KEYS):
                    kind = "wind"
                elif has(text, SIMBENCH_PV_FALLBACK_KEYS):
                    kind = "pv_fallback"
                else:
                    continue                                   # hydro, biomass, ... are not used
                v = p_sgen[col]
                pu = v / inst[col] if (inst[col] > 0.0 and 0.2 <= v.max() / inst[col] <= 1.05) else v / v.max()#pu means per unit 
                sgen_pool[kind].setdefault(name, np.clip(pu.to_numpy(dtype=float), 0.0, 1.0))
        pools = {"load": {k: pd.DataFrame(v) for k, v in load_pool.items()},
                 "sgen": {k: pd.DataFrame(v) for k, v in sgen_pool.items()}}
        if verbose:
            print(f"[SimBench] pooled from {list(key)}")
            for grp in ("load", "sgen"):
                for k, df in pools[grp].items():
                    print(f"[SimBench]   {grp}/{k}: {df.shape[1]} distinct profile(s) {list(df.columns)}")
        _SIMBENCH_POOL_CACHE[key] = pools
        return pools

    @staticmethod
    def _align_to_calendar(arr, index):
        """Roll the SimBench year so weekday AND clock time match `index` (SimBench starts on a Friday 00:00).
        Otherwise weekday/weekend shapes would not line up with the real SES / heat data read for the same dates."""
        if len(arr) != len(index):
            raise ValueError(f"SimBench profile length {len(arr)} != index length {len(index)}")
        shift_days = (index[0].dayofweek - SIMBENCH_YEAR_START.dayofweek) % 7
        offset_steps = int(round((index[0] - index[0].normalize()).total_seconds() / 900.0))   # 00:15 start -> 1
        return np.roll(arr, -(shift_days * 96 + offset_steps), axis=0)

    @staticmethod
    def _assign(src, n, rng):
        """Column positions for n elements: distinct SimBench profiles first, then cycle (seeded -> reproducible)."""
        order = rng.permutation(src.shape[1])
        return [int(order[i % len(order)]) for i in range(n)]

    @staticmethod
    def build(nominal, index, seed=GRID_PROFILE_SEED, load_peak_scale=1.0):
        """Profile dict {("load","p_mw"), ("load","q_mvar"), ("sgen","p_mw")} -> DataFrame (RangeIndex, element-id
        columns, len(index) rows). Every CIGRE element gets the shape of  SimBench profile of matching type."""
        pool = SimbenchProfiles._load_pool(SIMBENCH_CODES)
        rng = np.random.default_rng(seed)
        T = len(index)
        log = {}

        # ---- loads
        load_ids = nominal["load_p"].index
        n_load = len(load_ids)
        if nominal.get("load_kind") is not None:
            kinds = nominal["load_kind"].reindex(load_ids).to_numpy()
        else:
            kinds = rng.choice(["residential", "commercial"], size=n_load, p=[0.6, 0.4])
        shape_mat = np.empty((T, n_load), dtype=float)
        for kind in ("residential", "commercial"):
            cols = np.flatnonzero(kinds == "residential") if kind == "residential" else np.flatnonzero(kinds != "residential")
            if not len(cols):
                continue
            src = pool["load"][kind]
            if src.shape[1] == 0:
                print(f"[SimBench] WARNING: no '{kind}' load profiles found; using all load profiles.")
                src = pd.concat(pool["load"].values(), axis=1)
            for j, c in zip(cols, SimbenchProfiles._assign(src, len(cols), rng)):
                shape_mat[:, j] = src.iloc[:, c].to_numpy(dtype=float)
                log[f"load {load_ids[j]}"] = src.columns[c]
        shape_mat = SimbenchProfiles._align_to_calendar(shape_mat, index)
        p_load = shape_mat * nominal["load_p"].to_numpy(dtype=float)[None, :] * float(load_peak_scale)
        q_load = shape_mat * nominal["load_q"].to_numpy(dtype=float)[None, :] * float(load_peak_scale)

        # ---- sgens: every PV / wind unit gets the shape of one SimBench PV / wind profile; CHP, fuel cell = flat
        sgen_ids = nominal["sgen_p"].index
        n_sgen = len(sgen_ids)
        p_sgen = np.empty((T, n_sgen), dtype=float)
        if n_sgen:
            kinds_s = (nominal["sgen_kind"].reindex(sgen_ids).to_numpy() if nominal.get("sgen_kind") is not None
                       else np.array(["pv"] * n_sgen))
            for kind in ("pv", "wind"):
                cols = np.flatnonzero(kinds_s == kind)
                if not len(cols):
                    continue
                src = pool["sgen"][kind]
                if src.shape[1] == 0 and kind == "pv" and pool["sgen"]["pv_fallback"].shape[1]:
                    print("[SimBench] WARNING: no explicit PV profile found; using aggregated LV renewable "
                          f"profiles {list(pool['sgen']['pv_fallback'].columns)} as PV shape.")
                    src = pool["sgen"]["pv_fallback"]
                if src.shape[1] == 0:
                    raise RuntimeError(f"No '{kind}' sgen profile in SimBench grids {list(SIMBENCH_CODES)}; add a grid "
                                       f"to SIMBENCH_CODES or adjust SIMBENCH_PV_KEYS / SIMBENCH_WIND_KEYS (see the "
                                       f"pool summary printed above).")
                for j, c in zip(cols, SimbenchProfiles._assign(src, len(cols), rng)):
                    p_sgen[:, j] = src.iloc[:, c].to_numpy(dtype=float)
                    log[f"sgen {sgen_ids[j]}"] = src.columns[c]
            p_sgen[:, kinds_s == "flat"] = 1.0
            p_sgen = SimbenchProfiles._align_to_calendar(p_sgen, index)
            p_sgen = p_sgen * nominal["sgen_p"].to_numpy(dtype=float)[None, :]
        print("[SimBench] element -> SimBench profile:", log)

        return {("load", "p_mw"): pd.DataFrame(p_load, columns=load_ids),
                ("load", "q_mvar"): pd.DataFrame(q_load, columns=load_ids),
                ("sgen", "p_mw"): pd.DataFrame(p_sgen, columns=sgen_ids)}

class GridSource:
    @staticmethod
    def _build_raw_net():
        """pandapower.networks.create_cigre_network_mv(): CIGRE MV benchmark, 20 kV, 15 buses, 110/20 kV.
        Two trafos (25 MVA) feed a meshed-but-operated-radial grid (ring lines are open at one end), one
        ext_grid at the 110 kV bus. Load p_mw are the nominal (peak) values of the benchmark: 44.7 MW in
        total, i.e. trafo 0-1 is at ~101 % if ALL loads peak at once -- it is the diversity between the
        individually normalised profiles that keeps the base case feasible.
        CIGRE_WITH_DER: False | "pv_wind" | "all" (see pandapower docs)."""
        net = pn.create_cigre_network_mv(with_der=CIGRE_WITH_DER)

        # Both trafos carry a 30 deg vector-group shift; pandapower's Ward equivalent cannot represent it when
        # the trafos are in the eliminated region (reduced net converges to a wrong state). The shift only moves
        # angles, not magnitudes / loading / losses here, so it is set to 0.
        net.trafo["shift_degree"] = 0.0

        # The script has no battery dispatch and prepare_grid_for_opf() does not fix storages, so the two
        # batteries of with_der="all" would silently become OPF variables. They are removed.
        if len(net.storage):
            net.storage.drop(net.storage.index, inplace=True)

        sgen_type = net.sgen["type"].astype(str) if len(net.sgen) else pd.Series(dtype=str)
        sgen_kind = sgen_type.map(lambda t: "pv" if t == "PV" else ("wind" if t == "WP" else "flat"))
        nominal = {
            "load_p": (net.load["p_mw"] * net.load["scaling"]).astype(float),
            "load_q": (net.load["q_mvar"] * net.load["scaling"]).astype(float),
            # "Load R*" = residential feeder loads, "Load CI*" = commercial / industrial loads
            "load_kind": net.load["name"].astype(str).map(lambda n: "residential" if n.startswith("Load R") else "commercial"),
            "sgen_p": net.sgen["p_mw"].astype(float).copy(),
            "sgen_kind": sgen_kind,                              # PV -> solar shape, WP -> wind, fuel cell / CHP -> flat
        }
        return net, nominal

    @staticmethod
    def load_net(grid_code):
        """Returns the cleaned template net and remembers the nominal (peak) values for the profiles."""
        if grid_code != SUPPORTED_GRID_CODE:
            raise ValueError(f"This script variant only supports GRID_CODE={SUPPORTED_GRID_CODE!r}, got {grid_code!r}.")
        net, nominal = GridSource._build_raw_net()

        # Loads sit at their nominal (peak) value in the template, `scaling` is neutralised because the
        # profile code writes p_mw/q_mvar directly and never looks at `scaling`.
        net.load["p_mw"] = nominal["load_p"].reindex(net.load.index).to_numpy(dtype=float)
        net.load["q_mvar"] = nominal["load_q"].reindex(net.load.index).to_numpy(dtype=float)
        net.load["scaling"] = 1.0
        if len(net.sgen):
            net.sgen["p_mw"] = 0.0          # stress snapshot: no PV when the weakest branch is searched
            net.sgen["q_mvar"] = 0.0
            net.sgen["scaling"] = 1.0
        _GRID_NOMINAL_CACHE[grid_code] = nominal

        # Real geo coordinates (lat/lon or schematic) do not match the SLD symbol sizes (layout units):
        # drop them and let the hierarchical feeder-tree layout write consistent coordinates.
        net.bus["geo"] = None
        FeederTopology.compute_hierarchical_layout(net)
        return net

    @staticmethod
    def get_profiles(net=None, grid_code=None):
        """Return SimBench-shaped CIGRE MV profiles using the legacy profile-dictionary layout."""
        grid_code = grid_code or GRID_CODE
        if grid_code not in _GRID_PROFILE_CACHE:
            if grid_code not in _GRID_NOMINAL_CACHE:
                GridSource.load_net(grid_code)
            index = pd.date_range(YEAR_START, periods=PROFILE_STEPS, freq="15min")
            _GRID_PROFILE_CACHE[grid_code] = SimbenchProfiles.build(
                _GRID_NOMINAL_CACHE[grid_code], index, seed=GRID_PROFILE_SEED,
                load_peak_scale=GRID_LOAD_PEAK_SCALE)
        return _GRID_PROFILE_CACHE[grid_code]

_NET_TEMPLATE_CACHE = {}
class NetFactory:
    @staticmethod
    def get_net_template(grid_code):
        """Caches the CIGRE MV net template per grid_code across scenario runs."""
        if grid_code not in _NET_TEMPLATE_CACHE:
            net = GridSource.load_net(grid_code)
            GridOps.fix_element_dtypes(net)
            GridOps.prepare_grid_for_opf(net)
            _NET_TEMPLATE_CACHE[grid_code] = net
        return copy.deepcopy(_NET_TEMPLATE_CACHE[grid_code])

    @staticmethod
    def build_base_net(mall_bus, q_mall_base_mvar=0.0, q_eps=1e-3, grid_code=None):
        grid_code = grid_code or GRID_CODE
        net_base = NetFactory.get_net_template(grid_code)
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

        mall_feeder_line_idx = FeederTopology.find_bus_feeder_line(net_base, mall_bus)

        return net_base, mall_load_idx, mall_feeder_line_idx

class GridProfileApplier:
    @staticmethod
    def apply_scaled_column(net, table_name, col, native_values, scale, scoped_idx):
        """Writes native_values * scale into net[table_name][col]. If
    scoped_idx is given, only elements in it get scale; everything else is
    written unscaled (factor 1.0). Vectorised: one factor Series, one assignment."""
        ids = native_values.index
        factor = pd.Series(1.0 if scoped_idx is not None else scale, index=ids)
        if scoped_idx is not None:
            factor[ids.isin(list(scoped_idx))] = scale
        net[table_name].loc[ids, col] = native_values * factor

    @staticmethod
    def apply_profile_for_hour(net, profiles, idx, hour, load_scale=1.0, sgen_scale=1.0,
                                         scoped_sgen_idx=None, scoped_load_idx=None):
        if idx.tz is not None:
            hour = hour.tz_localize(idx.tz) if hour.tzinfo is None else hour.tz_convert(idx.tz)
        elif hour.tzinfo is not None:
            hour = hour.tz_localize(None)

        try:
            step = idx.get_loc(hour)
        except KeyError:
            # Hourly SES timestamps can fall between quarter-hour profile stamps. Select the
            # nearest profile point, but reject gaps larger than half an hour.
            target = pd.Timestamp(hour)
            if idx.tz is not None and target.tzinfo is None:
                target = target.tz_localize(idx.tz)
            elif idx.tz is None and target.tzinfo is not None:
                target = target.tz_localize(None)
            pos = int(idx.get_indexer([target], method="nearest")[0])
            if pos < 0 or abs((idx[pos] - target).total_seconds()) > 1800:
                raise KeyError(f"No profile timestamp close to {hour!r}")
            step = pos

        GridProfileApplier.apply_scaled_column(net, "load", "p_mw", profiles[("load", "p_mw")].iloc[step], load_scale, scoped_load_idx)
        GridProfileApplier.apply_scaled_column(net, "load", "q_mvar", profiles[("load", "q_mvar")].iloc[step], load_scale, scoped_load_idx)

        if len(profiles[("sgen", "p_mw")].columns):
            GridProfileApplier.apply_scaled_column(net, "sgen", "p_mw", profiles[("sgen", "p_mw")].iloc[step], sgen_scale, scoped_sgen_idx)

#####    OPF time-series engine
#PM_4: check why the plot stors only mall_feeder_line_loading_before_pct(after_pct), this should plot the overloads on all net.res_line
# net.res_line.loading_percent.max()
class OpfTimeseriesRunner:
    @staticmethod
    def build_opf_results(selected_time, scenario_label, status,
                            flex_activation_required, p_mall_min_mw, p_mall_base_mw,
                            p_mall_max_mw, p_mall_opf_mw, q_mall_opf_mvar,
                            p_grid_setpoint_kw, p_device_setpoint_kw,
                            mall_bus_vm_pu_before=np.nan, mall_bus_vm_pu_after=np.nan,
                            mall_feeder_line_loading_before_pct=np.nan,
                            mall_feeder_line_loading_after_pct=np.nan,
                            max_line_loading_before_pct=np.nan, max_line_loading_after_pct=np.nan,
                            max_trafo_loading_before_pct=np.nan, max_trafo_loading_after_pct=np.nan,
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
               "max_line_loading_before_pct": max_line_loading_before_pct,
               "max_line_loading_after_pct": max_line_loading_after_pct,
               "max_trafo_loading_before_pct": max_trafo_loading_before_pct,
               "max_trafo_loading_after_pct": max_trafo_loading_after_pct,
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

    @staticmethod
    def run_opf_timeseries_for_scenario(scenario_label, net_base, mall_load, mall_feeder_line_idx,
                                        profiles, idx, time_series_data_base, residual_mall_load_kw,
                                        grid_load_scale, grid_sgen_scale,
                                        q_mall_base_mvar, q_eps, initial_soc=INIT_SOC,
                                        scoped_sgen_idx=None, scoped_load_idx=None,
                                        capture_violated_snapshots=False):
        updated_flex_target_kw = np.zeros(len(time_series_data_base))
        opf_rows = []
        res_base_rows = []
        res_actual_rows = []
        flex_bounds_rows = []
        violation_detail_rows = []
        # Lightweight per-element metrics used by the whole-network SLD comparison.
        # Only scalar measurements are stored, not full copies of every network.
        sld_element_metric_rows = []
        # HYPERCAP :This dictionary  stores ONLY the final residual violating
        # network state (after Mall flexibility / actual dispatch / PF).
        # One (scenario, timestamp) residual violation -> one snapshot.
        violated_net_snapshots = {}

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
                start=start_t,
                end=end_t,
                time_resolution=time_resolution,
                frequency=frequency,
                collect_bounds=True,
                allow_export=allow_export_to_grid,
                init_soc=soc_current,
                previous_controller_results=prev_controller_results,
                previous_chp_downtime=prev_chp_downtime,
                return_state=True,
                verbose=False,
                )

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
            dispatch_infeasible = False
            max_line_loading_before = np.nan
            max_line_loading_after = np.nan
            max_trafo_loading_before = np.nan
            max_trafo_loading_after = np.nan

            net = copy.deepcopy(net_base)

            GridProfileApplier.apply_profile_for_hour(
                net, profiles, idx, selected_time,
                load_scale=grid_load_scale,
                sgen_scale=grid_sgen_scale,
                scoped_sgen_idx=scoped_sgen_idx,
                scoped_load_idx=scoped_load_idx)

            net.load.at[mall_load, "p_mw"] = p_mall_base_mw
            net.load.at[mall_load, "q_mvar"] = q_mall_base_mvar
            net.load.at[mall_load, "min_p_mw"] = p_mall_min_mw
            net.load.at[mall_load, "max_p_mw"] = p_mall_max_mw
            net.load.at[mall_load, "min_q_mvar"] = q_mall_base_mvar - q_eps
            net.load.at[mall_load, "max_q_mvar"] = q_mall_base_mvar + q_eps

            if not GridOps.run_pf(
                net,
                context=f"[{scenario_label}] {selected_time} (baseline, mall attached)",
                print_error=False):

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
                mall_vm_before = net.res_bus.at[
                    net.load.at[mall_load, "bus"], "vm_pu"]
                mall_line_before = net.res_line.at[
                    mall_feeder_line_idx, "loading_percent"]
                if len(net.res_line) and "loading_percent" in net.res_line:
                    max_line_loading_before = float(net.res_line["loading_percent"].max())
                if len(net.res_trafo) and "loading_percent" in net.res_trafo:
                    max_trafo_loading_before = float(net.res_trafo["loading_percent"].max())

                has_violation_before, violations_before = GridOps.check_grid_violations(net)
                SldPlotter.capture_element_metrics(
                    net, selected_time, "before", sld_element_metric_rows
                )

                if has_violation_before:
                    GridOps.record_violation_details(
                        violation_detail_rows,
                        selected_time,
                        "before",
                        violations_before,
                        net
                    )
                if not has_violation_before:
                    status = "no_violation_no_flex_needed"
                    flex_activation_required = False
                    v_after = v_before
                    violations_after = violations_before
                    mall_vm_after = mall_vm_before
                    mall_line_after = mall_line_before
                    max_line_loading_after = max_line_loading_before
                    max_trafo_loading_after = max_trafo_loading_before
                    # No flexibility action was needed, so the solved state is also
                    # the after-state for the component comparison.
                    SldPlotter.capture_element_metrics(
                        net, selected_time, "after", sld_element_metric_rows
                    )

                elif not bounds_feasible:
                    # No feasible flexibility range exists. Re-run the unchanged baseline
                    # dispatch as the explicit post-decision PF, then check actual limits and
                    # capture only a confirmed residual state for reinforcement planning.
                    flex_activation_required = True
                    net.load.at[mall_load, "p_mw"] = p_mall_base_mw
                    net.load.at[mall_load, "q_mvar"] = q_mall_base_mvar
                    if GridOps.run_pf(net, context=f"[{scenario_label}] {selected_time} after infeasible flexibility", print_error=False):
                        v_after = net.res_bus.vm_pu.copy()
                        mall_vm_after = net.res_bus.at[net.load.at[mall_load, "bus"], "vm_pu"]
                        mall_line_after = net.res_line.at[mall_feeder_line_idx, "loading_percent"]
                        max_line_loading_after = float(net.res_line["loading_percent"].max()) if len(net.res_line) else np.nan
                        max_trafo_loading_after = float(net.res_trafo["loading_percent"].max()) if len(net.res_trafo) else np.nan
                        has_violation_after, violations_after = GridOps.check_grid_violations(net)
                        SldPlotter.capture_element_metrics(
                            net, selected_time, "after", sld_element_metric_rows
                        )
                        if has_violation_after:
                            GridOps.record_violation_details(violation_detail_rows, selected_time, "after", violations_after, net)
                            if capture_violated_snapshots:
                                violated_net_snapshots[selected_time] = copy.deepcopy(net)
                        status = "flexibility_infeasible_remaining_violations" if has_violation_after else "flexibility_infeasible"
                    else:
                        status = "pf_after_infeasible_flexibility_failed"
                        v_after = None
                        violations_after = None
                        mall_vm_after = np.nan
                        mall_line_after = np.nan

                else:
                    flex_activation_required = True

                    p_mall_opf_mw = GridOps.run_mall_opf(
                        net,
                        mall_load,
                        p_mall_base_mw)

                    opf_failed = p_mall_opf_mw is None

                    if opf_failed:
                        has_overload = (
                            len(violations_before["line_overload"]) > 0 or
                            len(violations_before["trafo_overload"]) > 0
                        )

                        pure_overvoltage = (
                            len(violations_before["overvoltage"]) > 0 and
                            len(violations_before["undervoltage"]) == 0 and
                            not has_overload
                        )

                        if pure_overvoltage:
                            fallback_candidates = [
                                p_mall_max_mw,
                                p_mall_min_mw
                            ]
                        else:
                            fallback_candidates = [
                                p_mall_min_mw,
                                p_mall_max_mw
                            ]

                        best_score = np.inf
                        best_p_mw = fallback_candidates[0]

                        for p_candidate_mw in fallback_candidates:
                            net.load.at[mall_load, "p_mw"] = p_candidate_mw
                            net.load.at[mall_load, "q_mvar"] = q_mall_base_mvar

                            if not GridOps.run_pf(
                                net,
                                context=f"fallback PF at {selected_time}",
                                print_error=False):
                                continue

                            voltage = net.res_bus.vm_pu

                            score = np.maximum(
                                v_min_pu_std - voltage,
                                0.0
                            ).sum()

                            score += np.maximum(
                                voltage - v_max_pu_std,
                                0.0
                            ).sum()

                            if len(net.line):
                                score += (
                                    np.maximum(
                                        net.res_line.loading_percent -
                                        loading_percent_max_std,
                                        0.0
                                    ).sum() / 100.0
                                )

                            if len(net.trafo):
                                score += (
                                    np.maximum(
                                        net.res_trafo.loading_percent -
                                        loading_percent_max_std,
                                        0.0
                                    ).sum() / 100.0
                                )

                            if score < best_score:
                                best_score = score
                                best_p_mw = p_candidate_mw

                        p_mall_opf_mw = best_p_mw
                        q_mall_opf_mvar = q_mall_base_mvar

                    else:
                        q_mall_opf_mvar = net.res_load.at[
                            mall_load, "q_mvar"]

                    p_grid_setpoint_kw = p_mall_opf_mw * 1000.0
                    p_device_setpoint_kw = (
                        residual_t_kw[0] - p_grid_setpoint_kw
                    )

                    updated_flex_target_kw[selected_time_idx] = (
                        p_device_setpoint_kw
                    )

                    try:
                        res_actual_t, _, state_actual_t = run_mall_case_with_bounds(
                            time_series_data_base=time_series_t,
                            flex_target_kw=np.asarray([p_device_setpoint_kw]),
                            residual_mall_load_kw=residual_t_kw,
                            start=start_t,
                            end=end_t,
                            time_resolution=time_resolution,
                            frequency=frequency,
                            collect_bounds=False,
                            allow_export=allow_export_to_grid,
                            init_soc=soc_current,
                            previous_controller_results=prev_controller_results,
                            previous_chp_downtime=prev_chp_downtime,
                            return_state=True,
                            verbose=False,
                           )
                    except ValueError as exc:
                        # The prosumer cannot deliver this setpoint without breaking its own heat
                        # balance (e.g. storage full -> "Excess energy detected"). The mall therefore
                        # cannot provide this flexibility: keep the baseline dispatch, so the grid
                        # violation stays and the hour counts as a residual (reinforcement) hour.
                        dispatch_infeasible = True
                        print(f"[{scenario_label}] {selected_time}: flexibility dispatch infeasible "
                              f"({str(exc)[:80]}) -> baseline dispatch kept, hour stays violated.",
                              flush=True)
                        res_actual_t, state_actual_t = res_base_t, state_base_t

                    res_actual_t = res_actual_t.iloc[[0]].copy()

                    p_actual_grid_mw = (
                        res_actual_t.iloc[0]["p_grid_kw"] / 1000.0
                    )

                    net.load.at[mall_load, "p_mw"] = p_actual_grid_mw
                    net.load.at[mall_load, "q_mvar"] = q_mall_opf_mvar

                    if GridOps.run_pf(
                        net,
                        context=f"[{scenario_label}] {selected_time} after actual dispatch",
                        print_error=False):

                        v_after = net.res_bus.vm_pu.copy()

                        mall_vm_after = net.res_bus.at[
                            net.load.at[mall_load, "bus"], "vm_pu"]

                        mall_line_after = net.res_line.at[
                            mall_feeder_line_idx, "loading_percent"]
                        if len(net.res_line) and "loading_percent" in net.res_line:
                            max_line_loading_after = float(net.res_line["loading_percent"].max())
                        if len(net.res_trafo) and "loading_percent" in net.res_trafo:
                            max_trafo_loading_after = float(net.res_trafo["loading_percent"].max())

                        has_violation_after, violations_after = (
                            GridOps.check_grid_violations(net)
                        )
                        SldPlotter.capture_element_metrics(
                            net, selected_time, "after", sld_element_metric_rows
                        )

                        if has_violation_after:
                            GridOps.record_violation_details(
                                violation_detail_rows,
                                selected_time,
                                "after",
                                violations_after,
                                net
                            )
                            
                            if capture_violated_snapshots:
                                violated_net_snapshots[selected_time] = (
                                    copy.deepcopy(net)
                                )

                        if opf_failed:
                            status = (
                                "opf_failed_fallback_violations"
                                if has_violation_after
                                else "opf_failed_fallback_resolved"
                            )
                        else:
                            status = (
                                "opf_success_remaining_violations"
                                if has_violation_after
                                else "opf_success_violations_resolved"
                            )
                        if dispatch_infeasible:
                            status = "flexibility_infeasible_remaining_violations" if has_violation_after else "flexibility_infeasible"

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

            opf_rows.append(
                OpfTimeseriesRunner.build_opf_results(
                    selected_time=selected_time,
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
                    max_line_loading_before_pct=max_line_loading_before,
                    max_line_loading_after_pct=max_line_loading_after,
                    max_trafo_loading_before_pct=max_trafo_loading_before,
                    max_trafo_loading_after_pct=max_trafo_loading_after,
                    v_before=v_before,
                    v_after=v_after,
                    violations_before=violations_before,
                    violations_after=violations_after
                )
            )

        opf_results_df = pd.DataFrame(opf_rows).set_index("time")
        res_base = pd.DataFrame(res_base_rows)
        res_actual = pd.DataFrame(res_actual_rows)
        bounds_df = pd.DataFrame(flex_bounds_rows)

        res_base.index = time_series_data_base.index
        res_actual.index = time_series_data_base.index
        bounds_df.index = time_series_data_base.index

        violation_details_df = pd.DataFrame(
            violation_detail_rows,
            columns=[
                "time",
                "phase",
                "violation_type",
                "element_id",
                "location",
                "value",
                "limit",
                "excess",
                "normalized_severity_pct",
            ]
        )
        element_metrics_df = pd.DataFrame(
            sld_element_metric_rows,
            columns=[
                "time", "phase", "element_type", "element_id", "value",
                "limit", "limit_low", "limit_high", "stress",
                "violation_excess", "is_violation"
            ]
        )
        return (
            opf_results_df,
            updated_flex_target_kw,
            res_base,
            res_actual,
            bounds_df,
            violation_details_df,
            violated_net_snapshots,
            element_metrics_df,
        )

#####   Plotting, diagnostics, and reports
def _sld_table(net, name):
    """net[name] if it exists and has rows, else None."""
    return net[name] if name in net and net[name] is not None and len(net[name]) else None

def _sld_has_geo(net, bus):
    g = net.bus.at[bus, "geo"]
    return not pd.isna(g) and str(g).strip() not in ("", "None")

def _sld_in_service(df):
    return (df["in_service"].astype(bool) if "in_service" in df.columns
            else pd.Series(True, index=df.index))

def _sld_branches_with_geo(net, df, a="from_bus", b="to_bus"):
    ok = [_sld_has_geo(net, r[a]) and _sld_has_geo(net, r[b]) for _, r in df.iterrows()]
    return df.index[ok]

def _sld_as_list(c):
    """create_*_collection() returns one Collection or a list/tuple of them -> always a list."""
    if c is None:
        return []
    return [x for x in (c if isinstance(c, (list, tuple)) else [c]) if x is not None]

class SldPlotter:
    @staticmethod
    def style_axis(ax, ylabel, title, legend_loc="upper right"):
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(loc=legend_loc)
        ax.grid(True, alpha=0.3)

    @staticmethod
    def save_and_show_fig(fig, filename):
        fig.tight_layout()
        fig.savefig(filename, dpi=200, bbox_inches="tight")
        plt.close(fig)
        print(f"[plot] Saved: {filename}")

    @staticmethod
    def _bus_xy(net, bus):
        coords = json.loads(net.bus.at[bus, "geo"])['coordinates']
        return coords[0], coords[1]

    @staticmethod
    def capture_element_metrics(net, timestamp, phase, rows):
        """Append solved bus-voltage, line-loading and trafo-loading measurements.
        Only in-service elements with finite solved results are stored. Bus stress
        is based on distance from the allowed voltage band; line/trafo stress is
        loading divided by its applicable limit. Lower stress is better.
        """
        timestamp = pd.Timestamp(timestamp)
        # Bus voltage and its permitted range.
        if "res_bus" in net and net.res_bus is not None and "vm_pu" in net.res_bus.columns:
            for bus_id, result in net.res_bus.iterrows():
                if bus_id not in net.bus.index:
                    continue
                bus_row = net.bus.loc[bus_id]
                if "in_service" in bus_row.index and not bool(bus_row["in_service"]):
                    continue
                try:
                    value = float(result["vm_pu"])
                    low = float(bus_row["min_vm_pu"]) if "min_vm_pu" in bus_row.index and pd.notna(bus_row["min_vm_pu"]) else float(v_min_pu_std)
                    high = float(bus_row["max_vm_pu"]) if "max_vm_pu" in bus_row.index and pd.notna(bus_row["max_vm_pu"]) else float(v_max_pu_std)
                except (TypeError, ValueError):
                    continue
                if not (math.isfinite(value) and math.isfinite(low) and math.isfinite(high)) or high < low:
                    continue
                span = max(high - low, 1e-3)
                half_span = span / 2.0
                midpoint = (high + low) / 2.0
                if value < low:
                    excess = low - value
                    stress = 1.0 + excess / span
                elif value > high:
                    excess = value - high
                    stress = 1.0 + excess / span
                else:
                    excess = 0.0
                    stress = abs(value - midpoint) / half_span
                rows.append({
                    "time": timestamp, "phase": str(phase), "element_type": "bus",
                    "element_id": int(bus_id), "value": value, "limit": np.nan,
                    "limit_low": low, "limit_high": high, "stress": float(stress),
                    "violation_excess": float(excess),
                    "is_violation": bool(excess > 1e-9),
                })

        # Lines and transformers: lower loading relative to the limit is better.
        for element_type, result_name, table_name in (
                ("line", "res_line", "line"),
                ("trafo", "res_trafo", "trafo")):
            if result_name not in net or net[result_name] is None or "loading_percent" not in net[result_name].columns:
                continue
            result_table = net[result_name]
            source_table = net[table_name]
            for element_id, result in result_table.iterrows():
                if element_id not in source_table.index:
                    continue
                source_row = source_table.loc[element_id]
                if "in_service" in source_row.index and not bool(source_row["in_service"]):
                    continue
                try:
                    value = float(result["loading_percent"])
                    limit = float(source_row["max_loading_percent"]) if "max_loading_percent" in source_row.index and pd.notna(source_row["max_loading_percent"]) else float(loading_percent_max_std)
                except (TypeError, ValueError):
                    continue
                if not (math.isfinite(value) and math.isfinite(limit)) or limit <= 0:
                    continue
                excess = max(value - limit, 0.0)
                rows.append({
                    "time": timestamp, "phase": str(phase), "element_type": element_type,
                    "element_id": int(element_id), "value": value, "limit": limit,
                    "limit_low": np.nan, "limit_high": np.nan,
                    "stress": value / limit, "violation_excess": excess,
                    "is_violation": bool(value > limit + 1e-9),
                })

    @staticmethod
    def build_element_change_labels(element_metrics_df, timestamp):
        """Build compact,  status labels for every monitored bus/line/trafo.
        Returns (labels_dict, outcome_dataframe). The comparison is for one
        timestamp, comparing the solved before and after states.
        """
        if element_metrics_df is None or element_metrics_df.empty:
            return {}, pd.DataFrame(columns=[
                "time", "element_type", "element_id", "status", "before_value",
                "after_value", "unit", "before_violation", "after_violation"
            ])

        metrics = element_metrics_df.copy()
        metrics["_time_utc"] = pd.to_datetime(metrics["time"], utc=True, errors="coerce")
        target_time = pd.to_datetime(timestamp, utc=True, errors="coerce")
        rows_at_time = metrics[metrics["_time_utc"].eq(target_time)]
        if rows_at_time.empty:
            return {}, pd.DataFrame(columns=[
                "time", "element_type", "element_id", "status", "before_value",
                "after_value", "unit", "before_violation", "after_violation"
            ])

        before = rows_at_time[rows_at_time["phase"].astype(str).eq("before")].drop_duplicates(
            ["element_type", "element_id"], keep="last"
        ).set_index(["element_type", "element_id"])
        after = rows_at_time[rows_at_time["phase"].astype(str).eq("after")].drop_duplicates(
            ["element_type", "element_id"], keep="last"
        ).set_index(["element_type", "element_id"])

        status_text = {
            "Improved": "↑ IMP",
            "Degraded": "↓ DEG",
            "Resolved": "✓ RES",
            "New violation": "! NEW",
            "Unchanged": "= SAME",
            "Not evaluated": "N/E",
        }
        status_color = {
            "Improved": SLD_OUTCOME_IMPROVED_COLOR,
            "Degraded": SLD_OUTCOME_DEGRADED_COLOR,
            "Resolved": SLD_OUTCOME_RESOLVED_COLOR,
            "New violation": SLD_OUTCOME_NEW_COLOR,
            "Unchanged": SLD_OUTCOME_UNCHANGED_COLOR,
            "Not evaluated": SLD_OUTCOME_NE_COLOR,
        }

        outcome_rows = []
        labels = {}
        all_keys = sorted(set(before.index.tolist()) | set(after.index.tolist()), key=lambda k: (str(k[0]), int(k[1])))
        for element_type, element_id in all_keys:
            b = before.loc[(element_type, element_id)] if (element_type, element_id) in before.index else None
            a = after.loc[(element_type, element_id)] if (element_type, element_id) in after.index else None
            before_value = float(b["value"]) if b is not None and pd.notna(b["value"]) else np.nan
            after_value = float(a["value"]) if a is not None and pd.notna(a["value"]) else np.nan
            before_violation = bool(b["is_violation"]) if b is not None and pd.notna(b["is_violation"]) else None
            after_violation = bool(a["is_violation"]) if a is not None and pd.notna(a["is_violation"]) else None
            status = "Not evaluated"
            change_pct = np.nan
            unit = "pu" if element_type == "bus" else "% loading" 

            if b is not None and a is not None and np.isfinite(before_value) and np.isfinite(after_value):
                if before_violation and not after_violation:
                    status = "Resolved"
                elif not before_violation and after_violation:
                    status = "New violation"
                else:
                    before_stress = float(b["stress"])
                    after_stress = float(a["stress"])
                    delta = after_stress - before_stress
                    tolerance = 1e-4 #even the smallest of the improvements will be shown 
                    if delta < -tolerance:
                        status = "Improved"
                    elif delta > tolerance:
                        status = "Degraded"
                    else:
                        status = "Unchanged"
                if element_type in {"line", "trafo"} and abs(before_value) > 1e-9:
                    change_pct = (before_value - after_value) / abs(before_value) * 100.0

            text = status_text[status]
            if status in {"Improved", "Degraded"} and element_type in {"line", "trafo"} and pd.notna(change_pct):
                text = f"{text} {abs(change_pct):.3g}%"
            labels[(str(element_type), int(element_id))] = {
                "text": text,
                "color": status_color[status],
                "status": status,
                "before_value": before_value,
                "after_value": after_value,
                "unit": unit,
            }
            outcome_rows.append({
                "time": pd.Timestamp(timestamp),
                "element_type": str(element_type),
                "element_id": int(element_id),
                "status": status,
                "before_value": before_value,
                "after_value": after_value,
                "unit": unit,
                "loading_change_pct": change_pct,
                "before_violation": before_violation,
                "after_violation": after_violation,
            })

        outcome_df = pd.DataFrame(outcome_rows)
        return labels, outcome_df

    @staticmethod
    def _bus_label_offset(net, bus):
        """Return a small point offset directed away from the bus's neighbours."""
        x, y = SldPlotter._bus_xy(net, bus)
        neighbours = []
        for table_name, a_col, b_col in (("line", "from_bus", "to_bus"), ("trafo", "hv_bus", "lv_bus")):
            table = _sld_table(net, table_name)
            if table is None:
                continue
            for _, row in table.iterrows():
                try:
                    if int(row[a_col]) == int(bus):
                        other = int(row[b_col])
                    elif int(row[b_col]) == int(bus):
                        other = int(row[a_col])
                    else:
                        continue
                    if _sld_has_geo(net, other):
                        neighbours.append(SldPlotter._bus_xy(net, other))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
        if neighbours:
            cx = sum(pt[0] for pt in neighbours) / len(neighbours)
            cy = sum(pt[1] for pt in neighbours) / len(neighbours)
        else:
            valid_xy = [SldPlotter._bus_xy(net, b) for b in net.bus.index if _sld_has_geo(net, b)]
            cx = sum(pt[0] for pt in valid_xy) / max(len(valid_xy), 1)
            cy = sum(pt[1] for pt in valid_xy) / max(len(valid_xy), 1)
        dx, dy = x - cx, y - cy
        norm = math.hypot(dx, dy)
        if norm < 1e-9:
            dx, dy, norm = 1.0, 1.0, math.sqrt(2.0)
        return 10.0 * dx / norm, 10.0 * dy / norm

    @staticmethod
    def print_scenario_summary(scenario_label, opf_results_df, violation_details_df, res_actual,
                                top_n_elements=5):
        """One consolidated box per scenario: how many hours violated, how many
    were resolved vs. remain (reinforcement candidates), tracking error, SOC
    range, total grid support energy, and the top few most frequently
    violated elements. Full hour-by-hour and per-violation detail is still
    available in the CSVs written by run_scenario -- this is a
    terminal-friendly digest, not a replacement for them."""
        counts = _status_summary_counts(opf_results_df)
        n_total = counts["n_total"]
        n_no_flex = counts["n_no_flex"]
        n_violated = counts["n_violated"]
        n_resolved = counts["n_resolved"]
        n_remaining = counts["n_remaining"]
        n_infeasible = counts["n_infeasible"]
        n_pf_failed = counts["n_pf_failed"]
        n_not_evaluated = counts["n_not_evaluated"]

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
        if n_not_evaluated:
            print(f"    - not evaluated:       {n_not_evaluated}")
        print(f"  Max tracking error:      {max_tracking_err:.3f} kW")
        print(f"  Thermal storage SOC:     {soc_min:.1f}% - {soc_max:.1f}%")
        print(f"  Total grid support:      {total_support_mwh:.2f} MWh")

        if not violation_details_df.empty:
            summary = (violation_details_df
                       .groupby(["violation_type", "location"])
                       .agg(occurrences=("value", "size"), worst_excess=("excess", "max"))
                       .sort_values("occurrences", ascending=False)
                       .head(top_n_elements))
            #print(f"  Top {min(top_n_elements, len(summary))} violated elements "
                  #f"(full detail in grid_violation_details_{scenario_label}.csv):")
            for (vtype, loc), row in summary.iterrows():
                print(f"    {loc:22s} {vtype:15s} {int(row['occurrences']):4d} occurrence(s), "
                      f"worst excess beyond limit = {row['worst_excess']:.3f}")
        print(f"{'-'*66}\n")

    @staticmethod
    def plot_prosumer_participation(opf_results_df, scenario_label, violation_details_df=None):
        fig = ScenarioHtmlReport._build_participation_chart_fig(opf_results_df, scenario_label,
                                              violation_details_df=violation_details_df)
        SldPlotter.save_and_show_fig(fig, f"prosumer_grid_participation_{scenario_label}.png")

    @staticmethod
    def plot_single_line_diagram(
            net, mall_bus, savepath="grid_single_line_diagram.png", title=None,
            leaf_step=SLD_LEAF_STEP, depth_step=SLD_DEPTH_STEP,
            violations=None, dominant_violation_type=None,
            dominant_severity_pct=None, violation_labels=None,
            element_change_labels=None, ax=None,
            draw_legend=True, draw_summary=True, draw_outcomes=True):
        """Render one SLD, optionally into an axis owned by a combined figure.

        Supplying ``ax`` lets paired SLDs reuse this renderer without creating,
        saving, or showing a separate figure for each panel.
        """
        owns_figure = ax is None
        if owns_figure:
            fig, ax = plt.subplots(figsize=SldPlotter._compute_sld_figsize(net))
        else:
            fig = ax.figure

        if mall_bus in net.bus.index and owns_figure:
            mall_lines = net.line[(net.line.from_bus == mall_bus) | (net.line.to_bus == mall_bus)]
            print(f"\n[mall connection] bus {mall_bus} connects via {len(mall_lines)} line(s):")
            for line_id, row in mall_lines.iterrows():
                other = row["to_bus"] if row["from_bus"] == mall_bus else row["from_bus"]
                print(f"    line {line_id} ('{row.get('name', '')}') <-> bus {other}")
            mall_trafos = net.trafo[(net.trafo.hv_bus == mall_bus) | (net.trafo.lv_bus == mall_bus)]
            if len(mall_trafos):
                print(f"    also directly on {len(mall_trafos)} trafo(s): {list(mall_trafos.index)}")

        violations = violations or {}
        labels = dict(element_change_labels or {}) if draw_outcomes else {}
        # Preserve support for the older violation_labels argument.
        legacy_types = {
            "undervoltage": "bus", "overvoltage": "bus",
            "line_overload": "line", "trafo_overload": "trafo",
        }
        if draw_outcomes:
            for (old_type, element_id), info in (violation_labels or {}).items():
                new_type = legacy_types.get(old_type)
                if new_type:
                    labels.setdefault((new_type, int(element_id)), info)

        FeederTopology.compute_hierarchical_layout(net, leaf_step=leaf_step, depth_step=depth_step)
        # Keep element sizes proportional to layout spacing.
        bus_size = min(leaf_step, depth_step) * 0.065
        elem_size = bus_size * 0.62
        collections = SldPlotter.build_sld_collections(
            net, mall_bus=mall_bus, violations=violations,
            bus_size=bus_size, elem_size=elem_size,
            dominant_violation_type=dominant_violation_type,
            label_buses=False,
        )
        pp_plot.draw_collections(
            collections, ax=ax, figsize=None, plot_colorbars=False,
            axes_visible=(False, False)
        )
        # Draw bus numbers explicitly; outcomes are appended only when requested.
        for bus_id in net.bus.index:
            if not _sld_has_geo(net, bus_id):
                continue
            try:
                x, y = SldPlotter._bus_xy(net, bus_id)
                info = labels.get(("bus", int(bus_id)))
                text = f"{int(bus_id)} {info['text']}" if info else str(int(bus_id))
                color = info.get("color", "#333333") if info else "#333333"
                kwargs = dict(
                    xy=(x, y), xytext=SldPlotter._bus_label_offset(net, bus_id),
                    textcoords="offset points", ha="center", va="center",
                    fontsize=6.7 if info else 7.2, color=color,
                    zorder=32, clip_on=False,
                )
                if info:
                    kwargs["fontweight"] = "bold"
                    kwargs["bbox"] = dict(
                        boxstyle="round,pad=0.10", facecolor="white",
                        edgecolor=color, linewidth=0.65, alpha=0.96)
                ax.annotate(text, **kwargs)
            except (KeyError, ValueError, TypeError, IndexError, json.JSONDecodeError):
                continue

        # Line/transformer outcome tags appear only if this panel shows outcomes.
        for (element_type, element_id), info in labels.items():
            if element_type not in {"line", "trafo"}:
                continue
            try:
                if element_type == "line":
                    if int(element_id) not in net.line.index:
                        continue
                    row = net.line.loc[int(element_id)]
                    a_bus, b_bus = int(row["from_bus"]), int(row["to_bus"])
                    prefix = "L"
                else:
                    if int(element_id) not in net.trafo.index:
                        continue
                    row = net.trafo.loc[int(element_id)]
                    a_bus, b_bus = int(row["hv_bus"]), int(row["lv_bus"])
                    prefix = "T"
                if not (_sld_has_geo(net, a_bus) and _sld_has_geo(net, b_bus)):
                    continue
                x1, y1 = SldPlotter._bus_xy(net, a_bus)
                x2, y2 = SldPlotter._bus_xy(net, b_bus)
                x, y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                dx, dy = x2 - x1, y2 - y1
                norm = math.hypot(dx, dy)
                if norm < 1e-9:
                    nx_offset, ny_offset = 0.0, 1.0
                else:
                    nx_offset, ny_offset = -dy / norm, dx / norm
                side = -1.0 if int(element_id) % 2 else 1.0
                offset_points = 10.0 + 2.5 * (int(element_id) % 4)
                offset = (
                            nx_offset * offset_points * side,
                            ny_offset * offset_points * side,
                        )
                text = f"{prefix}{int(element_id)} {info.get('text', '')}"
                color = info.get("color", "#333333")
                ax.annotate(
                    text, (x, y), xytext=offset, textcoords="offset points",
                    ha="center", va="center", fontsize=6.2,
                    color=color, fontweight="bold", zorder=33, clip_on=False,
                    bbox=dict(boxstyle="round,pad=0.10", facecolor="white",
                              edgecolor=color, linewidth=0.65, alpha=0.96),
                )
            except (KeyError, ValueError, TypeError, IndexError, json.JSONDecodeError):
                continue

        if draw_legend:
            extra_handles = []
            if violations:
                extra_handles.extend([
                    Line2D([0], [0], color=SLD_DOMINANT_VIOLATION_COLOR, linewidth=3.0,
                           label=(f"Dominant violation: {dominant_violation_type}" if dominant_violation_type else "Violation")),
                    Line2D([0], [0], color=SLD_OTHER_VIOLATION_COLOR, linewidth=2.2,
                           label="Other violation type"),
                ])
            if labels:
                outcome_legend = [
                    ("↑ IMP = improved", SLD_OUTCOME_IMPROVED_COLOR),
                    ("↓ DEG = degraded", SLD_OUTCOME_DEGRADED_COLOR),
                    ("✓ RES = resolved", SLD_OUTCOME_RESOLVED_COLOR),
                    ("! NEW = new violation", SLD_OUTCOME_NEW_COLOR),
                    ("= SAME = unchanged", SLD_OUTCOME_UNCHANGED_COLOR),
                    ("N/E = not evaluated", SLD_OUTCOME_NE_COLOR),
                ]
                extra_handles.extend([
                    Line2D([0], [0], marker="s", color="white", linestyle="none",
                           markerfacecolor=color, markeredgecolor=color, markersize=5,
                           label=legend_label)
                    for legend_label, color in outcome_legend
                ])
            SldPlotter._build_sld_legend(
                ax, extra_handles=extra_handles, net=net,
                fontsize=7.3 if labels else 8, ncol=6 if labels else 4,
            )

        if draw_summary:
            notes = []
            if dominant_violation_type:
                notes.append(f"Dominant observed violation: {dominant_violation_type}")
            if dominant_severity_pct is not None and pd.notna(dominant_severity_pct):
                notes.append(f"Peak initial severity: {float(dominant_severity_pct):.2f}% of limit")
            if labels:
                counts = {}
                for info in labels.values():
                    status = str(info.get("status", "Not evaluated"))
                    counts[status] = counts.get(status, 0) + 1
                notes.append(
                    "Network response: "
                    f"{counts.get('Improved', 0)} improved | "
                    f"{counts.get('Degraded', 0)} degraded | "
                    f"{counts.get('Resolved', 0)} resolved | "
                    f"{counts.get('New violation', 0)} new | "
                    f"{counts.get('Unchanged', 0)} unchanged | "
                    f"{counts.get('Not evaluated', 0)} not evaluated"
                )
                notes.append("Bus status = voltage margin; line/trafo % = relative loading change")
            if notes:
                ax.text(
                    0.01, 0.99, "\n".join(notes), transform=ax.transAxes,
                    ha="left", va="top", fontsize=8.0, zorder=40,
                    bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                              edgecolor="#999999", alpha=0.96),
                )

        ax.set_title(title or f"{GRID_CODE} -- mall at bus {mall_bus}", fontsize=12, pad=9,)

        # Standalone calls retain the old save/show behaviour. Calls from the
        # paired renderer only draw onto their supplied axes.
        if owns_figure:
            plt.tight_layout()
            fig.subplots_adjust(bottom=0.20, top=0.92)
            output_path = Path(savepath)
            fig.savefig(output_path, dpi=300, bbox_inches="tight")
            if output_path.suffix.lower() == ".png":
                fig.savefig(output_path.with_suffix(".pdf"), bbox_inches="tight")
            plt.show()
            plt.close(fig)
            print(f"[plot] Saved: {output_path} (300 dpi)")
            if output_path.suffix.lower() == ".png":
                print(f"[plot] Saved vector PDF: {output_path.with_suffix('.pdf')}")
        return ax

    @staticmethod
    def plot_before_after_sld(
            net, mall_bus, timestamp, before_violations, after_violations,
            element_change_labels, scenario_label, savepath,
            dominant_violation_type=None, dominant_severity_pct=None,
            after_evaluated=True):
        """Draw matched BEFORE/AFTER SLD panels for one operating timestamp.
        Uses plot_single_line_diagram() for both panels, so the electrical
        symbol renderer and layout remain shared rather than duplicated.
        """
        before_violations = before_violations or {}
        after_violations = after_violations or {}
        labels = element_change_labels or {}

        # Ensure identical, complete bus coordinates for both panels.
        FeederTopology.compute_hierarchical_layout(net)
        single_w, single_h = SldPlotter._compute_sld_figsize(net)
        fig, axes = plt.subplots(
            1, 2, figsize=(2.0 * single_w, single_h + 2.5),
            sharex=False, sharey=False,
        )

        SldPlotter.plot_single_line_diagram(
            net, mall_bus=mall_bus, title="BEFORE prosumer response",
            violations=before_violations,
            dominant_violation_type=dominant_violation_type,
            dominant_severity_pct=dominant_severity_pct,
            ax=axes[0], draw_legend=False, draw_summary=False,
            draw_outcomes=False,
        )
        after_title = (
            "AFTER prosumer response"
            if after_evaluated
            else "AFTER prosumer response — power flow not evaluated"
        )
        SldPlotter.plot_single_line_diagram(
            net, mall_bus=mall_bus, title=after_title,
            violations=after_violations,
            dominant_violation_type=dominant_violation_type,
            ax=axes[1], draw_legend=False, draw_summary=False,
            draw_outcomes=True,
            element_change_labels=labels,
        )
        # Figure-level title
        fig.suptitle(   f"{GRID_CODE} — {scenario_label}: "
            f"prosumer effect at {pd.Timestamp(timestamp)}",
            y=0.975,
            fontsize=14,
        )
        counts = {}         # Count the network response outcomes
        for info in labels.values():
            status = str(info.get("status", "Not evaluated"))
            counts[status] = counts.get(status, 0) + 1
        context = []            # Row 1: initial violation information
        if dominant_violation_type:
            context.append(
                f"Dominant initial violation: {dominant_violation_type}"
            )
        if dominant_severity_pct is not None and pd.notna(dominant_severity_pct):
            context.append(
                f"Peak initial severity: {float(dominant_severity_pct):.2f}% of limit"
            )
        if context:
            fig.text(
                0.5, 0.915,
                "   •   ".join(context),
                ha="center",
                va="center",
                fontsize=9,
            )
        # Rows 2–3: outcomes, split for readability
        outcome_summary = (
            f"Outcomes: {counts.get('Improved', 0)} improved  |  "
            f"{counts.get('Degraded', 0)} degraded  |  "
            f"{counts.get('Resolved', 0)} resolved\n"
            f"{counts.get('New violation', 0)} new  |  "
            f"{counts.get('Unchanged', 0)} unchanged  |  "
            f"{counts.get('Not evaluated', 0)} not evaluated"
        )

        fig.text(
            0.5, 0.835,
            outcome_summary,
            ha="center",
            va="center",
            fontsize=8.5,
            linespacing=1.25,
            bbox=dict(
                boxstyle="round,pad=0.35",
                facecolor="white",
                edgecolor="#c8c8c8",
                linewidth=0.7,
                alpha=0.98,
            ),
        )
        # One common legend for the two panels.
        extra_handles = [
            Line2D([0], [0], color=SLD_DOMINANT_VIOLATION_COLOR, linewidth=3.0,
                   label=(f"Dominant violation: {dominant_violation_type}" if dominant_violation_type else "Violation")),
            Line2D([0], [0], color=SLD_OTHER_VIOLATION_COLOR, linewidth=2.2,
                   label="Other violation type"),
            Line2D([0], [0], marker="s", color="white", linestyle="none",
                   markerfacecolor=SLD_OUTCOME_IMPROVED_COLOR, markeredgecolor=SLD_OUTCOME_IMPROVED_COLOR,
                   markersize=5, label="↑ IMP = improved"),
            Line2D([0], [0], marker="s", color="white", linestyle="none",
                   markerfacecolor=SLD_OUTCOME_DEGRADED_COLOR, markeredgecolor=SLD_OUTCOME_DEGRADED_COLOR,
                   markersize=5, label="↓ DEG = degraded"),
            Line2D([0], [0], marker="s", color="white", linestyle="none",
                   markerfacecolor=SLD_OUTCOME_RESOLVED_COLOR, markeredgecolor=SLD_OUTCOME_RESOLVED_COLOR,
                   markersize=5, label="✓ RES = resolved"),
            Line2D([0], [0], marker="s", color="white", linestyle="none",
                   markerfacecolor=SLD_OUTCOME_NEW_COLOR, markeredgecolor=SLD_OUTCOME_NEW_COLOR,
                   markersize=5, label="! NEW = new violation"),
            Line2D([0], [0], marker="s", color="white", linestyle="none",
                   markerfacecolor=SLD_OUTCOME_UNCHANGED_COLOR, markeredgecolor=SLD_OUTCOME_UNCHANGED_COLOR,
                   markersize=5, label="= SAME = unchanged"),
            Line2D([0], [0], marker="s", color="white", linestyle="none",
                   markerfacecolor=SLD_OUTCOME_NE_COLOR, markeredgecolor=SLD_OUTCOME_NE_COLOR,
                   markersize=5, label="N/E = not evaluated"),
        ]
        SldPlotter._build_sld_legend(
            axes[0], extra_handles=extra_handles, net=net, fig=fig,
            fontsize=8, ncol=7,
        )

        # Make space for the shared heading and legend.
        fig.subplots_adjust(left=0.035, right=0.985, top=0.72, bottom=0.17, wspace=0.06)
        output_path = Path(savepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=300, bbox_inches="tight")
        if output_path.suffix.lower() == ".png":
            fig.savefig(output_path.with_suffix(".pdf"), bbox_inches="tight")
        plt.show()
        plt.close(fig)
        print(f"[plot] Saved paired before/after SLD: {output_path} (300 dpi)")
        if output_path.suffix.lower() == ".png":
            print(f"[plot] Saved vector PDF: {output_path.with_suffix('.pdf')}")
        return output_path

    @staticmethod
    def _compute_sld_figsize(net, min_w=18, min_h=11):
        max_x, max_y, min_y = 0.0, 0.0, 0.0
        geo_seen = False
        for bus_idx in net.bus.index:
            geo_str = net.bus.at[bus_idx, "geo"]
            if pd.isna(geo_str):
                continue
            coords = json.loads(geo_str)["coordinates"]
            max_x = max(max_x, coords[0])
            max_y = max(max_y, coords[1])
            min_y = min(min_y, coords[1]) if geo_seen else coords[1]
            geo_seen = True
        fig_w = max(min_w, max_x * 1.1 + 4)
        fig_h = max(min_h, (max_y - min_y) * 0.9 + 4)
        return fig_w, fig_h

    @staticmethod
    def _build_sld_legend(ax, extra_handles=None, loc="lower left", fontsize=8,
                           title="Legend", title_fontsize=9, outside=True, ncol=4,
                           net=None, fig=None):
        """Builds the legend. Entries for the optional element types
    (storage, gen, shunt, ward, ...) are only added when `net` actually
    contains rows in that table, so the legend describes THIS diagram
    instead of listing every symbol the renderer could ever draw.
    Passing net=None keeps the old behaviour (base entries only)."""

        def _marker(marker, color, label, filled=True, size=7, edgewidth=1.4):
            return Line2D([0], [0], marker=marker, color="w", linestyle="none",
                          markerfacecolor=(color if filled else "white"),
                          markeredgecolor=color, markeredgewidth=edgewidth,
                          markersize=size, label=label)

        base_handles = [
            Line2D([0], [0], color=SLD_BUSBAR_COLOR, linewidth=3, label="Busbar"),
            Line2D([0], [0], color=SLD_MALL_COLOR, linewidth=5, label="Mall busbar (point of interest)"),
            Line2D([0], [0], color=SLD_LINE_COLOR, linewidth=1.3, label="Line"),
            _marker("v", SLD_LOAD_COLOR, "Load (consumption)"),
            _marker("o", SLD_SGEN_COLOR, "Static generator (PV etc.)", filled=False, size=8),
            _marker("D", SLD_TRAFO_COLOR, "Transformer (2-winding)"),
            mpatches.Rectangle((0, 0), 1, 1, facecolor="none", edgecolor=SLD_EXTGRID_COLOR, hatch="xxxx",
                               label="Ext. grid connection"),
            _marker("s", SLD_SWITCH_CLOSED_COLOR, "Closed switch (line/trafo)", edgewidth=1.1),
            _marker("s", SLD_SWITCH_OPEN_EDGE, "Open switch (line/trafo)", filled=False, edgewidth=1.1),
            Line2D([0], [0], color=SLD_SWITCH_COLOR, linewidth=1.3,
                   label="Bus-bus switch (closed)"),
            Line2D([0], [0], color=SLD_OOS_COLOR, linewidth=1.3, linestyle=(0, (4, 3)),
                   label="Out-of-service / open bus-bus switch"),
            Line2D([0], [0], marker="", color="w", linestyle="none",
                   label="Numbers = bus/node index"),
        ]

        # (table, handle) pairs appended only if the table has rows
        OPTIONAL_ENTRIES = [
            ("storage", lambda: _marker("P", SLD_STORAGE_COLOR, "Storage (battery etc.)", size=8)),
            ("gen", lambda: _marker("s", SLD_GEN_COLOR, "Controllable generator")),
            ("shunt", lambda: _marker("v", SLD_SHUNT_COLOR, "Shunt")),
            ("ward", lambda: _marker("x", SLD_WARD_COLOR, "Ward equivalent", edgewidth=1.6)),
            ("xward", lambda: _marker("X", SLD_XWARD_COLOR, "Extended Ward equivalent")),
            ("svc", lambda: _marker("*", SLD_SVC_COLOR, "SVC", size=9)),
            ("ssc", lambda: _marker("*", SLD_SSC_COLOR, "SSC", size=9)),
            ("impedance", lambda: Line2D([0], [0], color=SLD_IMPEDANCE_COLOR, linewidth=1.3,
                                         label="Impedance (Ward branch)")),
            ("dcline", lambda: Line2D([0], [0], color=SLD_DCLINE_COLOR, linewidth=1.35,
                                      label="DC line")),
            ("tcsc", lambda: Line2D([0], [0], color=SLD_TCSC_COLOR, linewidth=1.3, label="TCSC")),
        ]
        if net is not None:
            for table_name, make_handle in OPTIONAL_ENTRIES:
                try:
                    present = table_name in net and len(net[table_name]) > 0
                except Exception:
                    present = False
                if present:
                    base_handles.append(make_handle())
        legend_kwargs = dict(handles=base_handles + (extra_handles or []),
                             fontsize=fontsize, framealpha=0.95, title=title,
                             title_fontsize=title_fontsize, handlelength=1.6,
                             labelspacing=0.4, columnspacing=1.4, borderpad=0.5)
        if fig is not None:
            # A paired SLD uses one shared legend across both panels.
            fig.legend(
                loc="lower center", bbox_to_anchor=(0.5, 0.015),
                ncol=ncol, borderaxespad=0.0, **legend_kwargs
            )
        elif outside:
            # Park the legend below the axes so it does not cover the feeder.
            ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.01),
                      ncol=ncol, borderaxespad=0.0, **legend_kwargs)
        else:
            ax.legend(loc=loc, ncol=1, **legend_kwargs)
    #toreview
    @staticmethod
    def build_sld_collections(net, mall_bus=None, violations=None, bus_color_fn=None,
                              bus_size=0.3, trafo_size=SLD_SYM_TRAFO, elem_size=None,
                              label_buses=True, dominant_violation_type=None):
        """Builds the SLD as a list of pandapower/matplotlib collections Pass the result to pp_plot.draw_collections().

        - violations   : dict from GridOps.check_grid_violations(); violated buses, lines and
                         trafos are drawn red.
        - bus_color_fn : optional bus -> colour (HyperCAP uses it for internal/boundary buses).
        - Out-of-service elements are grey (lines dashed); open bus-bus switches are grey dotted.
        pandapower takes ONE colour per collection, so each group below is its own collection."""
        elem_size = elem_size or bus_size * 0.8
        violations = violations or {}
        voltage_types = ("undervoltage", "overvoltage")
        all_violation_types = (*voltage_types, "line_overload", "trafo_overload")
        # If no dominant type is supplied, retain the legacy behaviour: every violation
        # is highlighted with the dominant colour. Scenario diagnostics pass a type so
        # all other violation classes remain visible in amber.
        if dominant_violation_type not in all_violation_types:
            dominant_violation_type = None
        dominant_types = set(all_violation_types) if dominant_violation_type is None else {dominant_violation_type}
        secondary_types = set() if dominant_violation_type is None else set(all_violation_types) - dominant_types
        v_bus_dom = {int(i) for k in voltage_types if k in dominant_types for i, _ in violations.get(k, [])}
        v_bus_other = {int(i) for k in voltage_types if k in secondary_types for i, _ in violations.get(k, [])}
        v_line_dom = {int(i) for i, _ in violations.get("line_overload", [])} if "line_overload" in dominant_types else set()
        v_line_other = {int(i) for i, _ in violations.get("line_overload", [])} if "line_overload" in secondary_types else set()
        v_trafo_dom = {int(i) for i, _ in violations.get("trafo_overload", [])} if "trafo_overload" in dominant_types else set()
        v_trafo_other = {int(i) for i, _ in violations.get("trafo_overload", [])} if "trafo_overload" in secondary_types else set()
        C = []
        geo_buses = [b for b in net.bus.index if _sld_has_geo(net, b)]

        # ---- lines: normal / violated / out of service
        ln = _sld_table(net, "line")
        if ln is not None:
            ok = _sld_branches_with_geo(net, ln)
            ins = _sld_in_service(ln).loc[ok]
            viol_dom = pd.Series(ok.isin(list(v_line_dom)), index=ok)
            viol_other = pd.Series(ok.isin(list(v_line_other)), index=ok)
            for idx, style in (
                    (ok[ins & ~viol_dom & ~viol_other], dict(color=SLD_LINE_COLOR, linewidths=1.35, linestyle="solid")),
                    (ok[ins & viol_other], dict(color=SLD_OTHER_VIOLATION_COLOR, linewidths=2.3, linestyle="solid")),
                    (ok[ins & viol_dom], dict(color=SLD_DOMINANT_VIOLATION_COLOR, linewidths=3.5, linestyle="solid")),
                    (ok[~ins], dict(color=SLD_OOS_COLOR, linewidths=1.1, linestyle="dashed"))):
                if len(idx):
                    C.append(pp_plot.create_line_collection(
                        net, lines=idx, use_bus_geodata=True, zorder=2, **style))

        # ---- dc lines and impedances (Ward eq_impedance)
        dc = _sld_table(net, "dcline")
        if dc is not None:
            idx = _sld_branches_with_geo(net, dc)
            if len(idx):
                C += _sld_as_list(pp_plot.create_dcline_collection(
                    net, dclines=idx, color=SLD_DCLINE_COLOR, linewidths=1.35, zorder=2))
        imp = _sld_table(net, "impedance")
        if imp is not None:
            idx = _sld_branches_with_geo(net, imp)
            if len(idx):
                C += _sld_as_list(pp_plot.create_impedance_collection(
                    net, impedances=idx, color=SLD_IMPEDANCE_COLOR, linewidths=1.1, zorder=2))

        # ---- busbars (one collection per colour)
        def _default_bus_color(b):
            if b == mall_bus:
                return SLD_MALL_COLOR
            if b in v_bus_dom:
                return SLD_DOMINANT_VIOLATION_COLOR
            if b in v_bus_other:
                return SLD_OTHER_VIOLATION_COLOR
            return SLD_BUSBAR_COLOR
        color_fn = bus_color_fn or _default_bus_color
        by_color = {}
        for b in geo_buses:
            by_color.setdefault(color_fn(int(b)), []).append(b)
        for col, buses in by_color.items():
            C.append(pp_plot.create_bus_collection(
                net, buses=buses, size=bus_size * 0.6, patch_type="rect", color=col, zorder=5))

        # ---- switches
        sw = _sld_table(net, "switch")
        if sw is not None:
            bb = sw[sw["et"] == "b"]
            for sel, col, ls in ((bb.index[bb["closed"].astype(bool)], SLD_SWITCH_COLOR, "-"),
                                 (bb.index[~bb["closed"].astype(bool)], SLD_OOS_COLOR, ":")):
                if len(sel):
                    C += _sld_as_list(pp_plot.create_bus_bus_switch_collection(
                        net, switches=sel, size=bus_size * 0.8, helper_line_style=ls,
                        helper_line_color=col, zorder=2))
            lsw = sw.index[sw["et"] == "l"]   # filled square = closed, hollow = open (pandapower symbol)
            if len(lsw):
                C += _sld_as_list(pp_plot.create_line_switch_collection(
                    net, switches=lsw, size=bus_size * 0.9, distance_to_bus=bus_size * 2.2,
                    use_line_geodata=False, zorder=7))

        # ---- single-bus elements (in service / out of service)
        def _bus_elements(table, fn, kw, color):
            t = _sld_table(net, table)
            if t is None:
                return
            idx = t.index[[_sld_has_geo(net, b) for b in t["bus"]]]
            oos = idx[~_sld_in_service(t).loc[idx]]
            for sel, col in ((idx.difference(oos), color), (oos, SLD_OOS_COLOR)):
                if len(sel):
                    C.extend(_sld_as_list(fn(net, **{kw: sel}, size=elem_size, color=col, zorder=4)))
        _bus_elements("load",    pp_plot.create_load_collection,    "loads",    SLD_LOAD_COLOR)
        _bus_elements("sgen",    pp_plot.create_sgen_collection,    "sgens",    SLD_SGEN_COLOR)
        _bus_elements("gen",     pp_plot.create_gen_collection,     "gens",     SLD_GEN_COLOR)
        _bus_elements("storage", pp_plot.create_storage_collection, "storages", SLD_STORAGE_COLOR)
        _bus_elements("ward",    pp_plot.create_ward_collection,    "wards",    SLD_WARD_COLOR)
        _bus_elements("xward",   pp_plot.create_xward_collection,   "xwards",   SLD_XWARD_COLOR)

        # ---- 2-winding trafos: normal / violated / out of service
        tr = _sld_table(net, "trafo")
        if tr is not None:
            ins = _sld_in_service(tr)
            viol_dom = pd.Series(tr.index.isin(list(v_trafo_dom)), index=tr.index)
            viol_other = pd.Series(tr.index.isin(list(v_trafo_other)), index=tr.index)
            for sel, col in ((tr.index[ins & ~viol_dom & ~viol_other], SLD_TRAFO_COLOR),
                             (tr.index[ins & viol_other], SLD_OTHER_VIOLATION_COLOR),
                             (tr.index[ins & viol_dom], SLD_DOMINANT_VIOLATION_COLOR),
                             (tr.index[~ins], SLD_OOS_COLOR)):
                if len(sel):
                    C += _sld_as_list(pp_plot.create_trafo_collection(
                        net, trafos=sel, size=trafo_size, color=col, zorder=6))

        # ---- 3-winding trafos
        t3 = _sld_table(net, "trafo3w")
        if t3 is not None:
            ins = _sld_in_service(t3)
            for sel, col in ((t3.index[ins], SLD_TRAFO_COLOR), (t3.index[~ins], SLD_OOS_COLOR)):
                if len(sel):
                    C += _sld_as_list(pp_plot.create_trafo3w_collection(
                        net, trafo3ws=sel, color=col, zorder=6))

        # ---- ext grid
        eg = _sld_table(net, "ext_grid")
        if eg is not None:
            ins = _sld_in_service(eg)
            for sel, col in ((eg.index[ins], SLD_EXTGRID_COLOR), (eg.index[~ins], SLD_OOS_COLOR)):
                if len(sel):
                    C += _sld_as_list(pp_plot.create_ext_grid_collection(
                        net, ext_grids=sel, size=SLD_SYM_EXTGRID, color=col, zorder=6))

        # ---- bus index labels
        if label_buses and geo_buses:
            xy = [SldPlotter._bus_xy(net, b) for b in geo_buses]
            C.append(pp_plot.create_annotation_collection(
                texts=[str(b) for b in geo_buses],
                coords=[(x - bus_size, y - bus_size * 1.6) for x, y in xy],
                size=bus_size * 1.1, color="#333333", zorder=20))
        return C
  
    @staticmethod
    def plot_soc_and_tracking(opf_results_df, res_actual, scenario_label, violation_details_df=None):
        fig = ScenarioHtmlReport._build_soc_tracking_chart_fig(opf_results_df, res_actual, scenario_label,
                                             violation_details_df=violation_details_df)
        SldPlotter.save_and_show_fig(fig, f"prosumer_soc_tracking_{scenario_label}.png")
        
    @staticmethod
    def plot_voltage_diagnostics(opf_results_df, scenario_label):
        fig = ScenarioHtmlReport._build_voltage_chart_fig(
            opf_results_df, scenario_label
        )
        SldPlotter.save_and_show_fig(
            fig, f"voltage_diagnostics_{scenario_label}.png"
        )

    @staticmethod
    def plot_scenario_diagnostics(opf_results_df,res_actual,scenario_label,violation_details_df=None):
        SldPlotter.plot_prosumer_participation(opf_results_df,scenario_label,violation_details_df=violation_details_df)
        SldPlotter.plot_soc_and_tracking(opf_results_df,res_actual,scenario_label,violation_details_df=violation_details_df)
        SldPlotter.plot_voltage_diagnostics(opf_results_df,scenario_label

        )

class ScenarioHtmlReport:
    @staticmethod
    def _fig_to_base64(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode("utf-8")
        plt.close(fig)
        return encoded

    @staticmethod
    def _build_participation_chart_fig(opf_results_df, scenario_label,violation_details_df=None):
        """Plot mall power dispatch and feeder loading before/after flexibility."""
        fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

        # Panel 1: baseline, requested setpoint, and actual delivered grid power.
        ax = axes[0]
        ax.plot(
            opf_results_df.index,
            opf_results_df["p_base_mw"],
            label="Baseline mall grid power",
            linestyle="--",
            color="tab:gray"
        )
        ax.plot(
            opf_results_df.index,
            opf_results_df["p_opf_mw"],
            label="OPF / fallback setpoint",
            color="tab:blue"
        )
        # Actual closed-loop power is stored in kW, so convert to MW.
        if "p_updated_grid_kw" in opf_results_df.columns:
            ax.plot(
                opf_results_df.index,
                opf_results_df["p_updated_grid_kw"] / 1000.0,
                label="Actual delivered grid power",
                linestyle="-.",
                color="tab:green"
            )

        ax.axhline(0, color="black", linewidth=0.8)

        SldPlotter.style_axis(
            ax,
            "Mall grid power [MW]\n(+ import / - export)",
            f"[{scenario_label}] Baseline, setpoint and actual power"
        )

        # Panel 2: existing mall feeder loading comparison.
        ax = axes[1]
        ax.plot(
            opf_results_df.index,
            opf_results_df["mall_feeder_line_loading_before_pct"],
            label="Feeder loading before flexibility",
            linestyle="--",
            color="tab:gray"
        )
        ax.plot(
            opf_results_df.index,
            opf_results_df["mall_feeder_line_loading_after_pct"],
            label="Feeder loading after flexibility",
            color="tab:green"
        )
        ax.axhline(
            100.0, color="tab:red", linestyle=":",
            label="100% loading limit"
        )
        ax.set_xlabel("Time")
        SldPlotter.style_axis(
            ax,
            "Mall feeder line loading [%]",
            f"[{scenario_label}] Feeder loading before vs. after"
        )
        plt.tight_layout()
        return fig

    @staticmethod
    def _build_voltage_chart_fig(opf_results_df, scenario_label):
        """Compare network-wide minimum and maximum voltage before/after."""
        fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
        voltage_series = [
            (
                axes[0],
                "v_min_before_pu",
                "v_min_after_pu",
                "Minimum bus voltage [p.u.]",
                "Network minimum voltage"
            ),
            (
                axes[1],
                "v_max_before_pu",
                "v_max_after_pu",
                "Maximum bus voltage [p.u.]",
                "Network maximum voltage"
            ),
        ]

        for ax, before_col, after_col, ylabel, title in voltage_series:
            if before_col in opf_results_df.columns:
                ax.plot(
                    opf_results_df.index,
                    opf_results_df[before_col],
                    linestyle="--",
                    label="Before flexibility",
                    color="tab:gray"
                )

            if after_col in opf_results_df.columns:
                ax.plot(
                    opf_results_df.index,
                    opf_results_df[after_col],
                    label="After flexibility",
                    color="tab:blue"
                )

            # Nominal voltage reference.
            ax.axhline(
                1.0, color="black", linestyle=":",
                linewidth=1, label="Nominal voltage (1.0 p.u.)"
            )

            SldPlotter.style_axis(
                ax, ylabel, f"[{scenario_label}] {title}"
            )

        axes[1].set_xlabel("Time")
        plt.tight_layout()
        return fig
        
    @staticmethod
    def _build_flexibility_bounds_chart_fig(bounds_df, opf_results_df,
                                            scenario_label):
        """Compare available mall power bounds with the chosen setpoint."""
        if bounds_df is None or bounds_df.empty:
            return None
        required = {"p_mall_min_mw", "p_mall_base_mw", "p_mall_max_mw"}
        if not required.issubset(bounds_df.columns):
            return None
        fig, ax = plt.subplots(figsize=(13, 5))
        # Align the bounds with the OPF result timestamps.
        bounds = bounds_df.reindex(opf_results_df.index)
        ax.fill_between(
            bounds.index,
            bounds["p_mall_min_mw"].to_numpy(dtype=float),
            bounds["p_mall_max_mw"].to_numpy(dtype=float),
            alpha=0.20,
            color="tab:blue",
            label="Available flexibility range"
        )
        ax.plot(
            bounds.index,
            bounds["p_mall_base_mw"],
            linestyle="--",
            color="tab:gray",
            label="Baseline mall power"
        )
        ax.plot(
            opf_results_df.index,
            opf_results_df["p_opf_mw"],
            color="tab:orange",
            label="OPF / fallback setpoint"
        )
        ax.set_xlabel("Time")
        SldPlotter.style_axis(
            ax,
            "Mall grid power [MW]",
            f"[{scenario_label}] Flexibility bounds vs. setpoint"
        )
        plt.tight_layout()
        return fig

    @staticmethod
    def _build_soc_tracking_chart_fig(opf_results_df, res_actual,
                                    scenario_label, violation_details_df=None):
        """Plot storage SOC, setpoint vs actual power, and tracking error."""
        fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
        # Panel 1: thermal storage state of charge.
        ax = axes[0]
        ax.plot(
            res_actual.index,
            res_actual["soc_percent"],
            label="Thermal storage SOC",
            color="tab:purple"
        )
        SldPlotter.style_axis(
            ax, "SOC [%]", f"[{scenario_label}] Thermal storage SOC"
        )
        # Panel 2: requested grid power vs actual delivered grid power.
        ax = axes[1]
        ax.plot(
            opf_results_df.index,
            opf_results_df["p_grid_setpoint_kw"],
            label="OPF / fallback grid setpoint",
            color="tab:blue"
        )
        ax.plot(
            opf_results_df.index,
            opf_results_df["p_updated_grid_kw"],
            linestyle="--",
            label="Actual prosumer grid power",
            color="tab:green"
        )
        ax.axhline(0, color="black", linewidth=0.8)

        SldPlotter.style_axis(
            ax, "Power [kW]", f"[{scenario_label}] Setpoint vs. actual power"
        )
        # Panel 3: tracking error, defined as actual minus setpoint.
        ax = axes[2]
        if "tracking_error_kw" in opf_results_df.columns:
            tracking_error = opf_results_df["tracking_error_kw"]
        else:
            tracking_error = (
                opf_results_df["p_updated_grid_kw"]
                - opf_results_df["p_grid_setpoint_kw"]
            )
        ax.plot(
            opf_results_df.index,
            tracking_error,
            label="Actual minus setpoint",
            color="tab:orange"
        )
        ax.axhline(0, color="black", linewidth=0.8, linestyle=":")
        ax.set_xlabel("Time")

        SldPlotter.style_axis(
            ax, "Tracking error [kW]", f"[{scenario_label}] Tracking error"
        )
        plt.tight_layout()
        return fig
    
    #PM_8: check that after the OPF result is applied by pandaprosumer, the violation table should not report "resolved" for pf failure and also for flex bounds infeasible scenario
    @staticmethod
    def build_violation_event_table(violation_details_df, opf_results_df=None):
      
        cols = [
            "time",
            "violation_type",
            "location",
            "value_before",
            "value_after",
            "severity_before_pct_of_limit",
            "severity_after_pct_of_limit",
            "normalized_improvement_pct",
            "status",
        ]
        if violation_details_df is None or violation_details_df.empty:
            return pd.DataFrame(columns=cols)
        detail = violation_details_df.copy()
        _excess = pd.to_numeric(detail.get("excess", pd.Series(np.nan, index=detail.index)), errors="coerce").abs()
        _limit = pd.to_numeric(detail.get("limit", pd.Series(np.nan, index=detail.index)), errors="coerce").abs()
        _severity_fallback = (100.0 * _excess / _limit.where(_limit > 1e-12)).replace([np.inf, -np.inf], np.nan)
        if "normalized_severity_pct" not in detail.columns:
            detail["normalized_severity_pct"] = _severity_fallback
        else:
            detail["normalized_severity_pct"] = pd.to_numeric(
                detail["normalized_severity_pct"], errors="coerce").fillna(_severity_fallback)
        event_keys = ["time", "violation_type", "location"]
        before_rows = detail[detail["phase"] == "before"].set_index(event_keys)
        after_rows = detail[detail["phase"] == "after"].set_index(event_keys)
        before = before_rows["value"]
        after = after_rows["value"]
        before_severity = before_rows["normalized_severity_pct"]
        after_severity = after_rows["normalized_severity_pct"]
        # Combine before/after values and normalized severities for each element event.
        combined = pd.DataFrame({
            "value_before": before,
            "severity_before_pct_of_limit": before_severity,
        }).join(pd.DataFrame({
            "value_after": after,
            "severity_after_pct_of_limit": after_severity,
        }), how="outer")
        combined = combined.reset_index()
        # Determine what happened during the after-evaluation.

        def _after_evaluation_status(time_value):
            if opf_results_df is None or opf_results_df.empty:
                return STATUS_NOT_EVALUATED
            try:
                result_row = opf_results_df.loc[time_value]
            except KeyError:
                return STATUS_NOT_EVALUATED
            if isinstance(result_row, pd.DataFrame):
                result_row = result_row.iloc[-1]
            result_status = result_row.get("status", STATUS_NOT_EVALUATED)
            if pd.isna(result_status):
                return STATUS_NOT_EVALUATED
            result_status = str(result_status)
            if result_status in {STATUS_RESOLVED, STATUS_STILL_VIOLATING,
                                 STATUS_PF_FAILED, STATUS_FLEX_INFEASIBLE,
                                 STATUS_NOT_EVALUATED}:
                return result_status
            return STATUS_NOT_EVALUATED

        def _status(row):
            # Timestep outcome decides PF failure / infeasibility / not evaluated, so those are
            # never mislabeled resolved. In an evaluated hour that is "Still violating", only
            # events that actually still have an after-value are unresolved; an event with no
            # after-row was cleared by the mall and is "Resolved".
            hour_status = _after_evaluation_status(row["time"])
            if hour_status == STATUS_STILL_VIOLATING and pd.isna(row["value_after"]):
                return STATUS_RESOLVED
            return hour_status

        combined["status"] = combined.apply(_status, axis=1)
        # A genuinely absent before/after event means zero severity only when the
        # corresponding measurement was valid / the post-dispatch PF was evaluated.
        # Do not turn an existing event with an invalid limit into a false zero.
        missing_before_event = combined["value_before"].isna()
        combined.loc[missing_before_event, "severity_before_pct_of_limit"] = 0.0
        post_evaluated = ~combined["status"].isin([STATUS_PF_FAILED, STATUS_NOT_EVALUATED])
        missing_after_event = combined["value_after"].isna() & post_evaluated
        combined.loc[missing_after_event, "severity_after_pct_of_limit"] = 0.0

        _before_severity = pd.to_numeric(combined["severity_before_pct_of_limit"], errors="coerce")
        _after_severity = pd.to_numeric(combined["severity_after_pct_of_limit"], errors="coerce")
        _can_calculate_improvement = (_before_severity > 0) & _before_severity.notna() & _after_severity.notna()
        _can_calculate_improvement &= ~combined["status"].isin([STATUS_PF_FAILED, STATUS_NOT_EVALUATED])
        combined["normalized_improvement_pct"] = np.nan
        combined.loc[_can_calculate_improvement, "normalized_improvement_pct"] = (
            (_before_severity[_can_calculate_improvement] - _after_severity[_can_calculate_improvement])
            / _before_severity[_can_calculate_improvement] * 100.0
        )

        combined = combined.sort_values(
            ["time", "violation_type", "location"]
        ).reset_index(drop=True)

        return combined[cols]

    @staticmethod
    def write_scenario_excel_report(scenario_label, opf_results_df, bounds_df, violation_details_df,
                                     res_actual):
        """Create a human-readable Excel workbook for one simulation scenario.
        Tables are written with pd.ExcelWriter(engine="openpyxl") + DataFrame.to_excel; openpyxl is
        only used afterwards for the styling pandas cannot do (header colours, Excel Table, widths,
        number formats, status colouring via conditional formatting)."""

        filename = f"grid_scenario_results_{scenario_label}.xlsx"

        #  styles 
        header_fill = PatternFill("solid", fgColor="1F4E78")
        header_font = Font(color="FFFFFF", bold=True)
        subheader_fill = PatternFill("solid", fgColor="D9EAF7")
        title_font = Font(size=16, bold=True)
        bold_font = Font(bold=True)
        thin_gray = Side(style="thin", color="D9D9D9")
        border = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)

        def _cf_fill(hex_color):
            # conditional-formatting fills need start_color/end_color (a plain fgColor is ignored)
            return PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")

        green_fill, yellow_fill, red_fill = _cf_fill("E2F0D9"), _cf_fill("FFF2CC"), _cf_fill("F4CCCC")
        orange_fill, gray_fill = _cf_fill("FCE4D6"), _cf_fill("E7E6E6")

        #  helper functions 
        def prepare_dataframe(df):
            """Return a clean copy with index converted to a time column."""
            if df is None:
                return pd.DataFrame()
            out = df.copy()
            if isinstance(out.index, pd.DatetimeIndex) and out.index.tz is not None:
                out.index = out.index.tz_localize(None)
            for col in out.columns:
                if isinstance(out[col].dtype, pd.DatetimeTZDtype):
                    out[col] = out[col].dt.tz_localize(None)
            if isinstance(out.index, pd.DatetimeIndex):
                out = out.reset_index()
                if "index" in out.columns:
                    out = out.rename(columns={"index": "time"})
            elif "Unnamed: 0" in out.columns and "time" not in out.columns:
                out = out.rename(columns={"Unnamed: 0": "time"})
            return out

        def number_format_for(header):
            header = str(header).lower()
            if "percent" in header or header.endswith("_pct") or "_kw" in header:
                return "0.0"
            return "0.000"          # pu, _mw, _mvar and everything else

        def write_sheet(writer, sheet_name, df, table_name):
            """df.to_excel + readable formatting. Returns (worksheet, written dataframe)."""
            df = prepare_dataframe(df)

            if df.empty:
                ws = writer.book.create_sheet(sheet_name)
                ws["A1"] = "No data available"
                ws["A1"].font = bold_font
                return ws, df

            df.to_excel(writer, sheet_name=sheet_name, index=False)
            ws = writer.sheets[sheet_name]

            # header row
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                cell.border = border
            ws.row_dimensions[1].height = 32
            ws.freeze_panes = "A2"
            # No sheet-level auto_filter: the Excel Table added below carries its own filter,
            # and an overlapping worksheet autofilter makes Excel report the file as corrupt.

            # number formats per column: floats by header name, datetimes as yyyy-mm-dd hh:mm
            # (ExcelWriter(datetime_format=...) is ignored by pandas' openpyxl writer)
            for col_idx, column in enumerate(df.columns, start=1):
                if pd.api.types.is_float_dtype(df[column]):
                    fmt = number_format_for(column)
                elif pd.api.types.is_datetime64_any_dtype(df[column]):
                    fmt = "yyyy-mm-dd hh:mm"
                else:
                    continue
                for (cell,) in ws.iter_rows(min_row=2, max_row=len(df) + 1,
                                            min_col=col_idx, max_col=col_idx):
                    cell.number_format = fmt

            # Excel table
            ref = f"A1:{get_column_letter(len(df.columns))}{len(df) + 1}"
            tab = Table(displayName=table_name, ref=ref)
            tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showFirstColumn=False,
                                                showLastColumn=False, showRowStripes=True,
                                                showColumnStripes=False)
            ws.add_table(tab)

            # column widths
            for col_idx, column in enumerate(df.columns, start=1):
                max_length = max([len(str(column))] +
                                 [len(str(v)) for v in df.iloc[:100, col_idx - 1].dropna()])
                ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_length + 2, 12), 32)

            return ws, df

        def add_fill_rules(ws, df, column, rules):
            """Colour cells of `column` that equal a value."""
            if df is None or df.empty:
                return
            first_row = 2
            last_row = len(df) + 1
            # Prevent invalid ranges such as J2:J1.
            if last_row < first_row or ws.max_row < first_row:
               return
            letter = get_column_letter(df.columns.get_loc(column) + 1)
            last_row = min(last_row, ws.max_row)
            cell_range =  f"{letter}{first_row}:{letter}{last_row}"
            for formula, fill in rules:
                ws.conditional_formatting.add(
                    cell_range, CellIsRule(operator="equal", formula=[formula], fill=fill))

        #  violation summary table 
        if violation_details_df is not None and not violation_details_df.empty:

            v = violation_details_df.copy()

            # Prefer actual excess over raw value because undervoltage
            # and overload have different directions.
            if "excess" in v.columns:
                summary = (v.groupby(["phase", "violation_type", "location"], dropna=False)
                            .agg(occurrences=("value", "size"), worst_excess=("excess", "max"))
                            .reset_index()
                            .sort_values(["phase", "occurrences", "worst_excess"],
                                         ascending=[True, False, False]))

            else:
                summary = (v.groupby(["phase", "violation_type", "location"], dropna=False)
                            .agg(occurrences=("value", "size"), worst_value=("value", "max"))
                            .reset_index()
                            .sort_values(["phase", "occurrences"], ascending=[True, False]))

        else:
            summary = pd.DataFrame(columns=["phase", "violation_type", "location", "occurrences"])

        # ---- counts for the summary sheet (same helper the terminal summary uses) ----
        counts = _status_summary_counts(opf_results_df)
        summary_rows = [
            ("Hours with no initial violation", counts["n_no_flex"]),
            ("Hours with initial violations", counts["n_violated"]),
            ("Initially violated hours resolved", counts["n_resolved"]),
            ("Hours still violating", counts["n_remaining"]),
            ("Flexibility-infeasible hours", counts["n_infeasible"]),
            ("Power-flow failure hours", counts["n_pf_failed"]),
            ("Not evaluated hours", counts["n_not_evaluated"]),
        ]

        max_tracking_error = (opf_results_df["tracking_error_kw"].abs().max()
                              if "tracking_error_kw" in opf_results_df else np.nan)
        soc_min = res_actual["soc_percent"].min() if "soc_percent" in res_actual else np.nan
        soc_max = res_actual["soc_percent"].max() if "soc_percent" in res_actual else np.nan
        support_mwh = (opf_results_df["grid_support_kw"].sum() / 1000.0
                       if "grid_support_kw" in opf_results_df else np.nan)
        indicators = [
            ("Maximum tracking error [kW]", max_tracking_error),
            ("Minimum thermal storage SOC [%]", soc_min),
            ("Maximum thermal storage SOC [%]", soc_max),
            ("Total grid support [MWh]", support_mwh),
        ]

        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            ws = writer.book.create_sheet("Summary")
            ws["A1"] = "Grid Simulation Scenario Report"
            ws["A1"].font = title_font
            ws["A3"] = "Scenario"
            ws["B3"] = scenario_label
            ws["A4"] = "Total simulation hours"
            ws["B4"] = len(opf_results_df)
            row = 6
            for label, value in summary_rows:
                ws.cell(row=row, column=1, value=label)
                ws.cell(row=row, column=2, value=int(value))
                ws.cell(row=row, column=1).font = bold_font
                ws.cell(row=row, column=1).fill = subheader_fill
                row += 1
            row += 1
            ws.cell(row=row, column=1, value="Engineering indicators").font = Font(size=12, bold=True)
            row += 1
            for label, value in indicators:
                ws.cell(row=row, column=1, value=label)
                ws.cell(row=row, column=2, value=None if pd.isna(value) else float(value))
                ws.cell(row=row, column=1).font = bold_font
                ws.cell(row=row, column=1).fill = subheader_fill
                ws.cell(row=row, column=2).number_format = "0.000"
                row += 1
            ws.column_dimensions["A"].width = 42
            ws.column_dimensions["B"].width = 24

            # ---- data sheets: df.to_excel + styling ----
            ws, df = write_sheet(writer, "Hourly Results", opf_results_df, "HourlyResults")
            add_fill_rules(ws, df, "status", [
                (f'"{STATUS_RESOLVED}"', green_fill),
                (f'"{STATUS_STILL_VIOLATING}"', red_fill),
                (f'"{STATUS_FLEX_INFEASIBLE}"', orange_fill),
                (f'"{STATUS_PF_FAILED}"', gray_fill),
                (f'"{STATUS_NOT_EVALUATED}"', gray_fill)])

            ws, df = write_sheet(writer, "Violations", violation_details_df, "Violations")
            add_fill_rules(ws, df, "phase", [('"before"', yellow_fill), ('"after"', red_fill)])
            ws, df = write_sheet(writer, "Flexibility Bounds", bounds_df, "FlexibilityBounds")
            add_fill_rules(ws, df, "feasible", [("TRUE", green_fill), ("FALSE", red_fill)])
            write_sheet(writer, "Prosumer Results", res_actual, "ProsumerResults")
            write_sheet(writer, "Violation Summary", summary, "ViolationSummary")
            #  workbook-wide formatting
            for ws in writer.book.worksheets:
                ws.sheet_view.showGridLines = False
        print(f"Human-readable Excel report written: {filename}")
        return filename

    @staticmethod
    def build_scenario_html_report(scenario_label, opf_results_df, violation_details_df,
                                        res_actual, bounds_df=None,savepath=None):
            """Builds one self-contained HTML file summarizing the full closed-loop
        scenario: headline stats, two diagnostic charts, a full hour-by-hour
        table of the mall's reaction at every step (color-coded by outcome),
        and a violation event log showing each violation's before/after value
        and whether it was resolved. Same underlying numbers as the CSVs, but
        presented for reading rather than spreadsheet-parsing."""

            savepath = savepath or f"grid_scenario_report_{scenario_label}.html"

            counts = _status_summary_counts(opf_results_df)
            n_total = counts["n_total"]
            n_no_flex = counts["n_no_flex"]
            n_violated = counts["n_violated"]
            n_resolved = counts["n_resolved"]
            n_remaining = counts["n_remaining"]
            n_infeasible = counts["n_infeasible"]
            n_pf_failed = counts["n_pf_failed"]
            n_not_evaluated = counts["n_not_evaluated"]
            total_support_mwh = opf_results_df["grid_support_kw"].sum() / 1000.0
            soc_min = res_actual["soc_percent"].min() if len(res_actual) else float("nan")
            soc_max = res_actual["soc_percent"].max() if len(res_actual) else float("nan")

            participation_b64 = ScenarioHtmlReport._fig_to_base64(
                ScenarioHtmlReport._build_participation_chart_fig(opf_results_df, scenario_label, violation_details_df))
            soc_b64 = ScenarioHtmlReport._fig_to_base64(
                ScenarioHtmlReport._build_soc_tracking_chart_fig(opf_results_df, res_actual, scenario_label, violation_details_df))
            
            voltage_fig = ScenarioHtmlReport._build_voltage_chart_fig(
                opf_results_df, scenario_label
            )
            voltage_b64 = ScenarioHtmlReport._fig_to_base64(voltage_fig)



            bounds_fig = ScenarioHtmlReport._build_flexibility_bounds_chart_fig(
                bounds_df, opf_results_df, scenario_label
            )
            bounds_b64 = (
                ScenarioHtmlReport._fig_to_base64(bounds_fig)
                if bounds_fig is not None
                else None
            )
            bounds_html = (
                '<h3>Flexibility bounds vs. setpoint</h3>\n'
                f'<img src="data:image/png;base64,{bounds_b64}" alt="Flexibility bounds">'
                if bounds_b64 else "")
            event_table = ScenarioHtmlReport.build_violation_event_table(violation_details_df,opf_results_df)

            def _cards_html():
                cards = [
                    ("Hours simulated", f"{n_total}"),
                    ("No violation", f"{n_no_flex} ({n_no_flex / max(n_total, 1) * 100:.0f}%)"),
                    ("Violated hours", f"{n_violated} ({n_violated / max(n_total, 1) * 100:.0f}%)"),
                    ("Resolved by mall", f"{n_resolved}"),
                    ("Remained unresolved", f"{n_remaining}"),
                    ("Flex infeasible", f"{n_infeasible}"),
                    ("Power-flow failures", f"{n_pf_failed}"),
                    ("Not evaluated", f"{n_not_evaluated}"),
                    ("Total grid support", f"{total_support_mwh:.2f} MWh"),
                    ("Thermal SOC range", f"{soc_min:.1f}% - {soc_max:.1f}%"),
                ]
                return "".join(
                    f'<div class="card"><div class="card-label">{label}</div>'
                    f'<div class="card-value">{value}</div></div>' for label, value in cards)

            def _hourly_table_html():
                display_df = opf_results_df.reset_index().rename(columns={"index": "time"})
                display_cols = ["time", "status", "flex_activation_required", "p_base_mw", "p_opf_mw",
                                "grid_support_kw", "mall_bus_vm_pu_before", "mall_bus_vm_pu_after",
                                "mall_feeder_line_loading_before_pct", "mall_feeder_line_loading_after_pct"]
                display_df = display_df[display_cols]

                rows_html = []
                for _, row in display_df.iterrows():
                    color = _STATUS_ROW_COLOR.get(row["status"], "#ffffff")
                    label = _STATUS_LABEL.get(row["status"], row["status"])
                    rows_html.append(
                        f'<tr style="background-color:{color};">'
                        f'<td>{row["time"]}</td>'
                        f'<td title="{row["status"]}">{label}</td>'
                        f'<td>{"Yes" if row["flex_activation_required"] else "No"}</td>'
                        f'<td>{row["p_base_mw"]:.3f}</td>'
                        f'<td>{row["p_opf_mw"]:.3f}</td>'
                        f'<td>{row["grid_support_kw"]:.1f}</td>'
                        f'<td>{row["mall_bus_vm_pu_before"]:.3f}</td>'
                        f'<td>{row["mall_bus_vm_pu_after"]:.3f}</td>'
                        f'<td>{row["mall_feeder_line_loading_before_pct"]:.1f}</td>'
                        f'<td>{row["mall_feeder_line_loading_after_pct"]:.1f}</td>'
                        f'</tr>')
                header = ("<tr><th>Time</th><th>Outcome</th><th>Flex used?</th>"
                        "<th>Baseline (MW)</th><th>Actual (MW)</th><th>Grid support (kW)</th>"
                        "<th>Mall V before (pu)</th><th>Mall V after (pu)</th>"
                        "<th>Feeder load before (%)</th><th>Feeder load after (%)</th></tr>")
                return header + "".join(rows_html)

            def _event_table_html():
                if event_table.empty:
                    return "<p>No grid violations occurred during this scenario.</p>"
                rows_html = []
                for _, row in event_table.iterrows():
                    color = _STATUS_ROW_COLOR.get(str(row["status"]), "#ffffff")
                    vb = f"{row['value_before']:.3f}" if pd.notna(row["value_before"]) else "-"
                    va = f"{row['value_after']:.3f}" if pd.notna(row["value_after"]) else "-"
                    sb = (f"{row['severity_before_pct_of_limit']:.2f}%"
                          if pd.notna(row["severity_before_pct_of_limit"]) else "-")
                    sa = (f"{row['severity_after_pct_of_limit']:.2f}%"
                          if pd.notna(row["severity_after_pct_of_limit"]) else "-")
                    improvement = (f"{row['normalized_improvement_pct']:+.1f}%"
                                   if pd.notna(row["normalized_improvement_pct"]) else "-")
                    rows_html.append(
                        f'<tr style="background-color:{color};">'
                        f'<td>{row["time"]}</td><td>{row["violation_type"]}</td>'
                        f'<td>{row["location"]}</td><td>{vb}</td><td>{va}</td>'
                        f'<td>{sb}</td><td>{sa}</td><td>{improvement}</td>'
                        f'<td>{row["status"]}</td></tr>')
                header = ("<tr><th>Time</th><th>Violation type</th><th>Location</th>"
                        "<th>Value before</th><th>Value after</th>"
                        "<th>Severity before (% of limit)</th><th>Severity after (% of limit)</th>"
                        "<th>Normalized improvement (%)</th><th>Status</th></tr>")
                return header + "".join(rows_html)

            html = f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>Scenario Report: {scenario_label}</title>
    <style>
    body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 24px; color: #222; }}
    h1 {{ margin-bottom: 4px; }}
    h2 {{ margin-top: 32px; border-bottom: 2px solid #ddd; padding-bottom: 4px; }}
    .subtitle {{ color: #666; margin-top: 0; }}
    .cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }}
    .card {{ background: #f7f7f9; border: 1px solid #e0e0e0; border-radius: 8px;
            padding: 12px 16px; min-width: 150px; }}
    .card-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
    .card-value {{ font-size: 20px; font-weight: 600; margin-top: 4px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px; }}
    th, td {{ border: 1px solid #ddd; padding: 5px 8px; text-align: left; }}
    th {{ background: #333; color: white; position: sticky; top: 0; }}
    details {{ margin-top: 8px; }}
    summary {{ cursor: pointer; font-weight: 600; padding: 8px; background: #f0f0f0;
                border-radius: 6px; }}
    .table-wrap {{ max-height: 600px; overflow-y: auto; margin-top: 8px; }}
    img {{ max-width: 100%; border: 1px solid #eee; border-radius: 6px; margin: 8px 0; }}
    .legend-swatch {{ display: inline-block; width: 12px; height: 12px; margin-right: 6px;
                        border-radius: 2px; vertical-align: middle; }}
    </style>
    </head>
    <body>

    <h1>Scenario Report: {scenario_label}</h1>
    <p class="subtitle">Closed-loop mall prosumer + grid OPF, {n_total} hourly steps</p>

    <div class="cards">
    {_cards_html()}
    </div>

    <h2>Diagnostics</h2>

    <h3>Power dispatch and feeder loading</h3>
    <img src="data:image/png;base64,{participation_b64}"
        alt="Power dispatch and feeder loading">

    <h3>Storage SOC, setpoint tracking and tracking error</h3>
    <img src="data:image/png;base64,{soc_b64}"
        alt="Storage SOC and power tracking">

    <h3>Network voltage before and after flexibility</h3>
    <img src="data:image/png;base64,{voltage_b64}"
        alt="Network voltage before and after flexibility">
    {bounds_html}
    <h2>Violation Event Log</h2>
    <p>
    <span class="legend-swatch" style="background:#e8f5e9;"></span>Resolved &nbsp;&nbsp;
    <span class="legend-swatch" style="background:#ffcdd2;"></span>Still violating &nbsp;&nbsp;
    <span class="legend-swatch" style="background:#e0e0e0;"></span>PF failed &nbsp;&nbsp;
    <span class="legend-swatch" style="background:#ffe0b2;"></span>Flexibility infeasible &nbsp;&nbsp;
    <span class="legend-swatch" style="background:#eeeeee;"></span>Not evaluated
    </p>
    <div class="table-wrap">
    <table> 
    {_event_table_html()}
    </table>
    </div>

    <h2>Hour-by-Hour Mall Reaction (all {n_total} steps)</h2>
    <p>
    <span class="legend-swatch" style="background:#e8f5e9;"></span>No violation &nbsp;&nbsp;
    <span class="legend-swatch" style="background:#fff9c4;"></span>Violated, resolved by mall &nbsp;&nbsp;
    <span class="legend-swatch" style="background:#ffcdd2;"></span>Violated, not resolved &nbsp;&nbsp;
    <span class="legend-swatch" style="background:#ffe0b2;"></span>Mall had no flexibility available &nbsp;&nbsp;
    <span class="legend-swatch" style="background:#e0e0e0;"></span>Power-flow failure
    </p>
    <details open>
    <summary>Show / hide full hourly table</summary>
    <div class="table-wrap">
    <table>
    {_hourly_table_html()}
    </table>
    </div>
    </details>

    </body>
    </html>
    """

            with open(savepath, "w", encoding="utf-8") as f:
                f.write(html)

            print(f"[{scenario_label}] HTML report written to {savepath}")
            return savepath

###### Grid violation maps -- BEFORE vs AFTER mall flexibility

_ZOOM_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
 body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#fafafa;color:#222}
 header{padding:10px 18px;background:#1f2d3d;color:#fff;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
 header h1{font-size:17px;margin:0;font-weight:600} select,button{font-size:14px;padding:4px 8px}
 .hint{font-size:12px;opacity:.8} .panel{display:none} .panel.on{display:block}
 .info{padding:8px 18px;font-size:14px;background:#fff;border-bottom:1px solid #ddd}
 .viewer{position:relative;overflow:hidden;height:calc(100vh - 118px);background:#fff;cursor:grab}
 .viewer.drag{cursor:grabbing} .stage{transform-origin:0 0;position:absolute;left:0;top:0;width:100%}
 .stage svg{width:100%;height:auto;display:block}
</style></head><body>
<header><h1>__TITLE__</h1>
 <label>View: <select id="sel"></select></label>
 <button id="zin">+</button><button id="zout">&minus;</button><button id="zreset">Reset</button>
 <span class="hint">mouse wheel = zoom, drag = pan, double-click = reset</span></header>
<div id="panels">__PANELS__</div>
<script>
const sel=document.getElementById('sel'), panels=[...document.querySelectorAll('.panel')];
panels.forEach((p,i)=>{const o=document.createElement('option');o.value=i;o.textContent=p.dataset.title;sel.appendChild(o);});
const S=panels.map(()=>({k:1,x:0,y:0}));
function apply(i){const st=panels[i].querySelector('.stage');st.style.transform=`translate(${S[i].x}px,${S[i].y}px) scale(${S[i].k})`;}
function zoomAt(i,f,cx,cy){const s=S[i],nk=Math.min(60,Math.max(1,s.k*f)),r=nk/s.k;
  s.x=cx-(cx-s.x)*r;s.y=cy-(cy-s.y)*r;s.k=nk;if(nk===1){s.x=0;s.y=0;}apply(i);}
function show(i){panels.forEach((p,j)=>p.classList.toggle('on',i==j));sel.value=i;}
panels.forEach((p,i)=>{const v=p.querySelector('.viewer');let d=null;
  v.addEventListener('wheel',e=>{e.preventDefault();const b=v.getBoundingClientRect();
    zoomAt(i,e.deltaY<0?1.2:1/1.2,e.clientX-b.left,e.clientY-b.top);},{passive:false});
  v.addEventListener('mousedown',e=>{d={x:e.clientX-S[i].x,y:e.clientY-S[i].y};v.classList.add('drag');});
  window.addEventListener('mouseup',()=>{d=null;v.classList.remove('drag');});
  window.addEventListener('mousemove',e=>{if(d&&p.classList.contains('on')){S[i].x=e.clientX-d.x;S[i].y=e.clientY-d.y;apply(i);}});
  v.addEventListener('dblclick',()=>{S[i]={k:1,x:0,y:0};apply(i);});});
sel.onchange=()=>show(+sel.value);
const cur=()=>+sel.value, mid=()=>{const v=panels[cur()].querySelector('.viewer').getBoundingClientRect();return[v.width/2,v.height/2];};
document.getElementById('zin').onclick=()=>zoomAt(cur(),1.5,...mid());
document.getElementById('zout').onclick=()=>zoomAt(cur(),1/1.5,...mid());
document.getElementById('zreset').onclick=()=>{S[cur()]={k:1,x:0,y:0};apply(cur());};
show(0);
</script></body></html>"""

class GridViolationMap:    
    @staticmethod
    def _group(d):
        """Rows of violation_details_df -> {violation_type: DataFrame[value, limit] indexed by element_id}."""
        out = {}
        for t in _VIOL_TYPES:
            sub = d[d["violation_type"] == t][["element_id", "value", "limit"]].copy()
            sub["element_id"] = sub["element_id"].astype(int)
            out[t] = sub.drop_duplicates("element_id").set_index("element_id")
        return out
    
    @staticmethod
    def violations_at(details_df, time, phase):
        d = details_df[(details_df["time"] == pd.Timestamp(time)) & (details_df["phase"] == phase)]
        return GridViolationMap._group(d)
    
    @staticmethod
    def envelope(details_df, phase):
        """Worst value each element reached over the whole window (min vm for under-voltage, max otherwise)."""
        d = details_df[details_df["phase"] == phase]
        out = {}
        for t in _VIOL_TYPES:
            sub = d[d["violation_type"] == t].copy()
            sub["element_id"] = sub["element_id"].astype(int)
            fn = "min" if t == "undervoltage" else "max"
            out[t] = sub.groupby("element_id").agg(value=("value", fn), limit=("limit", "first"))
        return out

    @staticmethod
    def _resolved(before, after):
        """Elements violated BEFORE that are no longer violated AFTER."""
        return {t: before[t].index.difference(after[t].index) for t in _VIOL_TYPES}

    @staticmethod
    def _new(before, after):
        """Elements that violate AFTER but did not BEFORE (created by the mall's reaction)."""
        return {t: after[t].index.difference(before[t].index) for t in _VIOL_TYPES}

    @staticmethod
    def _count_text(state):
        parts = [f"{len(state[t])} {_VIOL_LABEL[t][0 if len(state[t]) == 1 else 1]}"
                 for t in _VIOL_TYPES if len(state[t])]
        return ", ".join(parts) if parts else "no violations"

    #  colour scales
    @staticmethod
    def _colour_scales(states):
        """ONE voltage scale and ONE loading scale shared by every panel -> before/after are comparable."""
        volt = pd.concat([s[t]["value"].astype(float) for s in states for t in ("undervoltage", "overvoltage")])
        load = pd.concat([s[t]["value"].astype(float) for s in states for t in ("line_overload", "trafo_overload")])
        v_lo = min(v_min_pu_std - 0.01, float(volt.min()) if len(volt) else 1.0)
        v_hi = max(v_max_pu_std + 0.01, float(volt.max()) if len(volt) else 1.0)
        l_lim = loading_percent_max_std
        l_hi = max(l_lim * 1.25, float(load.max()) if len(load) else l_lim)
        cmap_v = cmap_continuous([(v_lo, "navy"), (v_min_pu_std, "deepskyblue"),
                                  (v_max_pu_std, "gold"), (v_hi, "red")])
        cmap_l = cmap_continuous([(l_lim, "gold"), ((l_lim + l_hi) / 2.0, "orange"), (l_hi, "red")])
        return cmap_v, cmap_l

    #  one panel
    @staticmethod
    def build_collections(net, mall_bus, active, resolved, scales, bus_size, trafo_size=SLD_SYM_TRAFO,
                          label_buses=True):
        """Grey background + coloured violations (+ green resolved elements + mall bus), as pandapower collections.
        pandapower needs z as a pandas Series indexed by element id (a bare array fails in the trafo collection)."""
        (cm_v, nm_v), (cm_l, nm_l) = scales
        C = []
        # ---- grey background
        ln = _sld_table(net, "line")
        if ln is not None:
            ok = _sld_branches_with_geo(net, ln)
            if len(ok):
                C.append(pp_plot.create_line_collection(net, lines=ok, use_bus_geodata=True,
                                                        color=VIOL_BASE_LINE_COLOR, linewidths=1.2, zorder=1))
        geo_buses = [b for b in net.bus.index if _sld_has_geo(net, b)]
        C.append(pp_plot.create_bus_collection(net, buses=geo_buses, size=bus_size * 0.5, patch_type="circle",
                                               color=VIOL_BASE_BUS_COLOR, zorder=2))
        tr = _sld_table(net, "trafo")
        if tr is not None:
            C += _sld_as_list(pp_plot.create_trafo_collection(net, trafos=tr.index, size=trafo_size,
                                                              color=VIOL_BASE_LINE_COLOR, zorder=3))
        eg = _sld_table(net, "ext_grid")
        if eg is not None:
            C += _sld_as_list(pp_plot.create_ext_grid_collection(net, ext_grids=eg.index, size=SLD_SYM_EXTGRID,
                                                                 color=SLD_EXTGRID_COLOR, zorder=3))

        # ---- resolved (green): violated before, fine after
        r_line = net.line.index.intersection(resolved.get("line_overload", []))
        if len(r_line):
            C.append(pp_plot.create_line_collection(net, lines=r_line, use_bus_geodata=True,
                                                    color=VIOL_RESOLVED_COLOR, linewidths=3.0, zorder=4))
        r_trafo = net.trafo.index.intersection(resolved.get("trafo_overload", []))
        if len(r_trafo):
            C += _sld_as_list(pp_plot.create_trafo_collection(net, trafos=r_trafo, size=trafo_size * 1.15,
                                                              color=VIOL_RESOLVED_COLOR, zorder=7))
        r_bus = net.bus.index.intersection(list(resolved.get("undervoltage", [])) +
                                           list(resolved.get("overvoltage", [])))
        r_bus = pd.Index([b for b in r_bus if _sld_has_geo(net, b)])
        if len(r_bus):
            C.append(pp_plot.create_bus_collection(net, buses=r_bus, size=bus_size * 0.9, patch_type="circle",
                                                   color=VIOL_RESOLVED_COLOR, zorder=8))

        # ---- violations (coloured by severity)
        a = active["line_overload"]
        idx = net.line.index.intersection(a.index)
        if len(idx):
            C.append(pp_plot.create_line_collection(net, lines=idx, use_bus_geodata=True, z=a["value"].astype(float),
                                                    cmap=cm_l, norm=nm_l, linewidths=3.8, zorder=5))
        a = active["trafo_overload"]
        idx = net.trafo.index.intersection(a.index)
        if len(idx):
            C += _sld_as_list(pp_plot.create_trafo_collection(net, trafos=idx, size=trafo_size * 1.15,
                                                              z=a["value"].astype(float), cmap=cm_l, norm=nm_l,
                                                              zorder=7))
        v = pd.concat([active["undervoltage"]["value"], active["overvoltage"]["value"]]).astype(float)
        v = v[~v.index.duplicated()]
        v_idx = pd.Index([b for b in net.bus.index.intersection(v.index) if _sld_has_geo(net, b)])
        if len(v_idx):
            C.append(pp_plot.create_bus_collection(net, buses=v_idx, size=bus_size * 1.0, patch_type="circle",
                                                   z=v, cmap=cm_v, norm=nm_v, zorder=9))

        # ---- mall bus (always shown) + labels
        if mall_bus in net.bus.index and _sld_has_geo(net, mall_bus):
            C.append(pp_plot.create_bus_collection(net, buses=[mall_bus], size=bus_size * 1.9, patch_type="rect",
                                                   color=VIOL_MALL_COLOR, zorder=6))
        if label_buses:
            lab = list(v_idx) + list(r_bus) + ([mall_bus] if mall_bus in net.bus.index else [])
            lab = [b for b in dict.fromkeys(lab) if _sld_has_geo(net, b)]
            if lab:
                xy = [SldPlotter._bus_xy(net, b) for b in lab]
                C.append(pp_plot.create_annotation_collection(
                    texts=[("Mall " if b == mall_bus else "") + str(b) for b in lab],
                    coords=[(x - bus_size, y - bus_size * (2.8 if b == mall_bus else 1.8)) for (x, y), b in zip(xy, lab)],
                    size=bus_size * 1.1, color="#222222", zorder=20))
        return C

    #  before | after figure
    @staticmethod
    def plot_before_after(net, mall_bus, before, after, title, bus_size, after_note=None, resolved=None):
        """Two panels (BEFORE | AFTER mall flexibility), shared colour scales. after=None -> after not evaluated."""
        empty = {t: pd.DataFrame(columns=["value", "limit"]) for t in _VIOL_TYPES}
        scales = GridViolationMap._colour_scales([before] + ([after] if after is not None else []))
        if resolved is None and after is not None:
            resolved = GridViolationMap._resolved(before, after)
        fig_w, fig_h = SldPlotter._compute_sld_figsize(net)
        fig, axes = plt.subplots(1, 2, figsize=(min(2 * fig_w * 0.75, 44), fig_h * 0.85), layout="constrained")

        GridViolationMap._draw(axes[0], net, mall_bus, before, {}, scales, bus_size,
                               f"BEFORE mall flexibility: {GridViolationMap._count_text(before)}")
        if after is None:
            GridViolationMap._draw(axes[1], net, mall_bus, empty, {}, scales, bus_size,
                                   f"AFTER mall flexibility: {after_note or 'not evaluated'}")
        else:
            n_res = sum(len(v) for v in resolved.values())
            n_new = sum(len(v) for v in GridViolationMap._new(before, after).values())
            extra = f" | {n_res} resolved" + (f" | {n_new} NEW" if n_new else "")
            GridViolationMap._draw(axes[1], net, mall_bus, after, resolved, scales, bus_size,
                                   f"AFTER mall flexibility: {GridViolationMap._count_text(after)}{extra}")

        (cm_v, nm_v), (cm_l, nm_l) = scales
        cb = fig.colorbar(ScalarMappable(norm=nm_v, cmap=cm_v), ax=list(axes), orientation="horizontal",
                          location="bottom", fraction=0.035, pad=0.02, aspect=50)
        cb.set_label(f"Bus voltage [pu]   (limits {v_min_pu_std:.2f} / {v_max_pu_std:.2f})")
        cb = fig.colorbar(ScalarMappable(norm=nm_l, cmap=cm_l), ax=list(axes), orientation="horizontal",
                          location="bottom", fraction=0.035, pad=0.06, aspect=50)
        cb.set_label(f"Line / trafo loading [%]   (limit {loading_percent_max_std:.0f} %)")
        handles = [Line2D([0], [0], marker="s", ls="", color=VIOL_MALL_COLOR, label="Mall bus"),
                   Line2D([0], [0], marker="o", ls="", color=VIOL_RESOLVED_COLOR, label="Violated before, resolved"),
                   Line2D([0], [0], marker="o", ls="", color="red", label="Violating (colour = severity)"),
                   Line2D([0], [0], color=VIOL_BASE_LINE_COLOR, lw=2, label="Within limits")]
        axes[0].legend(handles=handles, loc="lower left", fontsize=8, frameon=True)
        fig.suptitle(title, fontsize=13, fontweight="bold")
        return fig

    @staticmethod
    def _draw(ax, net, mall_bus, active, resolved, scales, bus_size, title):
        C = GridViolationMap.build_collections(net, mall_bus, active, resolved, scales, bus_size)
        pp_plot.draw_collections(C, ax=ax, figsize=None, plot_colorbars=False, axes_visible=(False, False))
        ax.set_title(title, fontsize=10)

    #  HTML
    @staticmethod
    def _patch_gc_styles():
        """Work around "AttributeError: 'str' object has no attribute 'name'" in matplotlib's SVG backend:
        some collections hand over capstyle/joinstyle as plain strings, which only the SVG writer chokes on
        (PNG/Agg tolerates them). Make the getters accept both strings and the CapStyle/JoinStyle enums."""
        from matplotlib.backend_bases import GraphicsContextBase as _GC
        if getattr(_GC, "_style_patch_applied", False):
            return

        def _name(v):
            return getattr(v, "name", v if isinstance(v, str) else str(v))

        _GC.get_capstyle = lambda self: _name(self._capstyle)
        _GC.get_joinstyle = lambda self: _name(self._joinstyle)
        _GC._style_patch_applied = True

    @staticmethod
    def fig_to_svg(fig):
        """Inline SVG (vector -> stays sharp at any zoom); text kept as text so the file stays small."""
        buf = io.StringIO()
        GridViolationMap._patch_gc_styles()
        with plt.rc_context({"svg.fonttype": "none"}):
            fig.savefig(buf, format="svg", bbox_inches="tight")
        svg = buf.getvalue()
        return svg[svg.index("<svg"):]

    @staticmethod
    def write_zoomable_html(path, title, panels):
        """panels: list of (panel_title, svg_markup). One <select> switches views; wheel zooms, drag pans."""
        body = "".join(
            f'<div class="panel" data-title="{html_lib.escape(t)}"><div class="info">{html_lib.escape(t)}</div>'
            f'<div class="viewer"><div class="stage">{svg}</div></div></div>' for t, svg in panels)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_ZOOM_HTML.replace("__TITLE__", html_lib.escape(title)).replace("__PANELS__", body))
        return path

    @staticmethod
    def build_scenario_maps(net_template, mall_bus, details_df, results_df, scenario_label,
                            output_dir="scenario_outputs", top_hours=VIOLATION_MAP_TOP_HOURS):
        """Before/after violation maps for one scenario. Returns the HTML path (or None if nothing violated)."""
        if (details_df is None or details_df.empty or "phase" not in details_df.columns
                or not (details_df["phase"] == "before").any()):
            print(f"[{scenario_label}] No grid violations -> no violation map written.")
            return None
        os.makedirs(output_dir, exist_ok=True)
        net = copy.deepcopy(net_template)
        if any(not _sld_has_geo(net, b) for b in net.bus.index):
            FeederTopology.compute_hierarchical_layout(net)          # fills missing coordinates (same as the SLD)
        bus_size = min(SLD_LEAF_STEP, SLD_DEPTH_STEP) * 0.08

        d = details_df.copy()
        d["time"] = pd.to_datetime(d["time"])
        before_n = d[d["phase"] == "before"].groupby("time").size()
        after_n = d[d["phase"] == "after"].groupby("time").size()
        hours = list(before_n.sort_values(ascending=False).head(top_hours).index)
        if len(after_n) and after_n.idxmax() not in hours:
            hours.append(after_n.idxmax())                           # always include the worst RESIDUAL hour
        hours = sorted(hours)

        panels, first_png = [], None
        # --- 1) whole-window envelope: worst value every element reached
        env_b, env_a = GridViolationMap.envelope(d, "before"), GridViolationMap.envelope(d, "after")
        fig = GridViolationMap.plot_before_after(
            net, mall_bus, env_b, env_a,
            f"[{scenario_label}] worst case over the whole window (every element at its worst hour)", bus_size)
        panels.append(("Whole window - worst case per element", GridViolationMap.fig_to_svg(fig)))
        plt.close(fig)

        # --- 2) the worst hours, individually
        for h in hours:
            status = None
            if results_df is not None and "status" in results_df.columns and pd.Timestamp(h) in results_df.index:
                status = str(results_df.loc[pd.Timestamp(h), "status"])
            evaluated = status not in (STATUS_PF_FAILED, STATUS_NOT_EVALUATED)
            b = GridViolationMap.violations_at(d, h, "before")
            a = GridViolationMap.violations_at(d, h, "after") if evaluated else None
            fig = GridViolationMap.plot_before_after(
                net, mall_bus, b, a, f"[{scenario_label}] {pd.Timestamp(h):%Y-%m-%d %H:%M} (status: {status})",
                bus_size, after_note=status)
            panels.append((f"{pd.Timestamp(h):%Y-%m-%d %H:%M} - {status} "
                           f"({int(before_n.get(h, 0))} before / {int(after_n.get(h, 0))} after)",
                           GridViolationMap.fig_to_svg(fig)))
            if first_png is None:                                    # PNG of the single worst hour
                first_png = os.path.join(output_dir, f"{scenario_label}_violation_map_worst_hour.png")
                fig.savefig(first_png, dpi=110, bbox_inches="tight")
            plt.close(fig)

        path = os.path.join(output_dir, f"{scenario_label}_grid_violation_map.html")
        GridViolationMap.write_zoomable_html(path, f"{scenario_label}: grid violations before vs after mall flexibility",
                                             panels)
        print(f"[{scenario_label}] violation map written: {path}" + (f" (+ {first_png})" if first_png else ""))
        return path

#####   Single-scenario orchestration
class ScenarioRunner:
    @staticmethod
    def run_scenario(scenario_label, direction, ses_data_1h_full, heat_data_file,
                      window_start, window_end, mall_bus,
                      grid_load_scale=1.0, grid_sgen_scale=1.0,
                      mall_pv_scale=1.0,
                      profiles=None, idx=None,
                       scoped_sgen_idx=None, scoped_load_idx=None,
                      capture_violated_snapshots=True):

        print(f"\n{'='*70}\nSCENARIO: {scenario_label} (direction={direction})\n"
              f"Window: {window_start} to {window_end} (exclusive)\n"
              f"Mall bus: {mall_bus} on {GRID_CODE} | "
              f"grid_load_scale={grid_load_scale} grid_sgen_scale={grid_sgen_scale} "
              f"mall_pv_scale={mall_pv_scale} "
              f"scoped_sgen_idx={scoped_sgen_idx} "
              f"scoped_load_idx={scoped_load_idx}\n{'='*70}")

        if ses_data_1h_full.index.min() > window_start or ses_data_1h_full.index.max() < window_end - pd.Timedelta(hours=1):
            raise RuntimeError(f"[{scenario_label}] SES data does not cover the requested window.")

        ses_data_1h = ses_data_1h_full.loc[window_start:window_end - pd.Timedelta(hours=1)]

        start = ses_data_1h.index.min().strftime("%Y-%m-%d %H:%M:%S")
        end = ses_data_1h.index.max().strftime("%Y-%m-%d %H:%M:%S")

        p_el_sc_kw = ses_data_1h["P el sc [kW]"].astype(float).to_numpy()
        p_pv_kw = ses_data_1h["P pv [kW]"].astype(float).to_numpy()
        residual_mall_load_kw = (p_el_sc_kw - p_pv_kw * mall_pv_scale)
        n_steps = len(residual_mall_load_kw)

        print(f"[{scenario_label}] Start: {start}  End: {end}  Steps: {n_steps}")
        print(f"[{scenario_label}] Residual mall load min/max: "
              f"{residual_mall_load_kw.min():.3f} / {residual_mall_load_kw.max():.3f} kW")

        time_series_data = build_time_series_data(start, n_steps, heat_data_file)

        if profiles is None or idx is None:
            net_template = NetFactory.get_net_template(GRID_CODE)
            profiles = GridSource.get_profiles(net_template, GRID_CODE)
            idx = pd.date_range(YEAR_START, periods=len(profiles[("load", "p_mw")]), freq="15min")

        q_mall_base_mvar = 0.0
        q_eps = IMPORT_Q_EPS_MVAR
        net_base, mall_load, mall_feeder_line_idx = NetFactory.build_base_net(
            mall_bus=mall_bus, q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps)

        print(f"[{scenario_label}] Running closed-loop prosumer + grid OPF ({n_steps} hourly steps)...")

        (opf_results_df, updated_flex_target_kw, res_base, res_actual,
         bounds_df, violation_details_df, violated_net_snapshots,
         element_metrics_df) = OpfTimeseriesRunner.run_opf_timeseries_for_scenario(
            scenario_label=scenario_label, 
            net_base=net_base, mall_load=mall_load, mall_feeder_line_idx=mall_feeder_line_idx,
            profiles=profiles, idx=idx,
            time_series_data_base=time_series_data,
            residual_mall_load_kw=residual_mall_load_kw,
            grid_load_scale=grid_load_scale, grid_sgen_scale=grid_sgen_scale,
            q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps,
            initial_soc=INIT_SOC, scoped_sgen_idx=scoped_sgen_idx, scoped_load_idx=scoped_load_idx,
            capture_violated_snapshots=capture_violated_snapshots)

        opf_results_df["p_updated_grid_kw"] = res_actual["p_grid_kw"].reindex(opf_results_df.index)
        opf_results_df["tracking_error_kw"] = opf_results_df["p_updated_grid_kw"] - opf_results_df["p_grid_setpoint_kw"]
        # Reports and CSVs use the same canonical five-status model as the outer scenario study.
        opf_results_df = _normalise_scenario_results(opf_results_df, violation_details_df, scenario_label)

        #opf_results_df.to_csv(f"grid_opf_timeseries_results_{scenario_label}.csv")
        #bounds_df.to_csv(f"grid_flexibility_bounds_{scenario_label}.csv")
        #violation_details_df.to_csv(f"grid_violation_details_{scenario_label}.csv", index=False)
        # Human-readable Excel report
        # 
        ScenarioHtmlReport.write_scenario_excel_report(
            scenario_label=scenario_label,
            opf_results_df=opf_results_df,
            bounds_df=bounds_df,
            violation_details_df=violation_details_df,
            res_actual=res_actual,
        )
        SldPlotter.print_scenario_summary(scenario_label, opf_results_df, violation_details_df, res_actual)
                # Save and display the diagnostic PNG figures.
        SldPlotter.plot_scenario_diagnostics(
            opf_results_df=opf_results_df,
            res_actual=res_actual,
            scenario_label=scenario_label,
            violation_details_df=violation_details_df
        )
        ScenarioHtmlReport.build_scenario_html_report(scenario_label, opf_results_df, violation_details_df, res_actual,bounds_df=bounds_df)

        return (opf_results_df, bounds_df, residual_mall_load_kw,
                violation_details_df, violated_net_snapshots, element_metrics_df)

#####   HyperCAP reduction, visualization, and export
class HyperCapReducer:
    @staticmethod
    def _run_equivalence_pf(net):
        """Fresh, isolated power flow used only for equivalence validation --deliberately separate from the main script's run_pf() (different solver
    settings: voltage angles + Q-limit enforcement, matching what the standalone validator used) so it never interferes with the OPF
    timeseries loop elsewhere in the script. Kept separate from the comparison logic below because it's a solve step, not a diff --
    it runs once per network, before any comparing happens."""
        net = copy.deepcopy(net)
        try:
            pp.runpp(net, calculate_voltage_angles=True, init="auto", enforce_q_lims=True)
            return net, bool(getattr(net, "converged", False)), None
        except Exception as exc:
            return net, False, f"{type(exc).__name__}: {exc}"
         
    @staticmethod
    def _compare_table_columns(reduced_pf, source_pf, table_name, columns, indices=None):
        """Generic comparator: diffs `columns` of `table_name` (e.g. "res_bus",
        "res_line", "res_ext_grid") between two solved pandapower nets, returning
        {column: max_abs_diff}.

        indices=None -> compare every index common to both nets (used for
            branches/ext_grid, where "common" = retained/matching elements).
        indices=[...] -> compare only these indices, still intersected with
            what's actually present in both nets (used for bus sets, where the
            caller supplies a specific internal/boundary bus list).

        A column that has no comparable rows (missing table, no overlap, all
        values non-finite) comes back as None rather than raising, so a caller
        can distinguish "nothing to compare" from "difference of zero"."""

        def _safe_float(value):
            try:
                value = float(value)
                if math.isfinite(value):
                    return value
            except Exception:
                pass
            return None

        if table_name not in reduced_pf or table_name not in source_pf:
            missing = []
            if table_name not in reduced_pf:
                missing.append("reduced")
            if table_name not in source_pf:
                missing.append("source")

            print(
                f"[HyperCAP comparison] Table '{table_name}' missing from "
                f"{', '.join(missing)} network(s). No comparison performed."
            )
            return {col: None for col in columns}

        reduced_table = reduced_pf[table_name]
        source_table = source_pf[table_name]

        reduced_indices = set(int(x) for x in reduced_table.index)
        source_indices = set(int(x) for x in source_table.index)
        common = reduced_indices & source_indices

        if indices is not None:
            requested = set(int(x) for x in indices)

            missing_reduced = sorted(requested - reduced_indices)
            missing_source = sorted(requested - source_indices)

            if missing_reduced:
                print(
                    f"[HyperCAP comparison] Table '{table_name}': requested "
                    f"indices absent from reduced results: {missing_reduced}"
                )
            if missing_source:
                print(
                    f"[HyperCAP comparison] Table '{table_name}': requested "
                    f"indices absent from source results: {missing_source}"
                )

            common &= requested
        else:
            only_reduced = sorted(reduced_indices - source_indices)
            only_source = sorted(source_indices - reduced_indices)

            if only_reduced:
                print(
                    f"[HyperCAP comparison] Table '{table_name}': indices "
                    f"present only in reduced results (not compared): {only_reduced}"
                )
            if only_source:
                pass
                # print(
                #     f"[HyperCAP comparison] Table '{table_name}': indices "
                #     f"present only in source results (not compared): {only_source}"
                # )

        diffs = {col: [] for col in columns}
        compared_counts = {col: 0 for col in columns}
        unusable_counts = {col: 0 for col in columns}

        for col in columns:
            missing_columns = []
            if col not in reduced_table.columns:
                missing_columns.append("reduced")
            if col not in source_table.columns:
                missing_columns.append("source")

            if missing_columns:
                pass
                # print(
                #     f"[HyperCAP comparison] Table '{table_name}', column '{col}' "
                #     f"missing from {', '.join(missing_columns)} results."
                # )

        for idx in sorted(common):
            for col in columns:
                if col not in reduced_table.columns or col not in source_table.columns:
                    continue

                rv = _safe_float(reduced_table.at[idx, col])
                sv = _safe_float(source_table.at[idx, col])

                if rv is not None and sv is not None:
                    diffs[col].append(rv - sv)
                    compared_counts[col] += 1
                else:
                    unusable_counts[col] += 1

        result = {}
        for col, values in diffs.items():
            finite = [abs(v) for v in values if math.isfinite(v)]
            result[col] = max(finite) if finite else None

           # print(
            #    f"[HyperCAP comparison] Table='{table_name}', column='{col}': "
            #    f"common rows={len(common)}, "
            #    f"compared={compared_counts[col]}, "
           #     f"unusable={unusable_counts[col]}, "
           #     f"max_abs_diff={result[col]}"
           # )

        return result

    @staticmethod
    def collect_violated_element_ids(df, phase="after"):
        out = {"bus": set(), "line": set(), "trafo": set()}
        if df is None or df.empty:
            return out
        required = {"phase", "violation_type", "element_id"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Violation table is missing required column(s): {sorted(missing)}")
        rows = df[df["phase"].astype(str) == str(phase)]
        for _, row in rows.iterrows():
            violation_type = str(row["violation_type"])
            element_id = int(row["element_id"])
            if violation_type in {"undervoltage", "overvoltage"}:
                out["bus"].add(element_id)
            elif violation_type == "line_overload":
                out["line"].add(element_id)
            elif violation_type == "trafo_overload":
                out["trafo"].add(element_id)
            else:
                raise ValueError(f"Unsupported violation_type={violation_type!r}.")
        return out

    @staticmethod
    def violated_elements_to_seed_buses(net, violated_elements):
        buses = {int(b) for b in violated_elements.get("bus", set())}
        for line_id in violated_elements.get("line", set()):
            line_id = int(line_id)
            if line_id not in net.line.index:
                raise KeyError(f"Violation references missing line index {line_id}.")
            buses.add(int(net.line.at[line_id, "from_bus"]))
            buses.add(int(net.line.at[line_id, "to_bus"]))
        for trafo_id in violated_elements.get("trafo", set()):
            trafo_id = int(trafo_id)
            if trafo_id not in net.trafo.index:
                raise KeyError(f"Violation references missing trafo index {trafo_id}.")
            buses.add(int(net.trafo.at[trafo_id, "hv_bus"]))
            buses.add(int(net.trafo.at[trafo_id, "lv_bus"]))
        return buses

    @staticmethod
    def find_boundary_buses(net, internal_buses):
        detailed = {int(b) for b in internal_buses}
        if not detailed:
            return set()
        graph = create_nxgraph(net, respect_switches=True)
        boundary = set()
        for bus in sorted(detailed):
            if bus not in graph:
                raise KeyError(f"Detailed bus {bus} is not present in pandapower graph.")
            for neighbor in graph.neighbors(bus):
                neighbor = int(neighbor)
                if neighbor not in detailed:
                    boundary.add(neighbor)
        return boundary

    @staticmethod
    def normalize_boundary_buses(net, raw_boundary_buses, verbose=True):
        raw = sorted({int(b) for b in raw_boundary_buses})
        if not raw:
            return set()

        _, bus_groups = get_connected_switch_buses_groups(net, raw)

        normalized = set()
        seen = set()
        collapsed_records = []
        for group in bus_groups:
            members = sorted({int(b) for b in group})
            raw_members = sorted(set(members) & set(raw))
            if not raw_members:
                continue
            representative = min(members)
            normalized.add(representative)
            seen.update(members)
            if len(members) > 1:
                collapsed_records.append((members, raw_members, representative))

        for bus in raw:
            if bus not in seen:
                normalized.add(bus)

        if verbose and collapsed_records:
            print(f"    [boundary collapse] {len(collapsed_records)} switch-group(s) merged: " +
                  ", ".join(f"{m}->{r}" for m, _, r in sorted(collapsed_records, key=lambda x: x[2])))

        return normalized

    @staticmethod
    def build_reduced_net_for_case(net_snapshot, boundary_buses, internal_buses, eq_type="ward"):
        boundary = sorted({int(b) for b in boundary_buses})
        internal = sorted({int(b) for b in internal_buses})

        if not internal:
            raise RuntimeError("HyperCAP detailed/internal bus set is empty.")
        if not boundary:
            raise RuntimeError("HyperCAP boundary bus set is empty.")

        overlap = set(boundary) & set(internal)
        if overlap:
            raise RuntimeError(f"HyperCAP internal and boundary bus sets overlap: {sorted(overlap)}")

        ge_module = importlib.import_module("pandapower.grid_equivalents.get_equivalent")
        original_merge = ge_module.merge_internal_net_and_equivalent_external_net

        def _strip_unmergeable_tables(*args, **kwargs):
            net_eq = args[0] if len(args) >= 2 else kwargs.get("net_eq")
            net_internal = args[1] if len(args) >= 2 else kwargs.get("net_internal")
            for merge_net in (net_eq, net_internal):
                for table_name in ("bus_geodata", "loadcases"):
                    if table_name in merge_net:
                        merge_net[table_name] = merge_net[table_name].iloc[0:0].copy()
            return original_merge(*args, **kwargs)

        ge_module.merge_internal_net_and_equivalent_external_net = _strip_unmergeable_tables
        try:
            reduced = pp_get_equivalent(net_snapshot, eq_type=eq_type, boundary_buses=boundary,
                                         internal_buses=internal, return_internal=True)
        finally:
            ge_module.merge_internal_net_and_equivalent_external_net = original_merge

        if reduced is None:
            raise RuntimeError("pandapower.get_equivalent() returned None.")

        return reduced

    @staticmethod
    def build_scenario_region(scenario, ordered_hours, snapshot_lookup, violation_table,
                               phase="after", verbose=True):
        """computes ONE frozen Ward-reduction region for `scenario`.
        Per hour: derives that hour's violation seed buses using the exact same helpers as the original per-hour path (collect_violated_element_ids
        + violated_elements_to_seed_buses). Unions the seed buses across every hour in the scenario, expands the union through switch-closed groups
        (get_connected_switch_buses_groups) exactly once, then calls find_boundary_buses / normalize_boundary_buses exactly once on that
        union -- instead of computing a separate region per hour.
        Topology bus lookups here are read-only (no net is mutated) and use the scenario's first hour as the topology reference net, since every
        hour within one scenario shares net_base's topology by construction (the same assumption Section 15 / merge_loadcases relies on).
        Returns (detailed_buses, boundary_buses, per_hour_seed_meta) where per_hour_seed_meta = {timestamp.isoformat(): {"violation_element_ids":
        {...}, "seed_buses": [...]}}.
        """
        if not ordered_hours:
            raise RuntimeError(f"HyperCAP scenario region for {scenario!r} has no hours.")

        topology_net = snapshot_lookup[(scenario, ordered_hours[0])]

        union_seed_buses = set()
        per_hour_seed_meta = {}

        for timestamp in ordered_hours:
            hour_rows = violation_table[(violation_table["_hypercap_time"] == timestamp)
                                         & (violation_table["_hypercap_phase"] == str(phase))]
            if hour_rows.empty:
                raise KeyError(
                    f"No {phase!r}-phase violation rows found for scenario={scenario!r} "
                    f"hour={timestamp}.")

            violations = HyperCapReducer.collect_violated_element_ids(hour_rows, phase=phase)
            hour_seed_buses = HyperCapReducer.violated_elements_to_seed_buses(topology_net, violations)
            if not hour_seed_buses:
                raise RuntimeError(
                    f"HyperCAP scenario {scenario!r} hour {timestamp} has no violation seed buses.")

            union_seed_buses |= hour_seed_buses
            per_hour_seed_meta[timestamp.isoformat()] = {
                "violation_element_ids": {name: sorted(int(x) for x in values)
                                           for name, values in violations.items()},
                "seed_buses": sorted(hour_seed_buses),
            }

        detailed_buses = set(get_connected_switch_buses_groups(topology_net, union_seed_buses)[0])
        if not detailed_buses:
            raise RuntimeError(f"HyperCAP scenario {scenario!r} produced an empty detailed bus set.")

        raw_boundary_buses = HyperCapReducer.find_boundary_buses(topology_net, detailed_buses)
        boundary_buses = HyperCapReducer.normalize_boundary_buses(
            topology_net, raw_boundary_buses, verbose=verbose)

        if detailed_buses & boundary_buses:
            raise RuntimeError(
                f"HyperCAP scenario {scenario!r} region has overlapping detailed/boundary buses: "
                f"{sorted(detailed_buses & boundary_buses)}")
        if not boundary_buses:
            raise RuntimeError(f"HyperCAP scenario {scenario!r} region has no boundary buses.")

        return detailed_buses, boundary_buses, per_hour_seed_meta

    @staticmethod
    def _normalize_hypercap_timestamp(value):
        ts = pd.Timestamp(value)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    @staticmethod
    def _snapshot_lookup(violated_net_snapshots):
        lookup = {}
        for (scenario, timestamp), net in violated_net_snapshots.items():
            key = (str(scenario), HyperCapReducer._normalize_hypercap_timestamp(timestamp))
            if key in lookup:
                raise RuntimeError(f"Duplicate HyperCAP snapshot after timestamp normalization: {key}")
            lookup[key] = net
        return lookup
 
    @staticmethod
    def validate_hypercap_case(case_id, reduced_net, source_net, detailed_internal_buses,
                                boundary_buses):
        """Electrical-equivalence check for one HyperCAP case: runs a fresh PF on  both the reduced network and its exact pre-reduction source, then
    compares voltage/angle/P/Q at internal + boundary buses, loading on any commonly retained lines/trafos, and ext_grid P/Q. Returns a dict with
    "passed" (bool), "failed_checks" (list of str), and the raw max-abs differences for reference. Never raises on a failed comparison -- only
    on a hard structural problem (e.g. PF not converging), which is itself reported via "passed": False rather than an exception, so a single bad
    case never aborts the whole export loop."""
 
        result = {"case_id": str(case_id), "passed": True, "failed_checks": [], "reasons": []}
 
        reduced_pf, reduced_converged, reduced_err = HyperCapReducer._run_equivalence_pf(reduced_net)
        if not reduced_converged:
            result["passed"] = False
            result["reasons"].append(f"Reduced-network PF did not converge ({reduced_err}).")
            return result
 
        source_pf, source_converged, source_err = HyperCapReducer._run_equivalence_pf(source_net)
        if not source_converged:
            result["passed"] = False
            result["reasons"].append(f"Source-network PF did not converge ({source_err}).")
            return result
 
        bus_cols = ["vm_pu", "va_degree", "p_mw", "q_mvar"]
 
        internal_summary = HyperCapReducer._compare_table_columns(
            reduced_pf, source_pf, "res_bus", bus_cols, indices=sorted(detailed_internal_buses))
        boundary_summary = HyperCapReducer._compare_table_columns(
            reduced_pf, source_pf, "res_bus", bus_cols, indices=sorted(boundary_buses))
        line_loading = HyperCapReducer._compare_table_columns(
            reduced_pf, source_pf, "res_line", ["loading_percent"])
        trafo_loading = HyperCapReducer._compare_table_columns(
            reduced_pf, source_pf, "res_trafo", ["loading_percent"])
        ext_grid = HyperCapReducer._compare_table_columns(
            reduced_pf, source_pf, "res_ext_grid", ["p_mw", "q_mvar"])
 
        result["internal_bus_summary"] = internal_summary
        result["boundary_bus_summary"] = boundary_summary
        result["line_loading_max_abs_diff_pct"] = line_loading["loading_percent"]
        result["trafo_loading_max_abs_diff_pct"] = trafo_loading["loading_percent"]
        result["ext_grid_p_max_abs_diff_mw"] = ext_grid["p_mw"]
        result["ext_grid_q_max_abs_diff_mvar"] = ext_grid["q_mvar"]
 
        checks = [
            ("internal_voltage", internal_summary["vm_pu"], HYPERCAP_VOLTAGE_TOLERANCE_PU),
            ("boundary_voltage", boundary_summary["vm_pu"], HYPERCAP_VOLTAGE_TOLERANCE_PU),
            ("internal_angle", internal_summary["va_degree"], HYPERCAP_ANGLE_TOLERANCE_DEG),
            ("boundary_angle", boundary_summary["va_degree"], HYPERCAP_ANGLE_TOLERANCE_DEG),
            ("retained_line_loading", line_loading["loading_percent"], HYPERCAP_LOADING_TOLERANCE_PERCENT),
            ("retained_trafo_loading", trafo_loading["loading_percent"], HYPERCAP_LOADING_TOLERANCE_PERCENT),
            ("ext_grid_active_power", ext_grid["p_mw"], HYPERCAP_POWER_TOLERANCE_MW),
            ("ext_grid_reactive_power", ext_grid["q_mvar"], HYPERCAP_POWER_TOLERANCE_MVAR),
        ]
 
        for name, value, tolerance in checks:
            if value is None:
                continue  # nothing to compare (e.g. no lines in common) -- not a failure
            if value > tolerance:
                result["passed"] = False
                result["failed_checks"].append(f"{name} (|diff|={value:.6g} > tol={tolerance:.6g})")
 
        if not result["passed"] and not result["reasons"]:
            result["reasons"] = [f"Tolerance exceeded: {c}" for c in result["failed_checks"]]
 
        return result

class HyperCapSldPlotter:
    @staticmethod
    def _draw_hypercap_region_patches(ax, coords, internal_buses, boundary_buses):
        """Background patches marking the internal (detailed), boundary (interface), and external (Ward-equivalent) regions. Visualization
    only -- does not touch net."""
        xs = [xy[0] for xy in coords.values()]
        ys = [xy[1] for xy in coords.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        x_span, y_span = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
 
        outer_pad_x, outer_pad_y = max(1.5, x_span * 0.08), max(1.5, y_span * 0.08)
        ax.add_patch(mpatches.FancyBboxPatch(
            (min_x - outer_pad_x, min_y - outer_pad_y),
            x_span + 2 * outer_pad_x, y_span + 2 * outer_pad_y,
            boxstyle="round,pad=0.02,rounding_size=0.35",
            facecolor="none", edgecolor="#1f77d0", linewidth=1.8,
            linestyle="--", alpha=0.28, zorder=0))
 
        def _region_patch(bus_set, pad_min, pad_frac, rounding, facecolor, edgecolor,
                           linewidth, linestyle, alpha, zorder, label, label_color):
            pts = [coords[b] for b in bus_set if b in coords]
            if not pts:
                return
            bx, by = [p[0] for p in pts], [p[1] for p in pts]
            pad_x = max(pad_min, x_span * pad_frac)
            pad_y = max(pad_min, y_span * pad_frac)
            rx0, ry0 = min(bx) - pad_x, min(by) - pad_y
            rw = (max(bx) - min(bx)) + 2 * pad_x
            rh = (max(by) - min(by)) + 2 * pad_y
            ax.add_patch(mpatches.FancyBboxPatch(
                (rx0, ry0), rw, rh, boxstyle=f"round,pad=0.02,rounding_size={rounding}",
                facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth,
                linestyle=linestyle, alpha=alpha, zorder=zorder))
            ax.text(rx0 + 0.15, ry0 + rh - 0.15, label, fontsize=9, fontweight="bold",
                    color=label_color, ha="left", va="top", zorder=20,
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                              edgecolor=edgecolor, alpha=0.90))
 
        _region_patch(internal_buses, 0.9, 0.045, "0.30", "none", "#2ca02c",
                      2.0, "--", 0.42, 0.5, "INTERNAL\n(detailed)", "#207020")
        _region_patch(boundary_buses, 0.65, 0.03, "0.25", "none", "#e69f00",
                      1.8, ":", 0.25, 0.7, "BOUNDARY\n(interface)", "#a35a00")
 
        ax.text(max_x + outer_pad_x * 0.55, max_y - outer_pad_y * 0.30,
                "EXTERNAL NETWORK\nrepresented by Ward equivalent",
                fontsize=10, fontweight="bold", color="#155a9c", ha="right", va="top",
                zorder=20, bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                                      edgecolor="#1f77d0", alpha=0.94))
 
    @staticmethod
    def _draw_hypercap_ward_symbols(ax, net, coords, busbar_half_width=0.35):
        """Draws an explanatory 'W' box next to each Ward-equivalent bus stacking multiple wards at the same bus. The Ward elements themselves
    already exist in net.ward -- this only annotates them."""
        if not (hasattr(net, "ward") and len(net.ward)):
            return
        ward_offsets = {}
        for _, row in net.ward.iterrows():
            bus = int(row["bus"])
            if bus not in coords:
                continue
            x, y = coords[bus]
            offset_no = ward_offsets.get(bus, 0)
            ward_offsets[bus] = offset_no + 1
            icon_x, icon_y = x - 1.0, y + 0.75 + offset_no * 0.65
 
            ax.plot([x, icon_x], [y + busbar_half_width, icon_y],
                    color="#1f77d0", linewidth=1.4, zorder=4)
            ax.add_patch(mpatches.Rectangle((icon_x - 0.28, icon_y - 0.22), 0.56, 0.44,
                                            facecolor="white", edgecolor="#1f77d0",
                                            linewidth=2.0, hatch="xx", zorder=8))
            ax.text(icon_x, icon_y, "W", ha="center", va="center", fontsize=9,
                    fontweight="bold", color="#1f77d0", zorder=9)
            ax.text(icon_x - 0.38, icon_y, "Ward\nexternal", ha="right", va="center",
                    fontsize=7.5, fontweight="bold", color="#1f77d0", zorder=9)
 
    @staticmethod
    def _label_hypercap_buses(ax, coords, internal_buses, boundary_buses):
        for bus, (x, y) in coords.items():
            if bus in internal_buses:
                label_color = "#207020"
            elif bus in boundary_buses:
                label_color = "#a35a00"
            else:
                label_color = "black"
            ax.annotate(str(bus), xy=(x, y), xytext=(-10, -12), textcoords="offset points",
                        fontsize=8.5, color=label_color, fontweight="bold", zorder=20,
                        clip_on=False, ha="right", va="top",
                        bbox=dict(boxstyle="round,pad=0.13", facecolor="white",
                                  edgecolor="none", alpha=0.88))

    @staticmethod
    def _draw_hypercap_legend_and_panel(ax, net, case_id, internal_buses, boundary_buses):
        extra_handles = [
            mpatches.Patch(facecolor="#b9e6b0", edgecolor="#2ca02c", label="Internal bus / detailed area"),
            mpatches.Patch(facecolor="#ffe08a", edgecolor="#e69f00", label="Boundary bus / interface"),
            mpatches.Patch(facecolor="#dbeeff", edgecolor="#1f77d0", linestyle="--",
                           label="External network / represented by equivalent"),
            mpatches.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="#1f77d0",
                               hatch="xx", label="Ward equivalent"),
        ]
        SldPlotter._build_sld_legend(ax, extra_handles=extra_handles, net=net,
                                     title="HyperCAP classification")

        case_text = (f"CASE\n{case_id}\n\n"
                     f"Internal: {sorted(internal_buses)}\n"
                     f"Boundary: {sorted(boundary_buses)}\n"
                     f"Ward elements: {len(net.ward) if hasattr(net, 'ward') else 0}\n"
                     f"Reduced buses: {len(net.bus)}")
        ax.text(0.995, 0.02, case_text, transform=ax.transAxes, fontsize=8.5,
                ha="right", va="bottom", zorder=30,
                bbox=dict(boxstyle="round,pad=0.45", facecolor="white",
                          edgecolor="#999999", alpha=0.94))

    @staticmethod
    def plot_hypercap_reduced_sld(net, case_id, case_metadata, savepath, dpi=220,
                                   leaf_step=SLD_LEAF_STEP, depth_step=SLD_DEPTH_STEP,
                                   busbar_half_width=0.35):
        """Visualization-only SLD for one already-reduced HyperCAP network.
    Classification: GREEN = internal (detailed), ORANGE = boundary
    (interface), BLUE = external network (Ward equivalent), HATCH = Ward
    element. Reuses SldPlotter.build_sld_collections() for the base network rendering (same
    pandapower-based renderer plot_single_line_diagram() uses) and only adds the
    classification overlays here. Does not modify net's electrical model --
    only fills in missing net.bus.geo and draws."""
        internal_buses = {int(b) for b in case_metadata.get("detailed_internal_buses", [])}
        boundary_buses = {int(b) for b in case_metadata.get("boundary_buses", [])}
        resolved_mall_bus = int(case_metadata["mall_bus"])
        FeederTopology.compute_hierarchical_layout(net, leaf_step=leaf_step, depth_step=depth_step)
        fig, ax = plt.subplots(figsize=SldPlotter._compute_sld_figsize(net))

        coords = {int(b): SldPlotter._bus_xy(net, b) for b in net.bus.index if pd.notna(net.bus.at[b, "geo"])}
        if not coords:
            raise RuntimeError(f"HyperCAP SLD {case_id}: no bus coordinates available.")

        HyperCapSldPlotter._draw_hypercap_region_patches(ax, coords, internal_buses, boundary_buses)

        def _classify(bus):
            if bus == resolved_mall_bus:
                return SLD_MALL_COLOR
            if bus in internal_buses:
                return "#2ca02c"
            if bus in boundary_buses:
                return "#e69f00"
            return SLD_BUSBAR_COLOR

        # fixed symbol size in layout units; get_collection_sizes() scales
        # with the net's extent and returns absurd values on a large feeder
        bus_size = min(leaf_step, depth_step) * 0.10
        # label_buses=False: HyperCAP draws its own colour-coded bus labels below
        collections = SldPlotter.build_sld_collections(
            net, mall_bus=resolved_mall_bus, bus_color_fn=_classify,
            bus_size=bus_size, label_buses=False)
        pp_plot.draw_collections(collections, ax=ax, figsize=None, plot_colorbars=False,
                                 axes_visible=(False, False))

        HyperCapSldPlotter._draw_hypercap_ward_symbols(ax, net, coords, busbar_half_width=busbar_half_width)
        HyperCapSldPlotter._label_hypercap_buses(ax, coords, internal_buses, boundary_buses)
        HyperCapSldPlotter._draw_hypercap_legend_and_panel(ax, net, case_id, internal_buses, boundary_buses)

        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(f"HyperCAP reduced network — {case_id}", fontsize=15, fontweight="bold", pad=18)
        plt.tight_layout()
        fig.savefig(savepath, dpi=dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return str(savepath)

class HyperCapExporter:
    #: element tables whose p_mw/q_mvar loading is expected to vary case to
    #: case and therefore gets stacked into scaling_loadcases
    LOADCASE_TABLES = ("load", "sgen")

    #: other tables that are supposed to stay IDENTICAL across every merged
    #: net (same topology precondition); a mismatch here means the snapshots
    #: don't actually share one topology and merge_loadcases must not paper
    #: over it
    STRUCTURAL_TABLES = ("bus", "line", "trafo", "load", "sgen")

    #: static columns (per table) that should also stay identical across
    #: cases; if they don't, merging still proceeds (the first net's values
    #: win) but a warning is printed, since a silent difference here (e.g. a
    #: scenario-specific line derate) would otherwise be invisible in the
    #: merged net
    STATIC_WATCH_COLUMNS = {
        "line": ("max_i_ka", "in_service", "length_km"),
        "trafo": ("in_service", "tap_pos"),
        "bus": ("in_service", "vn_kv"),
    }

    @staticmethod
    def _check_structural_equality(nets, loadcase_labels):
        """Raises if any net's bus/line/trafo/load/sgen index set (or order)
        differs from the first net's -- the precondition merge_loadcases
        needs before it's safe to line up p_mw/q_mvar rows across cases."""
        if not nets:
            raise ValueError("merge_loadcases: received an empty list of nets.")

        reference = nets[0]
        ref_label = loadcase_labels[0]

        for table in HyperCapExporter.STRUCTURAL_TABLES:
            if table not in reference or reference[table].empty:
                continue
            ref_index = list(reference[table].index)

            for net, label in zip(nets[1:], loadcase_labels[1:]):
                if table not in net or net[table].empty:
                    raise RuntimeError(
                        f"merge_loadcases: case {label!r} has no '{table}' table/rows, "
                        f"but reference case {ref_label!r} does -- these snapshots do not "
                        f"share one topology.")
                this_index = list(net[table].index)
                if this_index != ref_index:
                    same_set = set(this_index) == set(ref_index)
                    reason = "same elements, different order" if same_set else \
                        f"different elements (missing={sorted(set(ref_index) - set(this_index))}, " \
                        f"extra={sorted(set(this_index) - set(ref_index))})"
                    raise RuntimeError(
                        f"merge_loadcases: '{table}' index mismatch between case {ref_label!r} "
                        f"and case {label!r} ({reason}). merge_loadcases requires every case to "
                        f"be a deep copy of the same net_base -- if this fires, the snapshots "
                        f"passed in don't actually share one topology.")

    @staticmethod
    def _warn_on_static_differences(nets, loadcase_labels):
        """Non-fatal check: warns (does not raise) when a column that is
        supposed to be topology-fixed (e.g. line max_i_ka) actually differs
        between cases -- e.g. because two scenarios applied different
        capacity derates. merge_loadcases keeps the first net's value for
        these columns, so a silent mismatch here would otherwise be lost."""
        reference = nets[0]
        for table, columns in HyperCapExporter.STATIC_WATCH_COLUMNS.items():
            if table not in reference or reference[table].empty:
                continue
            for column in columns:
                if column not in reference[table].columns:
                    continue
                ref_values = reference[table][column]
                for net, label in zip(nets[1:], loadcase_labels[1:]):
                    other_values = net[table][column].reindex(ref_values.index)
                    if ref_values.dtype.kind in "fc":
                        differs = ~np.isclose(ref_values.to_numpy(dtype=float),
                                               other_values.to_numpy(dtype=float),
                                               equal_nan=True)
                    else:
                        differs = (ref_values.to_numpy() != other_values.to_numpy())
                    if differs.any():
                        diff_idx = list(ref_values.index[differs])
                        print(f"[Reinforcement] WARNING: '{table}.{column}' differs between "
                              f"case {loadcase_labels[0]!r} and case {label!r} at index "
                              f"{diff_idx} -- merge_loadcases keeps case {loadcase_labels[0]!r}'s "
                              f"value; if these cases came from scenarios with different derates, "
                              f"reconcile the static ratings before trusting the reinforcement "
                              f"result at these elements.")

    @staticmethod
    def _stack_loadcases(merged_net, nets, table):
        """Adds a 'scaling_loadcases' column to merged_net[table]: one list
        of p_mw values per row, in case order. Adds 'scaling_loadcases_q'
        too, but only if q_mvar actually varies across cases -- otherwise
        the existing q_mvar column already speaks for every case."""
        if table not in merged_net or merged_net[table].empty:
            return

        p_matrix = np.column_stack([net[table]["p_mw"].to_numpy(dtype=float) for net in nets])
        merged_net[table]["scaling_loadcases"] = list(p_matrix)
        # the plain p_mw column is no longer authoritative once there's more
        # than one load case -- keep it populated (mean across cases) only
        # so anything that still reads net.load.p_mw directly gets a sane
        # single-case fallback, not a stale first-hour value
        merged_net[table]["p_mw"] = p_matrix.mean(axis=1)

        if "q_mvar" in merged_net[table].columns:
            q_matrix = np.column_stack([net[table]["q_mvar"].to_numpy(dtype=float) for net in nets])
            if not np.allclose(q_matrix, q_matrix[:, [0]]):
                merged_net[table]["scaling_loadcases_q"] = list(q_matrix)
                merged_net[table]["q_mvar"] = q_matrix.mean(axis=1)

    @staticmethod
    def merge_loadcases(nets, loadcase_labels=None):
        """Merges N structurally-identical pandapower nets (one per violated hour in a scenario) into a single net carrying all N as parallel
        load cases.
        Enforces the precondition that every net shares one topology (same bus/line/trafo/load/sgen indices, same order) -- that's what makes
        stacking p_mw/q_mvar row-by-row across nets valid in the first place. Returns a deep copy of nets[0] with 'scaling_loadcases'
        (and, if it varies, 'scaling_loadcases_q') columns added to its load/sgen tables, plus 'loadcase_labels' / 'n_loadcases' recorded on
        the net itself for traceability back to (scenario, hour).
        """
        nets = list(nets)
        if loadcase_labels is None:
            loadcase_labels = [str(i) for i in range(len(nets))]
        loadcase_labels = list(loadcase_labels)
        if len(loadcase_labels) != len(nets):
            raise ValueError("merge_loadcases: loadcase_labels must be the same length as nets.")

        HyperCapExporter._check_structural_equality(nets, loadcase_labels)
        HyperCapExporter._warn_on_static_differences(nets, loadcase_labels)

        merged_net = copy.deepcopy(nets[0])
        for table in HyperCapExporter.LOADCASE_TABLES:
            HyperCapExporter._stack_loadcases(merged_net, nets, table)

        merged_net["loadcase_labels"] = loadcase_labels
        merged_net["n_loadcases"] = len(nets)

        print(f"[HyperCAP] merged {len(nets)} violated-hour snapshot(s) into one net "
              f"({len(merged_net.bus)} buses, {len(merged_net.line)} lines) with "
              f"scaling_loadcases on load/sgen.")

        return merged_net

    @staticmethod
    def build_hypercap_case_dict(net_base, violation_details_by_case, violated_net_snapshots,
                                      region_by_scenario, phase="after", eq_type="ward",
                                      verbose=True, validate=True):
            """Builds one reduced HyperCAP network per violating (scenario,
            timestamp) snapshot -- same per-hour reduce/validate/metadata shape
            as before. The detailed/boundary bus sets are NO LONGER computed
            here per hour: they come from `region_by_scenario`, one FROZEN
            region per scenario built once by HyperCapReducer.build_scenario_region
            . Runs validate_hypercap_case() against the exact
            pre-reduction snapshot right after each reduction and stores the
            result in that case's metadata under "validation", exactly as
            before."""
    
            del net_base  # retained for API compatibility; snapshots are authoritative
    
            snapshots = HyperCapReducer._snapshot_lookup(violated_net_snapshots)
            case_dict = {}
            case_metadata = {}
    
            ordered_snapshot_keys = sorted(snapshots.keys(), key=lambda key: (str(key[0]), pd.Timestamp(key[1])))
            print(f"[HyperCAP] {len(ordered_snapshot_keys)} violating snapshot(s) to reduce against their "
                  "scenario's frozen region" + (" (validating each against its source)" if validate else ""))
    
            n_failed_validation = 0
            case_iter = (tqdm(ordered_snapshot_keys, desc="HyperCAP export", unit="case")
                         if _HAVE_TQDM else ordered_snapshot_keys)
    
            for scenario, timestamp in case_iter:
                scenario = str(scenario)
                timestamp = pd.Timestamp(timestamp)
                snapshot = copy.deepcopy(snapshots[(scenario, timestamp)])
                case_id = f"{scenario}_{timestamp:%Y%m%d_%H%M}"
    
                if scenario not in region_by_scenario:
                    raise KeyError(f"No precomputed region found for scenario={scenario!r} (case {case_id}).")
                detailed_buses, boundary_buses, per_hour_seed_meta = region_by_scenario[scenario]
    
                hour_key = timestamp.isoformat()
                if hour_key not in per_hour_seed_meta:
                    raise KeyError(
                        f"No seed-bus metadata found for scenario={scenario!r} hour={timestamp} "
                        f"(case {case_id}) -- region and snapshots are out of sync.")
                hour_seed_meta = per_hour_seed_meta[hour_key]
    
                if case_id in case_dict:
                    raise RuntimeError(f"Duplicate HyperCAP case ID: {case_id}.")
    
                reduced = HyperCapReducer.build_reduced_net_for_case(
                    snapshot, boundary_buses=boundary_buses, internal_buses=detailed_buses, eq_type=eq_type)
    
                validation_result = None
                if validate:
                    validation_result = HyperCapReducer.validate_hypercap_case(
                        case_id=case_id, reduced_net=reduced, source_net=snapshot,
                        detailed_internal_buses=detailed_buses, boundary_buses=boundary_buses)
                    if not validation_result["passed"]:
                        n_failed_validation += 1
    
                case_dict[case_id] = reduced
                # [FIX 4] read the mall bus from the mall load itself
                _mall_rows = snapshot.load.index[snapshot.load["name"] == "Shopping Mall load"]
                if len(_mall_rows):
                    resolved_mall_bus = int(snapshot.load.at[_mall_rows[0], "bus"])
                else:
                    resolved_mall_bus, _ = FeederTopology.find_weakest_branch_leaf_bus(snapshot)
                case_metadata[case_id] = {
                    "scenario": scenario,
                    "mall_bus": int(resolved_mall_bus),
                    "time": timestamp.isoformat(),
                    "phase": str(phase),
                    "violation_element_ids": hour_seed_meta["violation_element_ids"],
                    "violation_seed_buses": hour_seed_meta["seed_buses"],
                    "detailed_internal_buses": sorted(detailed_buses),
                    "boundary_buses": sorted(boundary_buses),
                    "source_bus_count": int(len(snapshot.bus)),
                    "reduced_bus_count": int(len(reduced.bus)),
                    "region_frozen_across_hours": True,
                }
                if validation_result is not None:
                    case_metadata[case_id]["validation"] = validation_result
    
                status_tag = ""
                if validation_result is not None:
                    status_tag = " [VALID]" if validation_result["passed"] else " [FAILED VALIDATION]"
    
                summary_line = (f"[HyperCAP] {case_id}: internal={len(detailed_buses)} "
                                 f"boundary={len(boundary_buses)} -> {len(reduced.bus)}/{len(snapshot.bus)} "
                                 f"buses{status_tag}")
                if _HAVE_TQDM and isinstance(case_iter, tqdm):
                    case_iter.write(summary_line)
                else:
                    print(summary_line)
    
            if len(case_dict) != len(ordered_snapshot_keys):
                raise RuntimeError(f"HyperCAP case-count mismatch: {len(ordered_snapshot_keys)} violating snapshots "
                                    f"but {len(case_dict)} reduced networks -- a timestamp was lost or duplicated.")
    
            print(f"[HyperCAP] reduced {len(case_dict)}/{len(ordered_snapshot_keys)} violating snapshot(s)"
                  + (f", {n_failed_validation} failed electrical-equivalence validation" if validate else ""))
    
            return case_dict, case_metadata

    @staticmethod
    def build_hypercap_scenario_case_dict(net_base, violation_details_by_case, violated_net_snapshots,
                                           phase="after", eq_type="ward", verbose=True, validate=True):
        """
        For each scenario: builds ONE frozen Ward-reduction region (union of every hour's violation seed buses in that scenario --
        HyperCapReducer.build_scenario_region), reduces + validates EVERY hour in that scenario against that SAME frozen region (delegated to
        build_hypercap_case_dict, unchanged reduce/validate/metadata shape),then merges the N per-hour reduced nets for that scenario into one
        net via HyperCapExporter.merge_loadcases. Merging is only sound here because every hour in the scenario was reduced
        against the identical boundary/internal bus set, so the N reduced nets are guaranteed structurally identical.

        MEAN-VS-WORST-HOUR CHOICE (documented): merge_loadcases (protected,unchanged) deep-copies nets[0] as the merged net's structural +
        fallback-value (mean p_mw) template. Its *topology/geo/labels* come from whichever net is nets[0] -- so we explicitly order each
        scenario's net list to put the WORST hour (max |violation value|for that scenario/phase) first. This makes the merged net (and any
        SLD rendered from it) represent the worst hour, not an arbitrarychronological pick.

        Returns (case_dict, case_metadata) where
        case_dict = {scenario_label: merged_reduced_net}.
        """
        snapshots = HyperCapReducer._snapshot_lookup(violated_net_snapshots)

        violation_tables = {}
        for scenario, df in violation_details_by_case.items():
            if df is None or df.empty:
                violation_tables[str(scenario)] = pd.DataFrame()
                continue
            required = {"time", "phase", "violation_type", "element_id"}
            missing = required - set(df.columns)
            if missing:
                raise ValueError(f"Scenario {scenario!r} is missing required violation column(s): {sorted(missing)}")
            tmp = df.copy()
            tmp["_hypercap_time"] = pd.to_datetime(tmp["time"], errors="raise", utc=True)
            tmp["_hypercap_phase"] = tmp["phase"].astype(str)
            violation_tables[str(scenario)] = tmp

        hours_by_scenario = {}
        for scenario, timestamp in snapshots.keys():
            hours_by_scenario.setdefault(scenario, []).append(timestamp)
        for scenario in hours_by_scenario:
            hours_by_scenario[scenario] = sorted(hours_by_scenario[scenario])

        ordered_scenarios = sorted(hours_by_scenario.keys())
        print(f"[HyperCAP] Option A: building {len(ordered_scenarios)} frozen scenario region(s) "
              f"(union across {sum(len(h) for h in hours_by_scenario.values())} violating hour(s) total)")

        region_by_scenario = {}
        for scenario in ordered_scenarios:
            violation_table = violation_tables.get(scenario, pd.DataFrame())
            if violation_table.empty:
                raise KeyError(f"No violation-detail table found for scenario={scenario!r}.")
            detailed_buses, boundary_buses, per_hour_seed_meta = HyperCapReducer.build_scenario_region(
                scenario=scenario, ordered_hours=hours_by_scenario[scenario], snapshot_lookup=snapshots,
                violation_table=violation_table, phase=phase, verbose=verbose)
            region_by_scenario[scenario] = (detailed_buses, boundary_buses, per_hour_seed_meta)
            print(f"[HyperCAP] scenario {scenario!r}: frozen region -> "
                  f"internal={len(detailed_buses)} boundary={len(boundary_buses)} "
                  f"(union of {len(hours_by_scenario[scenario])} hour(s))")

        per_hour_case_dict, per_hour_case_metadata = HyperCapExporter.build_hypercap_case_dict(
            net_base=net_base, violation_details_by_case=violation_details_by_case,
            violated_net_snapshots=violated_net_snapshots, region_by_scenario=region_by_scenario,
            phase=phase, eq_type=eq_type, verbose=verbose, validate=validate)

        cases_by_scenario = {}
        for case_id, meta in per_hour_case_metadata.items():
            cases_by_scenario.setdefault(meta["scenario"], []).append(case_id)
        for scenario in cases_by_scenario:
            cases_by_scenario[scenario].sort(key=lambda cid: per_hour_case_metadata[cid]["time"])

        def _worst_hour_case_id(scenario, case_ids, violation_table):
            """Pick the hour with the largest normalized severity (fraction of limit).

            Raw voltage excess is in p.u. while thermal excess is in percentage points;
            normalize both as 100 * abs(excess) / abs(limit) before comparing.
            """
            worst_case_id, worst_score = None, -np.inf
            for cid in case_ids:
                timestamp = pd.to_datetime(per_hour_case_metadata[cid]["time"], utc=True)
                rows = violation_table[(violation_table["_hypercap_time"] == timestamp)
                                        & (violation_table["_hypercap_phase"] == str(phase))]
                if rows.empty:
                    continue
                if "normalized_severity_pct" in rows.columns:
                    scores = pd.to_numeric(rows["normalized_severity_pct"], errors="coerce")
                elif {"excess", "limit"}.issubset(rows.columns):
                    excess = pd.to_numeric(rows["excess"], errors="coerce").abs()
                    limit = pd.to_numeric(rows["limit"], errors="coerce").abs()
                    scores = 100.0 * excess / limit.where(limit > 1e-12)
                else:
                    raise ValueError(
                        f"Cannot rank HyperCAP hour {cid}: normalized severity or excess/limit is missing.")
                score = scores.replace([np.inf, -np.inf], np.nan).max(skipna=True)
                if pd.notna(score) and score > worst_score:
                    worst_score = float(score)
                    worst_case_id = cid
            if worst_case_id is None:
                raise RuntimeError(f"No valid normalized severity found for HyperCAP scenario {scenario!r}.")
            return worst_case_id

        merged_case_dict = {}
        merged_case_metadata = {}
        n_scenario_failed_hours = 0

        for scenario in ordered_scenarios:
            case_ids = cases_by_scenario.get(scenario, [])
            if not case_ids:
                raise RuntimeError(f"HyperCAP scenario {scenario!r} produced no per-hour reduced nets to merge.")

            worst_case_id = _worst_hour_case_id(scenario, case_ids, violation_tables[scenario])
            ordered_case_ids = [worst_case_id] + [cid for cid in case_ids if cid != worst_case_id]

            reduced_nets = [per_hour_case_dict[cid] for cid in ordered_case_ids]
            merged_net = HyperCapExporter.merge_loadcases(reduced_nets, loadcase_labels=ordered_case_ids)
            merged_case_dict[scenario] = merged_net

            detailed_buses, boundary_buses, _ = region_by_scenario[scenario]
            per_hour_meta = {cid: per_hour_case_metadata[cid] for cid in ordered_case_ids}
            n_failed_hours = sum(
                1 for cid in ordered_case_ids
                if not per_hour_case_metadata[cid].get("validation", {}).get("passed", True))
            n_scenario_failed_hours += n_failed_hours

            merged_case_metadata[scenario] = {
                "scenario": scenario,
                "mall_bus": per_hour_case_metadata[worst_case_id]["mall_bus"],
                "phase": str(phase),
                "detailed_internal_buses": sorted(detailed_buses),
                "boundary_buses": sorted(boundary_buses),
                "n_loadcases": len(ordered_case_ids),
                "loadcase_ids": ordered_case_ids,
                "worst_hour_case_id": worst_case_id,
                "reduced_bus_count": int(len(merged_net.bus)),
                "n_hours_failed_validation": n_failed_hours,
                "per_hour": per_hour_meta,
            }
        print(f"[HyperCAP] Option A: merged {len(merged_case_dict)} scenario(s)"
              + (f", {n_scenario_failed_hours} hour(s) across all scenarios failed electrical-equivalence "
                 "validation" if validate else ""))
        return merged_case_dict, merged_case_metadata
    
    @staticmethod
    def export_hypercap_case_slds(case_dict, case_metadata, out_dir="hypercap_slds", dpi=220):
        """Renders one classification-enhanced SLD per reduced HyperCAP case
    (visualization only -- no electrical data is touched)."""
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
 
        sld_paths = {}
        print(f"[HyperCAP SLD] rendering {len(case_dict)} case(s)")
 
        for case_no, (case_id, reduced_net) in enumerate(case_dict.items(), start=1):
            safe_case_id = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(case_id))
            png_path = out_path / f"{case_no:02d}_{safe_case_id}.png"
 
            try:
                generated_path = HyperCapSldPlotter.plot_hypercap_reduced_sld(
                    net=reduced_net, case_id=case_id, case_metadata=case_metadata[case_id],
                    savepath=str(png_path), dpi=dpi)
                sld_paths[str(case_id)] = generated_path
                print(f"[HyperCAP SLD] {case_no:02d}/{len(case_dict):02d}: {case_id} -> {generated_path}")
            except Exception as exc:
                plt.close("all")
                print(f"[HyperCAP SLD] WARNING: could not render {case_id}: {type(exc).__name__}: {exc}")
 
        if len(sld_paths) != len(case_dict):
            print(f"[HyperCAP SLD] WARNING: only {len(sld_paths)}/{len(case_dict)} SLDs rendered")
 
        return sld_paths

    @staticmethod
    def prepare_hypercap_export(net_base, violation_details_by_case, violated_net_snapshots,
                                 fixed_topology=True, eq_type="ward", out_dir="hypercap_cases",
                                 mall_branch_buses=None, phase="after", validate=True):
        """: build ONE frozen Ward-reduction region per scenario, reduce+validate every hour against it, merge the per-hour reduced nets per scenario
        (build_hypercap_scenario_case_dict), then write the resulting scenario-keyed case dict (+ metadata + source snapshots) to disk,
        render SLDs, and warn if any hour failed electrical-equivalence validation. I/O and SLD calls are unchanged from before; only the
        naming shifts from "case_id" (one per hour) to "scenario_label" (one per scenario), matching case_dict's new keys."""

        del fixed_topology
        del mall_branch_buses

        case_dict, case_metadata = HyperCapExporter.build_hypercap_scenario_case_dict(
            net_base=net_base, violation_details_by_case=violation_details_by_case,
            violated_net_snapshots=violated_net_snapshots, phase=phase, eq_type=eq_type,
            verbose=True, validate=validate)

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        cases_path = out / "hypercap_cases.pkl"
        with cases_path.open("wb") as f:
            pickle.dump(dict(case_dict), f, protocol=pickle.HIGHEST_PROTOCOL)

        metadata_path = out / "hypercap_cases_metadata.json"
        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(dict(case_metadata), f, indent=2, default=str)

        normalized_snapshots = {
            (str(scenario), HyperCapReducer._normalize_hypercap_timestamp(timestamp)): net
            for (scenario, timestamp), net in violated_net_snapshots.items()
        }
        snapshots_path = out / "post_mall_snapshots.pkl"
        with snapshots_path.open("wb") as f:
            pickle.dump(normalized_snapshots, f, protocol=pickle.HIGHEST_PROTOCOL)

        print(f"[HyperCAP] wrote {len(case_dict)} merged scenario case(s): {cases_path}")
        print(f"[HyperCAP] wrote case metadata: {metadata_path}")
        print(f"[HyperCAP] wrote {len(normalized_snapshots)} source snapshot(s): {snapshots_path}")

        HyperCapExporter.export_hypercap_case_slds(case_dict=case_dict, case_metadata=case_metadata,
                                   out_dir=out / "slds", dpi=220)

        if validate:
            n_scenarios_with_failed_hours = sum(
                1 for m in case_metadata.values() if m.get("n_hours_failed_validation", 0) > 0)
            if n_scenarios_with_failed_hours:
                print(f"[HyperCAP] WARNING: {n_scenarios_with_failed_hours}/{len(case_dict)} scenario(s) had "
                      f"at least one hour fail electrical-equivalence validation -- see \"per_hour\" in "
                      f"{metadata_path}")

        return case_dict, str(cases_path)

#####   Scenario helpers and main workflow
def _scenario_profile_copy(base_profiles, load_scale, sgen_scale,
                           branch_load_idx=None, branch_load_scale=1.0):
    """Copy profiles and apply scenario factors without mutating the base cache.

    P and Q demand are scaled together. ``branch_load_scale`` is applied only to loads
    downstream of the mall bus, which creates a physically local line-overload scenario
    instead of merely duplicating the system-wide transformer stress case.
    """
    out = {key: frame.copy(deep=True) for key, frame in base_profiles.items()}
    out[("load", "p_mw")] *= float(load_scale)
    out[("load", "q_mvar")] *= float(load_scale)
    out[("sgen", "p_mw")] *= float(sgen_scale)
    if branch_load_idx and float(branch_load_scale) != 1.0:
        valid = [idx for idx in branch_load_idx if idx in out[("load", "p_mw")].columns]
        if valid:
            out[("load", "p_mw")].loc[:, valid] *= float(branch_load_scale)
            out[("load", "q_mvar")].loc[:, valid] *= float(branch_load_scale)
    return out

def _plot_grid_profiles(profiles, idx, scenario_label, output_dir="scenario_outputs"):

    """Plot aggregate P/Q demand, generation and net active demand before evaluation."""
    os.makedirs(output_dir, exist_ok=True)
    load_p = profiles[("load", "p_mw")].sum(axis=1).to_numpy(dtype=float)
    load_q = profiles[("load", "q_mvar")].sum(axis=1).to_numpy(dtype=float)
    generation = profiles[("sgen", "p_mw")].sum(axis=1).to_numpy(dtype=float)
    net_demand = load_p - generation
    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
    axes[0].plot(idx, load_p, label="Aggregate load P (MW)")
    axes[0].plot(idx, generation, label="Aggregate generation P (MW)")
    axes[0].set_ylabel("MW"); axes[0].legend(loc="best")
    axes[1].plot(idx, load_q, label="Aggregate load Q (MVAr)")
    axes[1].set_ylabel("MVAr"); axes[1].legend(loc="best")
    axes[2].plot(idx, net_demand, label="Net demand P = load − generation (MW)")
    axes[2].axhline(0.0, linewidth=0.8)
    axes[2].set_ylabel("MW"); axes[2].set_xlabel("Time"); axes[2].legend(loc="best")
    for ax in axes: ax.grid(True, alpha=0.25)
    fig.suptitle(f"SimBench-shaped grid profiles before evaluation — {scenario_label}")
    fig.tight_layout()
    path = os.path.join(output_dir, f"{scenario_label}_grid_profiles.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path

def _plot_before_after_status_diagnostics(results_df, violation_details_df, scenario_label,
                                         output_dir="scenario_outputs"):
    """Plot before/after voltage and loading indicators available from the hourly runner."""
    os.makedirs(output_dir, exist_ok=True)
    x = results_df.index
    if results_df.empty:
        return None
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    # Whole-network extrema bracket every bus voltage; mall-bus traces show the connection point.
    for col, label in (("v_min_before_pu", "Grid minimum before"),
                       ("v_max_before_pu", "Grid maximum before"),
                       ("v_min_after_pu", "Grid minimum after"),
                       ("v_max_after_pu", "Grid maximum after"),
                       ("mall_bus_vm_pu_before", "Mall bus before"),
                       ("mall_bus_vm_pu_after", "Mall bus after")):
        if col in results_df.columns: axes[0].plot(x, results_df[col], label=label)
    axes[0].axhline(v_min_pu_std, linestyle="--", linewidth=0.8, label="V min limit")
    axes[0].axhline(v_max_pu_std, linestyle="--", linewidth=0.8, label="V max limit")
    axes[0].set_ylabel("Voltage (p.u.)"); axes[0].legend(loc="best", ncol=2); axes[0].grid(True, alpha=.25)
    for col, label in (("mall_feeder_line_loading_before_pct", "Mall feeder before"),
                       ("mall_feeder_line_loading_after_pct", "Mall feeder after"),
                       ("max_line_loading_before_pct", "Grid max line before"),
                       ("max_line_loading_after_pct", "Grid max line after"),
                       ("max_trafo_loading_before_pct", "Grid max transformer before"),
                       ("max_trafo_loading_after_pct", "Grid max transformer after")):
        if col in results_df.columns: axes[1].plot(x, results_df[col], label=label)
    axes[1].axhline(loading_percent_max_std, linestyle="--", linewidth=0.8, label="Loading limit")
    axes[1].set_ylabel("Loading (%)"); axes[1].set_xlabel("Time")
    axes[1].legend(loc="best"); axes[1].grid(True, alpha=.25)
    fig.suptitle(f"Before/after mall flexibility — {scenario_label}")
    fig.tight_layout()
    path = os.path.join(output_dir, f"{scenario_label}_before_after_diagnostics.png")
    fig.savefig(path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return path

def run_scenario_study(grid_codes=None):
    """Active four-scenario workflow; only final-PF residual violations are passed to HyperCAP."""

    global GRID_CODE
    if grid_codes is None: grid_codes = [GRID_CODE]
    if WINDOW_SOURCE not in ("grid", "mall"):
        raise ValueError(f"WINDOW_SOURCE must be 'grid' or 'mall', got {WINDOW_SOURCE!r}.")
    
    ses_data_1h_full, _, mall_export_row, mall_import_row = load_and_scan_ses_data(
        ses_data_file, window_days=WINDOW_DAYS)
    heat_hours = _heat_hours_on_profile_year(heat_data_file)

    all_summaries = []

    for grid_code in grid_codes:
        GRID_CODE = grid_code
        net_template = NetFactory.get_net_template(GRID_CODE)

        base_profiles = GridSource.get_profiles(net_template, GRID_CODE)
        idx = pd.date_range(YEAR_START, periods=len(base_profiles[("load", "p_mw")]), freq="15min")
        base_profiles = {k: f.set_axis(idx).resample("60min").mean() for k, f in base_profiles.items()}
        idx = base_profiles[("load", "p_mw")].index

        weakest_leaf_bus, weakest_line = FeederTopology.find_weakest_branch_leaf_bus(net_template)
        mall_bus = weakest_leaf_bus if MALL_BUS_OVERRIDE is None else int(MALL_BUS_OVERRIDE)

        if mall_bus not in net_template.bus.index:
            raise RuntimeError(f"Mall bus {mall_bus} is not present in {GRID_CODE}.")
        
        _, mall_branch_load_idx, mall_branch_buses = FeederTopology.find_downstream_elements(net_template, mall_bus)
        print(f"\n[{GRID_CODE}] Mall bus {mall_bus}; weakest-branch reference line {weakest_line}.")
        SldPlotter.plot_single_line_diagram(net_template, mall_bus=mall_bus)

        if WINDOW_SOURCE == "grid":
            export_row, import_row, grid_scan_df = scan_grid_windows(
                base_profiles, idx, ses_data_1h_full, heat_hours, window_days=WINDOW_DAYS)
            os.makedirs("scenario_outputs", exist_ok=True)
            grid_scan_df.to_csv(os.path.join(
                "scenario_outputs", f"{GRID_CODE.replace(' ', '_')}_grid_window_scan.csv"), index=False)
        else:
            export_row, import_row = mall_export_row, mall_import_row

        windows = {}
        for kind, row in (("export", export_row), ("import", import_row)):
            ws = pd.Timestamp(row["window_start"])
            we = pd.Timestamp(row["window_end"]) + pd.Timedelta(hours=1)   # exclusive end

            check_window_coverage(f"{kind} window", ws, we, ses_data_1h_full, heat_hours)
            windows[kind] = (ws, we)
            print(f"[{GRID_CODE}] {WINDOW_SOURCE}-based {kind} window: {ws} -> {we} "
                  f"(peak residual {row['residual_peak_export_kw' if kind == 'export' else 'residual_peak_import_kw'] / 1000.0:.3f} MW)")
            
        residual_snapshots = {}
        violation_details_by_case = {}

        for label, cfg in SCENARIO_CONFIGS.items():
            direction = "export" if label == "overvoltage" else "import"
            window_start, window_end = windows[direction]

            profiles = _scenario_profile_copy(
                base_profiles, cfg["load_scale"], cfg["sgen_scale"],
                branch_load_idx=mall_branch_load_idx,
                branch_load_scale=cfg.get("branch_load_scale", 1.0))
            profile_plot = _plot_grid_profiles(profiles, idx, label)

            print(f"\n[scenario:{label}] {cfg['description']} | profile plot: {profile_plot}")

            results, bounds, residual_mall, details, snapshots, element_metrics = ScenarioRunner.run_scenario(
                scenario_label=label, direction=direction, ses_data_1h_full=ses_data_1h_full,
                heat_data_file=heat_data_file, window_start=window_start, window_end=window_end,
                mall_bus=mall_bus, grid_load_scale=1.0, grid_sgen_scale=1.0,
                profiles=profiles, idx=idx, capture_violated_snapshots=True)
            
            
            os.makedirs("scenario_outputs", exist_ok=True)
            results.to_csv(os.path.join("scenario_outputs", f"{label}_hourly_results.csv"), index=True)
            details.to_csv(os.path.join("scenario_outputs", f"{label}_violation_details.csv"), index=False)

            _plot_before_after_status_diagnostics(results, details, label)
            GridViolationMap.build_scenario_maps(net_template, mall_bus, details, results, label)

            status_counts = results["status"].value_counts().to_dict()

            #To review this addition :
                        # --- Dominant violation and whole-network before/after outcomes.
            # This stays in the existing scenario caller to avoid adding a separate helper
            # function/class. Severity is expressed as percent of the applicable limit.
            if not details.empty and {"phase", "time", "violation_type", "element_id", "excess", "limit"}.issubset(details.columns):
                analysis_details = details.copy()
                analysis_details["_time_utc"] = pd.to_datetime(analysis_details["time"], utc=True, errors="coerce")
                _excess = pd.to_numeric(analysis_details["excess"], errors="coerce").abs()
                _limit = pd.to_numeric(analysis_details["limit"], errors="coerce").abs()
                _fallback_severity = (100.0 * _excess / _limit.where(_limit > 1e-12)).replace([np.inf, -np.inf], np.nan)
                if "normalized_severity_pct" in analysis_details.columns:
                    _existing_severity = pd.to_numeric(analysis_details["normalized_severity_pct"], errors="coerce")
                    analysis_details["_severity_pct"] = _existing_severity.fillna(_fallback_severity)
                else:
                    analysis_details["_severity_pct"] = _fallback_severity

                dominant_before = analysis_details[
                    analysis_details["phase"].astype(str).eq("before")
                    & analysis_details["_severity_pct"].notna()
                ].copy()

                if dominant_before.empty:
                    print(f"[{label}] No before-phase violation severity available for dominant-violation plotting.")
                else:
                    dominant_idx = dominant_before["_severity_pct"].idxmax()
                    dominant_type = str(dominant_before.loc[dominant_idx, "violation_type"])
                    worst_time = pd.Timestamp(dominant_before.loc[dominant_idx, "_time_utc"])
                    dominant_severity_pct = float(dominant_before.loc[dominant_idx, "_severity_pct"])

                    # Build before/after severity pairs for each element of the dominant type.
                    # A missing after-row becomes zero only when the after-PF was evaluated.
                    improvement_columns = [
                        "time", "violation_type", "element_id", "location", "status",
                        "severity_before_pct_of_limit", "severity_after_pct_of_limit",
                        "severity_reduction_pct_points", "normalized_improvement_pct", "outcome",
                    ]
                    dominant_rows = analysis_details[
                        analysis_details["violation_type"].astype(str).eq(dominant_type)
                    ].copy()
                    _key = ["_time_utc", "violation_type", "element_id"]
                    _before = dominant_rows[dominant_rows["phase"].astype(str).eq("before")].drop_duplicates(_key, keep="last")
                    _after = dominant_rows[dominant_rows["phase"].astype(str).eq("after")].drop_duplicates(_key, keep="last")
                    _before = _before[_key + ["location", "_severity_pct"]].rename(columns={
                        "location": "location_before", "_severity_pct": "severity_before_pct_of_limit"})
                    _after = _after[_key + ["location", "_severity_pct"]].rename(columns={
                        "location": "location_after", "_severity_pct": "severity_after_pct_of_limit"})
                    _before["_before_present"] = True
                    _after["_after_present"] = True
                    improvement_df = _before.merge(_after, on=_key, how="outer")
                    improvement_df["_before_present"] = improvement_df["_before_present"].fillna(False).astype(bool)
                    improvement_df["_after_present"] = improvement_df["_after_present"].fillna(False).astype(bool)

                    if not results.empty and "status" in results.columns:
                        _result_times = pd.to_datetime(results.index, utc=True, errors="coerce")
                        _status_series = pd.Series(results["status"].astype(str).to_numpy(), index=_result_times)
                        _status_series = _status_series[~_status_series.index.duplicated(keep="last")]
                        _status_by_time = _status_series.to_dict()
                    else:
                        _status_by_time = {}
                    improvement_df["status"] = improvement_df["_time_utc"].map(_status_by_time).fillna(STATUS_NOT_EVALUATED)
                    improvement_df["location"] = improvement_df["location_before"].combine_first(improvement_df["location_after"])

                    _before_severity = pd.to_numeric(improvement_df["severity_before_pct_of_limit"], errors="coerce")
                    _after_severity = pd.to_numeric(improvement_df["severity_after_pct_of_limit"], errors="coerce")
                    _before_severity.loc[~improvement_df["_before_present"]] = 0.0
                    _valid_after_status = improvement_df["status"].isin(
                        [STATUS_RESOLVED, STATUS_STILL_VIOLATING, STATUS_FLEX_INFEASIBLE])
                    _after_missing_but_evaluated = ~improvement_df["_after_present"] & _valid_after_status
                    _after_severity.loc[_after_missing_but_evaluated] = 0.0
                    improvement_df["severity_before_pct_of_limit"] = _before_severity
                    improvement_df["severity_after_pct_of_limit"] = _after_severity
                    improvement_df["severity_reduction_pct_points"] = _before_severity - _after_severity
                    improvement_df["normalized_improvement_pct"] = np.where(
                        (_before_severity > 0) & _before_severity.notna() & _after_severity.notna(),
                        (_before_severity - _after_severity) / _before_severity * 100.0,
                        np.nan,
                    )

                    _outcomes = []
                    for _b, _a, _status in zip(
                            _before_severity, _after_severity, improvement_df["status"]):
                        if _status in {STATUS_PF_FAILED, STATUS_NOT_EVALUATED} or pd.isna(_a) or pd.isna(_b):
                            _outcomes.append("Not evaluated")
                        elif _b <= 0 and _a > 0:
                            _outcomes.append("New violation")
                        elif _b <= 0:
                            _outcomes.append("No baseline violation")
                        elif _a <= 1e-12:
                            _outcomes.append("Resolved")
                        elif _a < _b - 1e-9:
                            _outcomes.append("Improved; still violating")
                        elif _a > _b + 1e-9:
                            _outcomes.append("Worsened")
                        else:
                            _outcomes.append("Unchanged")
                    improvement_df["outcome"] = _outcomes
                    improvement_df["time"] = improvement_df["_time_utc"]
                    improvement_df = improvement_df[improvement_columns].sort_values(
                        ["time", "violation_type", "element_id"]).reset_index(drop=True)
                    improvement_path = os.path.join(
                        "scenario_outputs", f"{label}_normalized_improvement_dominant.csv")
                    improvement_df.to_csv(improvement_path, index=False)

                    # Reconstruct the SLD violation dictionary for the dominant severity hour;
                    # secondary violation classes are retained so they remain visible in amber.
                    _worst_rows = analysis_details[
                        analysis_details["phase"].astype(str).eq("before")
                        & (analysis_details["_time_utc"] == worst_time)
                    ]
                    _violations = {kind: [] for kind in _VIOL_TYPES}
                    for _, _vrow in _worst_rows.iterrows():
                        _kind = str(_vrow["violation_type"])
                        if _kind in _violations:
                            _violations[_kind].append((int(_vrow["element_id"]), float(_vrow["value"])))

                    # Build before/after outcome labels for every monitored bus, line and transformer.
                    _violation_labels, _element_outcomes = SldPlotter.build_element_change_labels(
                        element_metrics, worst_time
                    )
                    outcome_path = os.path.join(
                        "scenario_outputs", f"{label}_network_element_outcomes.csv"
                    )
                    _element_outcomes.to_csv(outcome_path, index=False)

                    # Build the AFTER violation set for the exact same timestamp.
                    _after_rows = analysis_details[
                        analysis_details["phase"].astype(str).eq("after")
                        & (analysis_details["_time_utc"] == worst_time)
                    ]
                    _after_violations = {kind: [] for kind in _VIOL_TYPES}
                    for _, _vrow in _after_rows.iterrows():
                        _kind = str(_vrow["violation_type"])
                        if _kind in _after_violations:
                            _after_violations[_kind].append(
                                (int(_vrow["element_id"]), float(_vrow["value"]))
                            )

                    after_metric_mask = (
                        element_metrics["phase"].astype(str).eq("after")
                        if not element_metrics.empty
                        else pd.Series(dtype=bool)
                    )
                    after_metric_times = pd.to_datetime(
                        element_metrics.loc[after_metric_mask, "time"],
                        utc=True, errors="coerce",
                    ) if not element_metrics.empty else pd.Series(dtype="datetime64[ns, UTC]")
                    after_evaluated = bool((after_metric_times == worst_time).any())

                    plot_path = os.path.join(
                        "scenario_outputs", f"{label}_before_after_sld.png")
                    SldPlotter.plot_before_after_sld(
                        copy.deepcopy(net_template),
                        mall_bus=mall_bus,
                        timestamp=worst_time,
                        before_violations=_violations,
                        after_violations=_after_violations,
                        element_change_labels=_violation_labels,
                        scenario_label=label,
                        savepath=plot_path,
                        dominant_violation_type=dominant_type,
                        dominant_severity_pct=dominant_severity_pct,
                        after_evaluated=after_evaluated,
                    )
                    print(f"[{label}] Whole-network outcome table: {outcome_path}")
                    print(f"[{label}] Dominant violation type: {dominant_type}; "
                          f"peak normalized severity: {dominant_severity_pct:.2f}% of limit at {worst_time}.")
                    print(f"[{label}] Per-element normalized improvement CSV: {improvement_path}")
                    _report_rows = improvement_df[pd.to_datetime(improvement_df["time"], utc=True) == worst_time]
                    if not _report_rows.empty:
                        print(f"[{label}] Dominant-type element improvement at representative hour:")
                        print(_report_rows[["element_id", "location", "severity_before_pct_of_limit",
                                            "severity_after_pct_of_limit", "normalized_improvement_pct", "outcome"]]
                              .to_string(index=False))
            else:
                print(f"[{label}] No violation details available for dominant-violation plotting.")
            ##to review this addition : end

            expected_type = cfg["expected_violation_type"]
            target_details = details[(details.get("phase", pd.Series(dtype=str)) == "before") &
                                     (details.get("violation_type", pd.Series(dtype=str)) == expected_type)] if not details.empty else pd.DataFrame()
            target_event_count = int(len(target_details))
            target_hours = int(target_details["time"].nunique()) if target_event_count and "time" in target_details else 0
            target_detected = target_event_count > 0

            print(f"[scenario:{label}] canonical status counts: {status_counts}")
            print(f"[scenario:{label}] target {expected_type}: "
                  f"{'DETECTED' if target_detected else 'NOT DETECTED'} "
                  f"({target_event_count} violation events across {target_hours} hour(s) before flexibility)")
            all_summaries.append({"scenario": label, "expected_violation_type": expected_type,
                                  "target_violation_detected": target_detected,
                                  "target_violation_events": target_event_count,
                                  "target_violation_hours": target_hours, **status_counts})
            violation_details_by_case[label] = details

            # run_scenario captures a snapshot only after successful final PF and actual-limit check.
            for time_key, snapshot in snapshots.items():
                residual_snapshots[(label, time_key)] = snapshot
            # Keep post-response residual snapshots for HyperCAP. The matched-time
            # before/after SLD above replaces the separate residual SLD image.

        if residual_snapshots:
            print(f"\n[HyperCAP] Exporting {len(residual_snapshots)} confirmed residual-violation snapshots.")
            HyperCapExporter.prepare_hypercap_export(
                net_base=net_template,
                violation_details_by_case=violation_details_by_case,
                violated_net_snapshots=residual_snapshots,
                fixed_topology=True, eq_type="ward",
                out_dir=f"hypercap_cases_{GRID_CODE.replace(' ', '_')}",
                mall_branch_buses=mall_branch_buses)
        else:
            print("[HyperCAP] No confirmed residual violations after final power flow; nothing exported.")
    if all_summaries:
        pd.DataFrame(all_summaries).fillna(0).to_csv("scenario_outputs/scenario_status_summary.csv", index=False)
    return all_summaries

def main(grid_codes=None):
    return run_scenario_study(grid_codes=grid_codes)
if __name__ == "__main__":
    main()