"""
FUNCTION INDEX (with descriptions)

1. Terminal/Environment Setup
 suppress_native_stdout()          : context manager that redirects stdout to devnull,
                                       hiding the HiGHS solver's banner during OPF runs
 _patched_create_empty_network()   : monkeypatches pp.create_empty_network so every new
                                       net gets legacy bus_geodata/line_geodata tables,
                                       since older plotting helpers still expect them

2. SES Data Loading + Window Scanning
 load_full_ses_data()               : reads the SES Excel file, cleans column names and
                                        decimal commas, drops bad rows, resamples to hourly
 scan_ses_windows()                  : slides an N-day window across the data, computing
                                        residual load (consumption - PV) sums/peaks to find
                                        the best import-stress and export-surplus windows
 load_and_scan_ses_data()            : convenience wrapper - loads + scans in one call
 build_time_series_data()            : builds the prosumer's hourly input series from the
                                        heat-demand Excel data, tiling it if too short

3. Mall Prosumer Model Builder
 build_mall_prosumer()               : builds the full prosumer container - creates CHP,
                                        booster heat pump, thermal storage, heat demand,
                                        and optimizer controller, then wires all of them
                                        together via GenericMapping connections; can carry
                                        forward previous controller state/CHP downtime

4. Prosumer Run With Bounds
 run_mall_case_with_bounds()         : runs one prosumer simulation via run_timeseries,
                                        extracts CHP/heat pump/storage/demand results into
                                        a clean DataFrame, and optionally computes the
                                        mall's flexibility bounds (min/base/max grid power)

5. Grid Preparation + OPF
 fix_element_dtypes()                : repairs boolean columns pandas may have broken,
                                        disables tap-dependency tables on transformers
 prepare_grid_for_opf()              : sets voltage/loading limits, ext_grid power bounds,
                                        optional line capacity derating
 run_pf()                            : runs Newton-Raphson power flow with error handling,
                                        returns success/failure
 check_grid_violations()             : scans all buses/lines/trafos for voltage and
                                        loading violations
 element_label()                     : returns a readable name/id for a violated element
 record_violation_details()          : logs violation rows (time, phase, type, location,
                                        value) into a list
 run_mall_opf()                      : sets a quadratic cost objective (penalizing
                                        deviation from baseline power) and solves an OPF
                                        for the mall's optimal power setpoint

6. Feeder Topology Helpers
 find_bus_feeder_line()              : finds the line(s) incident to a given bus
 find_weakest_branch_leaf_bus()      : runs a PF, finds the most-loaded line, then walks
                                        outward along the topology graph to the dead-end
                                        (leaf) bus of that branch - used to auto-place the
                                        mall at the electrically weakest point
 build_feeder_graph()                : builds a switch-respecting NetworkX graph plus
                                        bus-pair -> line/trafo index lookup maps
 root_bus_path()                     : validates connectivity, returns the shortest path
                                        from the ext_grid bus to a target bus
 find_path_lines_to_bus()            : returns line indices lying along that path
 find_path_trafos_to_bus()           : returns trafo indices lying along that path
 find_downstream_elements()          : finds all loads/sgens electrically downstream of a
                                        bus (used to scope calibration to the mall's branch)
 compute_hierarchical_layout()       : computes a tree-style layout for buses missing
                                        geodata, for cleaner single-line diagrams; also
                                        returns a branch-id map for per-branch coloring

7. Net Template + Base Net
 get_net_template()                  : loads and caches a Simbench net template per grid
                                        code, applying dtype fixes and OPF prep once
 build_base_net()                    : deep-copies the cached template, applies optional
                                        line/trafo derating, attaches the controllable
                                        mall load at the target bus

8. Simbench Profile Helpers
 apply_scaled_column()               : writes scaled profile values into a net table
                                        column, optionally scoped to certain elements
 apply_simbench_profile_for_hour()   : applies load/sgen profiles for one specific hour,
                                        with optional scoped scaling
 get_feeder_load_sgen_window()       : sums total feeder load/sgen power over a window
 find_worst_hour_proxy()             : picks the single worst-stress hour in a window,
                                        for either "import" or "export" direction

9. Grid Stress Calibration
 run_pf_metrics()                    : runs PF, packages voltage/loading/violation
                                        metrics into one dict
 attempt_opf_resolution()            : runs the mall OPF, applies its result, reruns PF,
                                        checks whether the violation is resolved
 evaluate_calibration_point()        : builds/tests a net at a given stress "knob" value
                                        (line derate, trafo derate, or load scale), applies
                                        the worst-hour profile, runs PF/OPF, reports status
 bisect_to_first_violation()         : bisects a value range to find the threshold that
                                        first produces a grid violation; raises if the
                                        "stress" bound never actually violates
 calibrate_import_decoupled()        : runs three independent single-axis bisections
                                        (line derate / load scale / trafo derate) to find
                                        standalone violation thresholds for the import case
 print_calibration_spot_check()      : prints a debug summary for a chosen calibration
                                        value (violated? resolved? PF failed?)

10. OPF Results + Closed-Loop Runner
 build_opf_results()                 : assembles one results row per timestep (setpoints,
                                        voltages, loadings, violation counts)
 run_opf_timeseries_for_scenario()   : main hour-by-hour loop - runs the prosumer
                                        baseline, checks grid violations, runs OPF if
                                        needed, applies fallback logic if OPF fails, re-runs
                                        the prosumer with actual dispatch, and logs
                                        everything (SOC/controller state carries across
                                        hours)

11. Plotting + Terminal Summaries
- style_axis()                        : applies consistent labels/legend/grid styling to
                                        a matplotlib axis
 save_and_show_fig()                 : saves and displays a matplotlib figure (SldPlotter
                                        static method; index previously called this
                                        save_and_show())
 _bus_xy()                           : extracts (x, y) coordinates from a bus's geo JSON
 draw_busbar()                       : draws a bus as a short thick segment (SLD style)
 draw_orthogonal_connector()         : draws an elbow (H-V-H) connector between two
                                        busbars instead of a diagonal line
 _violation_bands()                  : merges consecutive violated hours into continuous
                                        (start, end) bands
 _annotate_violation_bands()         : shades violation bands onto a matplotlib axis
 _violation_summary_text()           : builds a short text summary of the worst violations
 print_scenario_summary()            : prints a consolidated terminal summary box per
                                        scenario (violated hours, resolved vs. remaining,
                                        top violated elements, tracking error, SOC range)
 _add_collection_safe()              : safely adds a plotting collection (or tuple/list
                                        of them) to an axis
 plot_single_line_diagram()          : draws the full grid diagram with the mall bus
                                        highlighted
 plot_prosumer_participation()       : plots mall power & feeder loading before/after OPF
 draw_load_sgen_icons()              : manually draws load (arrow) and sgen (circle)
                                        icons attached to each bus
 plot_soc_and_tracking()             : plots storage SOC & setpoint tracking
 plot_scenario_diagnostics()         : wrapper calling both plot functions above

12. HTML Scenario Report
- _fig_to_base64()                    : renders a matplotlib figure to an inline base64 PNG
- _build_participation_chart_fig()    : builds the baseline-vs-actual dispatch + feeder
                                        loading figure used in the HTML report
- _build_soc_tracking_chart_fig()     : builds the SOC + setpoint-tracking figure used in
                                        the HTML report
- build_violation_event_table()       : pivots the flat violation log into one row per
                                        violation event, with before/after values side by
                                        side and a resolved/still-violating status
- build_scenario_html_report()        : assembles the full self-contained HTML report
                                        (headline cards, both diagnostic charts, the
                                        violation event log, and the full hour-by-hour
                                        table) and writes it to disk

13. Scenario Runner
- run_scenario()                      : orchestrates one scenario  builds data, runs sim,
                                        saves CSVs, prints summary, plots diagnostics,
                                        writes the HTML report
- run_for_grid()                      : per-grid workflow - resolves mall bus, calibrates
                                        all stress axes, spot-checks each calibrated
                                        threshold, runs all scenarios

14. HyperCAP Reduced Network Export (incl. load-case merging)
    Freezes ONE Ward-reduction region per SCENARIO (the union of every
    violated hour's seed buses in that scenario), reduces+validates every
    hour in the scenario against that same frozen region, then merges that
    scenario's N per-hour REDUCED nets into a single net carrying all N as
    parallel load cases. So S scenarios produce S merged reduced networks
    -- and each one IS the reinforcement-planning input (small, Ward-
    reduced grids only; there is no separate full-topology merge path).
     All classes below are staticmethod-only namespaces (HyperCapReducer 
     / HyperCapExporter /HyperCapSldPlotter).

    HyperCapReducer (per-hour + per-scenario region helpers):
    - collect_violated_element_ids()      : parses a violation_details_df into per-type
                                            sets of violated element ids (bus / line /
                                            trafo) for one (scenario, timestamp) case
    - violated_elements_to_seed_buses()    : converts violated line/trafo ids into incident
                                            buses and unions with violated bus ids
    - find_boundary_buses()                : any internal (detailed) bus with a neighbor
                                            outside the detailed set becomes a boundary bus
    - normalize_boundary_buses()           : collapses raw boundary buses that pandapower
                                            would treat as one closed-switch group into a
                                            single representative, before get_equivalent()
    - build_reduced_net_for_case()         : calls pandapower's get_equivalent() for one
                                            snapshot, given its detailed/boundary bus sets
                                            (the only place get_equivalent() is called)
    - build_scenario_region()              : NEW vs. the old per-hour design - unions each
                                            hour's violation seed buses across the whole
                                            scenario, expands through switch-closed groups
                                            once, and runs find_boundary_buses() /
                                            normalize_boundary_buses() once per scenario
                                            instead of once per hour, producing ONE frozen
                                            (detailed_buses, boundary_buses, seed_meta)
                                            region that every hour in that scenario reuses
    - validate_hypercap_case()             : electrical-equivalence check for one reduced
                                            case - runs a fresh PF on both the reduced net
                                            and its exact source, compares voltage/angle/
                                            P/Q at internal+boundary buses plus retained
                                            line/trafo loading and ext_grid P/Q against the
                                            HYPERCAP_*_TOLERANCE_* constants; returns a
                                            dict with "passed"/"failed_checks" and never
                                            raises on a failed comparison (only on PF
                                            non-convergence), so one bad hour can't abort
                                            the whole export loop

    HyperCapExporter (per-hour reduction, per-scenario merge, and I/O):
    - LOADCASE_TABLES / STRUCTURAL_TABLES / STATIC_WATCH_COLUMNS
                                            : constants controlling merge_loadcases() below -
                                            which tables get a scaling_loadcases column,
                                            which tables must be structurally identical
                                            across cases, and which static columns get a
                                            non-fatal mismatch warning
    - _check_structural_equality()         : raises if any net's bus/line/trafo/load/sgen
                                            index set or order differs from the first net's
                                            - the precondition merge_loadcases needs before
                                            it's safe to stack p_mw/q_mvar rows across cases
    - _warn_on_static_differences()        : non-fatal - warns if a column that should be
                                            topology-fixed (e.g. line max_i_ka) actually
                                            differs between cases (e.g. different derates)
    - _stack_loadcases()                   : adds a 'scaling_loadcases' column (one p_mw
                                            list per row, in case order) to one table;
                                            also 'scaling_loadcases_q' if q_mvar varies
    - merge_loadcases()                    : merges N structurally-identical reduced nets
                                            (one per violated hour in a scenario) into a
                                            single net carrying all N as parallel load
                                            cases; deep-copies nets[0] as the structural/
                                            geo/label template, so callers order the worst
    - plot_hypercap_reduced_sld()          : draws one reduced network, colored by
                                            internal / boundary / external (Ward) region

15. Main
- main()                              : scans SES data, runs the full workflow for each
                                        grid code

main()                                          [sec 15]
  load_and_scan_ses_data()                      [sec 2]
    load_full_ses_data(), scan_ses_windows()
  run_for_grid()                                 [sec 13]
    get_net_template()                          [sec 7]
    sb.get_absolute_values()                     [external]
    find_weakest_branch_leaf_bus()               [sec 6]
    find_path_lines_to_bus() / find_path_trafos_to_bus()   [sec 6]
    find_downstream_elements()                   [sec 6]
    plot_single_line_diagram()                   [sec 11]
      compute_hierarchical_layout(), draw_busbar(), draw_load_sgen_icons()...
    run_mall_case_with_bounds()                  [sec 4]
      build_mall_prosumer()                      [sec 3]
    find_worst_hour_proxy()                      [sec 8]
    calibrate_import_decoupled()                 [sec 9]
      bisect_to_first_violation()
        evaluate_calibration_point()
          build_base_net()                       [sec 7]
          apply_simbench_profile_for_hour()       [sec 8]
          run_pf_metrics(), attempt_opf_resolution()  [sec 5/9]
    run_scenario()  x2 or x3                      [sec 13]
      run_opf_timeseries_for_scenario()           [sec 10]
        (loops: run_mall_case_with_bounds → run_pf →
         check_grid_violations → run_mall_opf → fallback logic →
         build_opf_results)                        [sec 4, 5, 5, 5, 10]
      print_scenario_summary()                     [sec 11]
      build_scenario_html_report()                 [sec 12]
        _build_participation_chart_fig(), build_violation_event_table()...
    run_for_grid_hypercap_tail()                   [sec 13]
      run_scenario() x2 (captures one violated-net snapshot per residual violation)
      prepare_hypercap_export()                    [sec 14]
        build_hypercap_scenario_case_dict()   -- one MERGED reduced case per scenario
          build_scenario_region()  x per scenario -- ONE frozen region for all its hours
            collect_violated_element_ids(), violated_elements_to_seed_buses()
            find_boundary_buses(), normalize_boundary_buses()
          build_hypercap_case_dict()  -- reduces+validates every hour against its
                                          scenario's frozen region
            build_reduced_net_for_case()  x N hours (calls pp.get_equivalent())
            validate_hypercap_case()  x N hours (if validate=True)
          merge_loadcases()  -- merges each scenario's per-hour reduced nets into
                                 one net, worst-hour-first
            _check_structural_equality(), _warn_on_static_differences()
            _stack_loadcases()  x per table
        export_hypercap_case_slds()
          plot_hypercap_reduced_sld()  x N scenarios
"""


from __future__ import annotations
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
import json as _json
import json as json
import pickle
import traceback
import re
from pandapower.topology import create_nxgraph, connected_component
from pandapower.grid_equivalents.toolbox import get_connected_switch_buses_groups
import importlib
import math
from matplotlib.lines import Line2D
import matplotlib.patches as mpatches

# used by Section 14 (HyperCAP export) for the grid-equivalent reduction
from pandapower.grid_equivalents.get_equivalent import get_equivalent as pp_get_equivalent

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
heat_data_file = project_root / "tutorials_extended" / "data" / "aleja_heat_demand_model_data_2025.xlsx"

GRID_CODE = "1-MV-rural--1-sw"  # urban grids are stiff, so rural grids are preferred for stress-testing  1-MV-rural--1-sw

MALL_BUS = 15  # not hard coded in practice: the mall bus is auto-determined, see find_weakest_branch_leaf_bus()

YEAR_START = pd.Timestamp("2025-01-01 00:15:00")


# Grid violation thresholds
v_min_pu_std = 0.90
v_max_pu_std = 1.10
loading_percent_max_std = 100.0
LOCAL_TZ = "Europe/Berlin"
#SIMULATION_START = pd.Timestamp("2025-01-01 00:00:00")
#SIMULATION_END = pd.Timestamp("2026-01-01 00:00:00")

SIMULATION_START_LOCAL = pd.Timestamp(
    "2025-01-01 00:00:00"
).tz_localize(LOCAL_TZ)

SIMULATION_END_LOCAL = pd.Timestamp(
    "2026-01-01 00:00:00"
).tz_localize(LOCAL_TZ)

SIMULATION_START = SIMULATION_START_LOCAL.tz_convert("UTC")
SIMULATION_END = SIMULATION_END_LOCAL.tz_convert("UTC")
# SLD (single-line diagram) styling knobs
SLD_LEAF_STEP = 2.2     # vertical spacing between sibling leaves (1.4 made the
                        # sgen circle of one row overlap the load arrow of the next)
SLD_DEPTH_STEP = 3.0    # horizontal spacing per tree depth level (was hardcoded 2.0)

# SLD color scheme (industrial single-line-diagram convention)
SLD_BUSBAR_COLOR   = "#000000"   # black - busbars stay black
SLD_MALL_COLOR     = "#d62728"   # red - point of interest
SLD_LINE_COLOR     = "#4d4d4d"   # dark grey - feeders/lines
SLD_LOAD_COLOR     = "#1f4e8c"   # dark blue - load arrows
SLD_SGEN_COLOR     = "#2e8b57"   # sea green - generation (PV/sgen)
SLD_TRAFO_COLOR    = "#555555"   # medium grey - transformer symbol
SLD_EXTGRID_COLOR  = "#000000"   # black hatch - ext grid
SLD_SWITCH_COLOR   = "#d62728"   # red dotted - closed bus-bus switches (previously not drawn at all)
SLD_IMPEDANCE_COLOR = "#9467bd"   # purple dashed - Ward eq_impedance between two boundary buses

# --- SLD symbol sizes, expressed in LAYOUT UNITS ---
# NOT derived from pp_plot.get_collection_sizes(), which scales with the
# geographic extent of the net and returns ~0.5 layout units on a 100-bus
# feeder -> switches/trafos drawn as oversized blobs on top of the busbars.
SLD_SYM_SWITCH   = 0.12   # half-size of the switch square (data units)
SLD_SYM_TRAFO    = 0.34   # trafo circle radius
SLD_SYM_EXTGRID  = 0.38   # ext-grid box size
SLD_SYM_MARKER   = 26     # scatter marker area (pt^2) for gen/storage/shunt/...
SLD_SYM_SWITCH_DIST_MULT = 1.25   # switch offset from the bus, in busbar_half_width

# --- colors of the remaining element types ---
# Module level (they used to be locals inside _draw_sld_base) so that
# _build_sld_legend() can label them with the exact same colors they are
# drawn in. A legend that invents its own colors is worse than no legend.
SLD_OOS_COLOR            = "#a0a0a0"   # out of service
SLD_DCLINE_COLOR         = "#393b79"
SLD_GEN_COLOR            = "#8c564b"   # controllable generator
SLD_STORAGE_COLOR        = "#e377c2"   # storage (the pink "plus" markers)
SLD_SHUNT_COLOR          = "#7f7f7f"
SLD_WARD_COLOR           = "#17becf"
SLD_XWARD_COLOR          = "#bcbd22"
SLD_SVC_COLOR            = "#ff7f0e"
SLD_SSC_COLOR            = "#ff9896"
SLD_TCSC_COLOR           = "#c49c94"
SLD_SWITCH_CLOSED_COLOR  = "#1a1a1a"   # filled square = closed line/trafo switch
SLD_SWITCH_OPEN_EDGE     = "#6e6e6e"   # hollow square = open line/trafo switch
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

#####################################################################################
# 2. SES data loading + best-window scanning
######################################################################################
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

##############################################################################################
# 3. pprosumer model (unchanged from the closed-loop model: previous
# controller results and CHP downtime are carried across timesteps)
#PM: TODO: check if the addition of the el. battery storage would make sense for case when mall flex is insufficient
#################################################################################################

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

##################################################################################################
# 4. pprosumer run with controller-based bounds
##################################################################################################

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

################################################################################################
# 5. pandapower grid preparation + OPF integration
################################################################################################

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

    @staticmethod
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

    @staticmethod
    def record_violation_details(rows_list, hour, phase, violations, net):
        for violation_type, entries in violations.items():
            for element_id, value in entries:
                rows_list.append({
                    "time": hour,
                    "phase": phase,
                    "violation_type": violation_type,
                    "element_id": element_id,
                    "location": GridOps.element_label(net, violation_type, element_id),
                    "value": value,
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

#######################################################################################################
# 6. Feeder topology helpers -- locating the weakest branch, walking from
# the ext_grid to a target bus, and finding elements downstream of a bus
#########################################################################################################

class FeederTopology:
    @staticmethod
    def find_bus_feeder_line(net, bus):
        candidates = net.line.index[(net.line.from_bus == bus) | (net.line.to_bus == bus)]
        if len(candidates) == 0:
            raise RuntimeError(f"No line found incident to bus {bus}.")
        return candidates[0]

    @staticmethod
    def find_weakest_branch_leaf_bus(net):
        """Finds the most electrically stressed line in the network, then walks
    outward from it to the leaf bus (dead end) at the far end of that
    branch. Used to pick where to place the mall for a calibration / worst
    case check (typically where voltage problems are worst)."""

        net_check = copy.deepcopy(net)
        GridOps.fix_element_dtypes(net_check)
        if not GridOps.run_pf(net_check, context="find_weakest_branch_leaf_bus", print_error=False):
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def _find_path_elements_to_bus(net, target_bus, kind, max_segments_from_bus=None):
        graph, line_of_edge, trafo_of_edge = FeederTopology.build_feeder_graph(net)
        _, bus_path = FeederTopology.root_bus_path(net, graph, target_bus, "target_bus")
        lookup = line_of_edge if kind == "line" else trafo_of_edge

        element_idx = [lookup[edge] for edge in zip(bus_path[:-1], bus_path[1:]) if edge in lookup]

        if max_segments_from_bus is not None and len(element_idx) > max_segments_from_bus:
            element_idx = element_idx[-max_segments_from_bus:]

        return element_idx

    @staticmethod
    def find_path_lines_to_bus(net, target_bus, max_segments_from_bus=None):
        return FeederTopology._find_path_elements_to_bus(net, target_bus, "line",
                                           max_segments_from_bus=max_segments_from_bus)

    @staticmethod
    def find_path_trafos_to_bus(net, target_bus):
        """Trafos (if any) sitting on the ext_grid -> target_bus path -- e.g. an
    HV/MV substation trafo or an MV/LV trafo feeding the mall's branch.
    Returns an empty list if the path is all lines, which is common on a
    pure MV feeder where the only trafo sits at the root."""
        return FeederTopology._find_path_elements_to_bus(net, target_bus, "trafo")

    @staticmethod
    def find_downstream_elements(net, mall_bus):
        """Every load and sgen sitting electrically downstream of mall_bus."""
        graph, _, _ = FeederTopology.build_feeder_graph(net)
        _, bus_path = FeederTopology.root_bus_path(net, graph, mall_bus, "mall_bus")

        path_buses = set(bus_path)

        graph_no_backedge = graph.copy()
        if len(bus_path) > 1:
            graph_no_backedge.remove_edge(bus_path[-2], bus_path[-1])

        subtree_buses = nx.node_connected_component(graph_no_backedge, mall_bus)

        downstream_buses = path_buses | subtree_buses

        downstream_sgen_idx = list(
            net.sgen.index[net.sgen["bus"].isin(downstream_buses)]
        )
        downstream_load_idx = list(
            net.load.index[net.load["bus"].isin(downstream_buses)]
        )

        return downstream_sgen_idx, downstream_load_idx, downstream_buses

#PM#2: check why the switches are set to False when build_feeder_graph(net) to create this nx graph sets it to TRUE
    @staticmethod
    def compute_hierarchical_layout(net, leaf_step=SLD_LEAF_STEP, depth_step=SLD_DEPTH_STEP):
        """Fills in net.bus.geo (in place) for any bus missing geo data, using a
    feeder tree layout rooted at the ext_grid bus, and returns a
    {bus: branch_id} map (branch_id=-1 for the root/trunk) so callers can
    color each outgoing branch differently. Returns an empty dict and makes
    no changes to net if every bus already has geo data.

    leaf_step / depth_step control spacing between sibling leaves and
    between depth levels respectively -- increase these if the diagram
    looks cramped."""

        geo = net.bus.geo
        missing_geo = geo.isna() | (geo.astype(str).str.strip() == "") | (geo.astype(str) == "None")
        if not missing_geo.any():
            return {}

        print(f"[plot] {missing_geo.sum()} bus(es) missing geo data -> "
              f"computing hierarchical feeder tree layout (industry SLD style)")

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

        y_counter = [0.0]
        pos = {}

        def assign_y(bus):
            kids = children_by_parent.get(bus, [])
            if not kids:
                y = y_counter[0]
                y_counter[0] += leaf_step
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
                y_counter[0] += leaf_step
                pos[b] = y

        for bus, y in pos.items():
            x = levels[bus] * depth_step
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

##################################################################################################
# 7. Simbench net template + base net with the mall load attached
##############################################################################################

_NET_TEMPLATE_CACHE = {}
class NetFactory:
    @staticmethod
    def get_net_template(grid_code):
        """Caches the Simbench net template per grid_code, since re-loading it
    from Simbench on every scenario/calibration call is expensive."""
        if grid_code not in _NET_TEMPLATE_CACHE:
            net = sb.get_simbench_net(grid_code)
            GridOps.fix_element_dtypes(net)
            GridOps.prepare_grid_for_opf(net, capacity_derate=1.0, derate_line_idx=None)
            _NET_TEMPLATE_CACHE[grid_code] = net
        return copy.deepcopy(_NET_TEMPLATE_CACHE[grid_code])

    @staticmethod
    def build_base_net(mall_bus=MALL_BUS, q_mall_base_mvar=0.0, q_eps=1e-3,
                        capacity_derate=1.0, derate_line_idx=None,
                        capacity_derate_trafo=1.0, derate_trafo_idx=None, grid_code=None):
        grid_code = grid_code or GRID_CODE
        net_base = NetFactory.get_net_template(grid_code)

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

        mall_feeder_line_idx = FeederTopology.find_bus_feeder_line(net_base, mall_bus)

        return net_base, mall_load_idx, mall_feeder_line_idx

#############################################################################################################
# 8. Simbench profile helpers -- reading absolute value profiles and
# deriving stress signals from them (worst hour, per-window feeder totals)
################################################################################################################

class SimbenchProfileSource:
    @staticmethod
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

    @staticmethod
    def apply_simbench_profile_for_hour(net, profiles, idx, hour, load_scale=1.0, sgen_scale=1.0,
                                         scoped_sgen_idx=None, scoped_load_idx=None):
        if idx.tz is not None:
            hour = hour.tz_localize(idx.tz) if hour.tzinfo is None else hour.tz_convert(idx.tz)
        elif hour.tzinfo is not None:
            hour = hour.tz_localize(None)

        step = idx.get_loc(hour)

        SimbenchProfileSource.apply_scaled_column(net, "load", "p_mw", profiles[("load", "p_mw")].iloc[step], load_scale, scoped_load_idx)
        SimbenchProfileSource.apply_scaled_column(net, "load", "q_mvar", profiles[("load", "q_mvar")].iloc[step], load_scale, scoped_load_idx)

        if len(profiles[("sgen", "p_mw")].columns):
            SimbenchProfileSource.apply_scaled_column(net, "sgen", "p_mw", profiles[("sgen", "p_mw")].iloc[step], sgen_scale, scoped_sgen_idx)

    @staticmethod
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

    @staticmethod
    def find_worst_hour_proxy(direction, window_start, window_end, residual_mall_load_kw, load_p_1h, sgen_p_1h):
        hourly_idx, feeder_load_window, feeder_sgen_window = SimbenchProfileSource.get_feeder_load_sgen_window(
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

##################################################################################################################
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
########################################################################################################################

class GridStressCalibration:
    @staticmethod
    def run_pf_metrics(net, context):
        if not GridOps.run_pf(net, context=context, print_error=False):
            return None
        line_load_max = net.res_line["loading_percent"].max() if len(net.res_line) else float("nan")
        trafo_load_max = net.res_trafo["loading_percent"].max() if len(net.res_trafo) else float("nan")
        has_violation, violations = GridOps.check_grid_violations(net)
        return {"vm_min": net.res_bus["vm_pu"].min(), "vm_max": net.res_bus["vm_pu"].max(),
                "line_load_max": line_load_max, "trafo_load_max": trafo_load_max,
                "max_loading_pct": np.nanmax([line_load_max, trafo_load_max]),
                "has_violation": has_violation, "violations": violations}

    @staticmethod
    def attempt_opf_resolution(net, mall_load, p_mall_base_mw, context):
        """Runs the mall OPF, applies its result, re-runs PF, and reports
    whether the violation is resolved."""
        p_opf_mw = GridOps.run_mall_opf(net, mall_load, p_mall_base_mw)
        if p_opf_mw is None:
            return False
        net.load.at[mall_load, "p_mw"] = p_opf_mw
        if not GridOps.run_pf(net, context=context + " after OPF", print_error=False):
            return False
        has_violation_after, _ = GridOps.check_grid_violations(net)
        return not has_violation_after

    @staticmethod
    def _build_calibration_net(mode, mall_bus, value, derate_line_idx=None,
                                derate_trafo_idx=None, q_eps=IMPORT_Q_EPS_MVAR):
        if mode == "derate":
            return NetFactory.build_base_net(mall_bus=mall_bus, capacity_derate=value,
                                   derate_line_idx=derate_line_idx, q_eps=q_eps)
        elif mode == "derate_trafo":
            return NetFactory.build_base_net(mall_bus=mall_bus, capacity_derate_trafo=value,
                                   derate_trafo_idx=derate_trafo_idx, q_eps=q_eps)
        elif mode == "scale":
            return NetFactory.build_base_net(mall_bus=mall_bus, q_eps=q_eps)
        else:
            raise ValueError("mode must be 'derate', 'derate_trafo', or 'scale'")
    
    @staticmethod
    def evaluate_calibration_point(direction, worst_hour, bounds_df, mall_bus, profiles, idx,
                                    mode, value, derate_line_idx=None, derate_trafo_idx=None,
                                    scoped_sgen_idx=None, scoped_load_idx=None,
                                    verbose_debug=VERBOSE_CALIBRATION_DEBUG,
                                    return_net=False):
        if worst_hour not in bounds_df.index:
            raise RuntimeError(f"Worst hour {worst_hour} not found in prosumer bounds_df.")

        p_mall_min_mw = bounds_df.at[worst_hour, "p_mall_min_mw"]
        p_mall_base_mw = bounds_df.at[worst_hour, "p_mall_base_mw"]
        p_mall_max_mw = bounds_df.at[worst_hour, "p_mall_max_mw"]

        q_eps = IMPORT_Q_EPS_MVAR

        if mode == "scale" and direction != "import":
            raise ValueError(
                "direction must be 'import': export-direction ('scale' mode with "
                "sgen scaling) calibration was removed along with the rest of Case 2.")

        net_base, mall_load, _ = GridStressCalibration._build_calibration_net(
            mode, mall_bus, value, derate_line_idx=derate_line_idx,
            derate_trafo_idx=derate_trafo_idx, q_eps=q_eps)
        net = copy.deepcopy(net_base)

        load_scale = value if mode == "scale" else 1.0
        this_scoped_load_idx = scoped_load_idx if mode == "scale" else None
        SimbenchProfileSource.apply_simbench_profile_for_hour(
            net, profiles, idx, worst_hour,
            load_scale=load_scale, sgen_scale=1.0,
            scoped_sgen_idx=None, scoped_load_idx=this_scoped_load_idx)

        net.load.at[mall_load, "p_mw"] = p_mall_base_mw
        net.load.at[mall_load, "min_p_mw"] = p_mall_min_mw
        net.load.at[mall_load, "max_p_mw"] = p_mall_max_mw

        context = f"calibration ({direction}, {mode}={value})"
        metrics = GridStressCalibration.run_pf_metrics(net, context=context)
        if metrics is None:
            result = {"value": value, "violated": False, "resolved": False, "pf_failed": True,
                      "max_loading_pct": np.nan, "v_min_pu": np.nan, "v_max_pu": np.nan}
            if return_net:
                result["net_before"] = None
                result["net_after"] = None
            return result

        if verbose_debug:
            print(f"    [calib debug] {mode}={value}: vm_pu min={metrics['vm_min']:.4f} max={metrics['vm_max']:.4f} "
                  f"(limits {v_min_pu_std:.3f}-{v_max_pu_std:.3f}), "
                  f"line loading max={metrics['line_load_max']:.1f}% trafo loading max={metrics['trafo_load_max']:.1f}% "
                  f"(limit {loading_percent_max_std}%)")

        if not metrics["has_violation"]:
            result = {"value": value, "violated": False, "resolved": False, "pf_failed": False,
                      "max_loading_pct": metrics["max_loading_pct"], "v_min_pu": metrics["vm_min"], "v_max_pu": metrics["vm_max"]}
            if return_net:
                ### no violation means "before" == "after" (nothing to fix)
                net_snapshot = copy.deepcopy(net)
                result["net_before"] = net_snapshot
                result["net_after"] = net_snapshot
            return result

        ### capture the violated state before attempt_opf_resolution mutates net
        net_before = copy.deepcopy(net) if return_net else None

        resolved = GridStressCalibration.attempt_opf_resolution(net, mall_load, p_mall_base_mw, context=context)

        result = {"value": value, "violated": True, "resolved": resolved, "pf_failed": False,
                  "max_loading_pct": metrics["max_loading_pct"], "v_min_pu": metrics["vm_min"], "v_max_pu": metrics["vm_max"]}
        if return_net:
            result["net_before"] = net_before
            result["net_after"] = net  # mutated in place by attempt_opf_resolution
        return result

    @staticmethod
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

    @staticmethod
    def calibrate_import_decoupled(worst_hour_imp, bounds_df_imp, mall_bus, profiles, idx,
                                    derate_line_idx, scoped_load_idx, derate_trafo_idx=None,
                                    derate_bounds=CALIBRATION_DERATE_BOUNDS,
                                    load_scale_bounds=CALIBRATION_UV_LOAD_SCALE_BOUNDS,
                                    trafo_derate_bounds=CALIBRATION_DERATE_BOUNDS,
                                    iters=BISECTION_ITERS, raise_on_unbracketed=True):

        axis_configs = [
            ("derate_only", "derate", derate_bounds,
             dict(derate_line_idx=derate_line_idx), True),
            ("load_scale_only", "scale", load_scale_bounds,
             dict(scoped_load_idx=scoped_load_idx), True),
        ]
        if derate_trafo_idx:
            axis_configs.append(
                ("trafo_derate_only", "derate_trafo", trafo_derate_bounds,
                 dict(derate_trafo_idx=derate_trafo_idx), False))
        else:
            print("[CASE 1] No trafo sits on the mall's ext_grid-to-bus path -- "
                  "skipping trafo-overload calibration axis.")

        results = {"trafo_derate_only": (None, pd.DataFrame())}

        for key, mode, bounds, extra_kwargs, required in axis_configs:
            def evaluate(value, mode=mode, extra_kwargs=extra_kwargs):
                return GridStressCalibration.evaluate_calibration_point(
                    "import", worst_hour_imp, bounds_df_imp, mall_bus, profiles, idx,
                    mode=mode, value=value, **extra_kwargs)
            try:
                threshold, log = GridStressCalibration.bisect_to_first_violation(
                    evaluate, bounds=bounds, iters=iters,
                    raise_on_unbracketed=raise_on_unbracketed)
            except RuntimeError as exc:
                if required:
                    raise
                print(f"[CASE 1] {key} axis not binding within bounds {bounds} at "
                      f"worst_hour_imp={worst_hour_imp} ({exc}) -- treating as "
                      "non-binding for this mall_bus/grid_code, skipping.")
                threshold, log = None, pd.DataFrame()
            results[key] = (threshold, log)

        derate_threshold = results["derate_only"][0]
        load_scale_threshold = results["load_scale_only"][0]
        trafo_derate_threshold = results["trafo_derate_only"][0]

        print(f"[CASE 1] derate only threshold = {derate_threshold:.4f} "
              f"(bounds {derate_bounds}); load_scale-only threshold = "
              f"{load_scale_threshold:.4f} (bounds {load_scale_bounds})"
              + (f"; trafo_derate-only threshold = {trafo_derate_threshold:.4f} "
                 f"(bounds {trafo_derate_bounds})" if trafo_derate_threshold is not None else
                 "; trafo_derate-only: not binding (skipped)"))

        return results

    @staticmethod
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

#####################################################################################################################
# 10. OPF results row + closed-loop scenario runner
#####################################################################################################################
#PM#1: check why the plot stors only mall_feeder_line_loading_before_pct(after_pct), this should plot the overloads on all net.res_line
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

    @staticmethod
    def run_opf_timeseries_for_scenario(scenario_label, direction, net_base, mall_load, mall_feeder_line_idx,
                                        profiles, idx, time_series_data_base, residual_mall_load_kw,
                                        grid_load_scale, grid_sgen_scale,
                                        q_mall_base_mvar, q_eps, initial_soc=0.0,
                                        scoped_sgen_idx=None, scoped_load_idx=None,
                                        capture_violated_snapshots=False):
        updated_flex_target_kw = np.zeros(len(time_series_data_base))
        opf_rows = []
        res_base_rows = []
        res_actual_rows = []
        flex_bounds_rows = []
        violation_detail_rows = []

        # ================================================================
        # HYPERCAP CHANGE:
        # This dictionary now stores ONLY the final residual violating
        # network state (after Mall flexibility / actual dispatch / PF).
        #
        # One (scenario, timestamp) residual violation -> one snapshot.
        # ================================================================
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

            SimbenchProfileSource.apply_simbench_profile_for_hour(
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

                has_violation_before, violations_before = GridOps.check_grid_violations(net)

                if has_violation_before:
                    GridOps.record_violation_details(
                        violation_detail_rows,
                        selected_time,
                        "before",
                        violations_before,
                        net
                    )

                    # ====================================================
                    # HYPERCAP CHANGE:
                    # DO NOT capture the snapshot here.
                    #
                    # This is the pre-Mall-flexibility violated state.
                    # HyperCAP needs the final state AFTER Mall flexibility
                    # and the final PF.
                    # ====================================================

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
                        verbose=False)

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

                        has_violation_after, violations_after = (
                            GridOps.check_grid_violations(net)
                        )

                        if has_violation_after:
                            GridOps.record_violation_details(
                                violation_detail_rows,
                                selected_time,
                                "after",
                                violations_after,
                                net
                            )

                            # =================================================
                            # HYPERCAP ADDITION:
                            # Capture the FINAL network state ONLY when the
                            # violation still exists after Mall flexibility,
                            # actual dispatch, and the final PF.
                            #
                            # This does NOT change the electrical simulation.
                            # It only makes a deep copy for Section 14.
                            #
                            # One residual violating timestamp ->
                            # one independent HyperCAP input network.
                            # =================================================
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
                "value"
            ]
        )

        return (
            opf_results_df,
            updated_flex_target_kw,
            res_base,
            res_actual,
            bounds_df,
            violation_details_df,
            violated_net_snapshots
        )

##############################################################################################################################
# 11. Plotting + terminal summaries
##############################################################################################################################

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
        fig.savefig(filename)
        plt.show()

    @staticmethod
    def _bus_xy(net, bus):
        coords = _json.loads(net.bus.at[bus, "geo"])["coordinates"]
        return coords[0], coords[1]

    @staticmethod
    def draw_busbar(ax, x, y, half_length=0.35, color="black", linewidth=4, zorder=3, orientation="vertical"):
        """Draws one bus as a short thick segment (PowerFactory/PSS-E style)
    instead of a point-circle. orientation='vertical' is the standard SLD
    convention; 'horizontal' is kept as an option but not used by default."""
        if orientation == "vertical":
            ax.plot([x, x], [y - half_length, y + half_length], color=color, linewidth=linewidth,
                    solid_capstyle="butt", zorder=zorder)
        else:
            ax.plot([x - half_length, x + half_length], [y, y], color=color, linewidth=linewidth,
                    solid_capstyle="butt", zorder=zorder)


    @staticmethod
    def draw_orthogonal_connector(ax, xy_from, xy_to, color="grey", linewidth=1.3, zorder=1,
                                half_width=0.35, linestyle="solid"):
        x0, y0 = xy_from
        x1, y1 = xy_to
        if abs(x1 - x0) < 1e-9:
            ax.plot([x0, x1], [y0, y1], color=color, linewidth=linewidth, zorder=zorder, linestyle=linestyle)
            return
        jog_x = x0 + (x1 - x0) / 2.0
        xs = [x0, jog_x, jog_x, x1]
        ys = [y0, y0, y1, y1]
        ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=zorder, linestyle=linestyle)

    @staticmethod
    def _switch_anchor(net, bus, other_bus, distance):
        """Point `distance` away from `bus` along the FIRST segment of the
    route that draw_orthogonal_connector() actually draws (horizontal out
    of the bus, unless both buses share an x, in which case vertical).

    This is the fix for switches that appeared to float in mid-air: they
    were placed on the straight chord between the two buses, which is not
    where the line is drawn."""
        x0, y0 = SldPlotter._bus_xy(net, bus)
        x1, y1 = SldPlotter._bus_xy(net, other_bus)
        if abs(x1 - x0) < 1e-9:
            return x0, y0 + (distance if y1 >= y0 else -distance)
        return x0 + (distance if x1 > x0 else -distance), y0

    @staticmethod
    def _draw_switch_square(ax, x, y, closed, size=SLD_SYM_SWITCH,
                             closed_color=SLD_SWITCH_CLOSED_COLOR,
                             open_edge=SLD_SWITCH_OPEN_EDGE, zorder=7):
        """Axis-aligned square on the route: filled = closed, hollow = open.
    Drawn as a data-coordinate Rectangle (not a scatter marker) so it keeps
    its size relative to the busbars at any figure size or dpi."""
        ax.add_patch(mpatches.Rectangle(
            (x - size, y - size), 2 * size, 2 * size,
            facecolor=(closed_color if closed else "white"),
            edgecolor=(closed_color if closed else open_edge),
            linewidth=1.1, zorder=zorder))

    @staticmethod
    def _violation_bands(violation_details_df, phase="after"):
        """Merges consecutive violated hours into continuous (start, end) bands
    instead of one shape per hour, so the shaded region actually shows
    how long a violation lasted."""
        if violation_details_df is None or violation_details_df.empty:
            return []
        times = sorted(pd.to_datetime(
            violation_details_df.loc[violation_details_df["phase"] == phase, "time"]).unique())
        if not len(times):
            return []
        step = pd.Timedelta(hours=1)
        bands = []
        band_start = prev = times[0]
        for t in times[1:]:
            if t - prev > step:
                bands.append((band_start, prev + step))
                band_start = t
            prev = t
        bands.append((band_start, prev + step))
        return bands

    @staticmethod
    def _annotate_violation_bands(ax, violation_details_df, phase="after", color="tab:red", alpha=0.12):
        bands = SldPlotter._violation_bands(violation_details_df, phase=phase)
        for start, end in bands:
            ax.axvspan(start, end, color=color, alpha=alpha, zorder=0)
        return bands

    @staticmethod
    def _violation_summary_text(violation_details_df, phase="after", top_n=3):
        if violation_details_df is None or violation_details_df.empty:
            return None
        sub = violation_details_df[violation_details_df["phase"] == phase]
        if sub.empty:
            return None
        worst = (sub.sort_values("value", ascending=False)
                  .drop_duplicates(subset=["violation_type", "location"])
                  .head(top_n))
        lines = [f"{row['time']:%m-%d %H:%M} {row['violation_type']} @ {row['location']} "
                 f"(worst={row['value']:.1f})" for _, row in worst.iterrows()]
        return "Worst violations:\n" + "\n".join(lines)

    @staticmethod
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

    @staticmethod
    def _add_collection_safe(ax, coll):
        """Some pandapower create_*_collection() calls return a single
    Collection, others return a tuple/list of them (e.g. load, sgen, trafo
    can all do this depending on version/symbol style). This adds whichever
    it is and returns the first actual Collection object found, for use as
    a legend handle."""
        if coll is None:
            return None
        if isinstance(coll, (tuple, list)):
            first = None
            for c in coll:
                if c is None:
                    continue
                ax.add_collection(c)
                if first is None:
                    first = c
            return first
        else:
            ax.add_collection(coll)
            return coll

    @staticmethod
    def plot_prosumer_participation(opf_results_df, scenario_label, violation_details_df=None):
        fig = ScenarioHtmlReport._build_participation_chart_fig(opf_results_df, scenario_label,
                                              violation_details_df=violation_details_df)
        SldPlotter.save_and_show_fig(fig, f"prosumer_grid_participation_{scenario_label}.png")

    @staticmethod
    def plot_single_line_diagram(net, mall_bus=MALL_BUS, savepath="grid_single_line_diagram.png", title=None,
                                  leaf_step=SLD_LEAF_STEP, depth_step=SLD_DEPTH_STEP, busbar_half_width=0.35):
        if mall_bus in net.bus.index:
            mall_lines = net.line[(net.line.from_bus == mall_bus) | (net.line.to_bus == mall_bus)]
            print(f"\n[mall connection] bus {mall_bus} connects via {len(mall_lines)} line(s):")
            for li, row in mall_lines.iterrows():
                other = row["to_bus"] if row["from_bus"] == mall_bus else row["from_bus"]
                print(f"    line {li} ('{row.get('name', '')}') <-> bus {other}")
            mall_trafos = net.trafo[(net.trafo.hv_bus == mall_bus) | (net.trafo.lv_bus == mall_bus)]
            if len(mall_trafos):
                print(f"    also directly on {len(mall_trafos)} trafo(s): {list(mall_trafos.index)}")
 
        FeederTopology.compute_hierarchical_layout(net, leaf_step=leaf_step, depth_step=depth_step)
        # fixed symbol size in layout units; get_collection_sizes() scales
        # with the net's extent and returns absurd values on a large feeder
        bus_size = min(leaf_step, depth_step) * 0.10
 
        fig_w, fig_h = SldPlotter._compute_sld_figsize(net)
 
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
 
        SldPlotter._draw_sld_base(ax, net, bus_size, busbar_half_width=busbar_half_width, mall_bus=mall_bus)
 
        ax.autoscale_view()
        ax.set_aspect("equal")
        ax.axis("off")
 
        for bus_idx in net.bus.index:
            geo_str = net.bus.at[bus_idx, "geo"]
            if pd.isna(geo_str):
                continue
            coords = _json.loads(geo_str)["coordinates"]
            ax.annotate(str(bus_idx), xy=(coords[0], coords[1]), xytext=(-7, -10),
                        textcoords="offset points", fontsize=7, color="#333333",
                        fontweight="bold", zorder=20, clip_on=False,
                        ha="right", va="top",
                        bbox=dict(boxstyle="round,pad=0.12", facecolor="white",
                                  edgecolor="none", alpha=0.75))
 
        SldPlotter._build_sld_legend(ax, net=net)
        ax.set_title(title or f"{GRID_CODE} -- mall connected directly at bus {mall_bus} (red busbar)")
        plt.tight_layout()
        # reserve room below the axes for the legend that now sits there, so it
        # is not clipped in the interactive window (savefig's bbox_inches=
        # "tight" already takes care of the PNG)
        fig.subplots_adjust(bottom=0.14)
        plt.savefig(savepath, dpi=130, bbox_inches="tight")
        plt.show()
        return ax

    @staticmethod
    def _compute_sld_figsize(net, min_w=18, min_h=11):
        max_x, max_y, min_y = 0.0, 0.0, 0.0
        geo_seen = False
        for bus_idx in net.bus.index:
            geo_str = net.bus.at[bus_idx, "geo"]
            if pd.isna(geo_str):
                continue
            coords = _json.loads(geo_str)["coordinates"]
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
                           net=None):
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
            Line2D([0], [0], color=SLD_LINE_COLOR, linewidth=1.3, label="Line (orthogonal routing)"),
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
        if outside:
            # park it below the axes so it never covers a feeder; the
            # bbox_inches="tight" in savefig keeps it in the exported PNG
            ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.01),
                      ncol=ncol, borderaxespad=0.0, **legend_kwargs)
        else:
            ax.legend(loc=loc, ncol=1, **legend_kwargs)


    @staticmethod
    def _draw_sld_base(ax, net, bus_size, busbar_half_width=0.35, bus_color_fn=None,
                        mall_bus=None, load_color=SLD_LOAD_COLOR, sgen_color=SLD_SGEN_COLOR,
                        line_color=SLD_LINE_COLOR, trafo_color=SLD_TRAFO_COLOR, logger=None):
        """Draws every populated element table in `net`, or logs it as not
        rendered. Out-of-service elements are drawn dashed/grey instead of
        being omitted or drawn identically to in-service elements.
        `logger`: optional logging.Logger; falls back to print() if None.
        """

        def _log(msg, level="warning"):
            if logger is not None:
                getattr(logger, level, logger.warning)(msg)
            else:
                print(f"[_draw_sld_base:{level}] {msg}")

        OOS_COLOR = SLD_OOS_COLOR
        OOS_DASH = (0, (4, 3))
        DCLINE_COLOR = SLD_DCLINE_COLOR
        GEN_COLOR = SLD_GEN_COLOR
        STORAGE_COLOR = SLD_STORAGE_COLOR
        SHUNT_COLOR = SLD_SHUNT_COLOR
        WARD_COLOR = SLD_WARD_COLOR
        XWARD_COLOR = SLD_XWARD_COLOR
        SVC_COLOR = SLD_SVC_COLOR
        SSC_COLOR = SLD_SSC_COLOR
        TCSC_COLOR = SLD_TCSC_COLOR

        rendered_tables = set()

        if bus_color_fn is None:
            def bus_color_fn(bus):
                return (SLD_MALL_COLOR, 5.0, 1.6) if bus == mall_bus else (SLD_BUSBAR_COLOR, 3.0, 1.0)

        def _has_geo(bus):
            return not pd.isna(net.bus.at[bus, "geo"])

        # ---- lines: bug A fixed (single loop), bug C fixed (in_service style) ----
        if len(net.line):
            for li, row in net.line.iterrows():
                from_bus, to_bus = int(row["from_bus"]), int(row["to_bus"])
                if not (_has_geo(from_bus) and _has_geo(to_bus)):
                    continue
                in_service = bool(row.get("in_service", True))
                style = (dict(color=line_color, linewidth=1.35, linestyle="solid") if in_service
                        else dict(color=OOS_COLOR, linewidth=1.1, linestyle=OOS_DASH))
                SldPlotter.draw_orthogonal_connector(
                    ax, SldPlotter._bus_xy(net, from_bus), SldPlotter._bus_xy(net, to_bus),
                    zorder=2, half_width=busbar_half_width, **style)
            rendered_tables.add("line")

        # ---- dcline (previously never drawn) ----
        if "dcline" in net and len(net.dcline):
            for di, row in net.dcline.iterrows():
                from_bus, to_bus = int(row["from_bus"]), int(row["to_bus"])
                if not (_has_geo(from_bus) and _has_geo(to_bus)):
                    continue
                in_service = bool(row.get("in_service", True))
                style = (dict(color=DCLINE_COLOR, linewidth=1.35, linestyle="solid") if in_service
                        else dict(color=OOS_COLOR, linewidth=1.1, linestyle=OOS_DASH))
                SldPlotter.draw_orthogonal_connector(
                    ax, SldPlotter._bus_xy(net, from_bus), SldPlotter._bus_xy(net, to_bus),
                    zorder=2, half_width=busbar_half_width, **style)
            rendered_tables.add("dcline")

        # ---- switches ----
        if len(net.switch):
            # bus-bus: closed AND open still both drawn -- a bus-bus switch IS
            # the only connector between those two buses (unlike line/trafo
            # switches, which sit on top of a connector/symbol that's drawn
            # independently elsewhere), so filtering these to open-only would
            # visually disconnect closed bus-bus pairs. Left unchanged.
            bb = net.switch[net.switch["et"] == "b"]
            for si, row in bb.iterrows():
                bus_a, bus_b = int(row["bus"]), int(row["element"])
                if not (_has_geo(bus_a) and _has_geo(bus_b)):
                    continue
                closed = bool(row["closed"])
                style = (dict(color=SLD_SWITCH_COLOR, linewidth=1.1, linestyle="solid") if closed
                        else dict(color=OOS_COLOR, linewidth=1.0, linestyle=(0, (2, 2))))
                SldPlotter.draw_orthogonal_connector(
                    ax, SldPlotter._bus_xy(net, bus_a), SldPlotter._bus_xy(net, bus_b),
                    zorder=2, half_width=busbar_half_width, **style)
            rendered_tables.add("switch")

            # bus-line / bus-trafo switches.
            # Only OPEN switches are drawn as markers here -- their connector
            # (the line itself, or the trafo circle) is drawn unconditionally
            # in the sections above/below regardless of switch state, so
            # dropping the closed-switch markers only removes clutter; it
            # cannot disconnect anything.
            le = net.switch[net.switch["et"].isin(["l", "t"])]
            l_sw = le[(le["et"] == "l") & (~le["closed"])]
            t_sw = le[(le["et"] == "t") & (~le["closed"])]

            sw_dist = busbar_half_width * SLD_SYM_SWITCH_DIST_MULT
            _sw_taken = {}

            def _switch_xy(bus, other_bus):
                """Anchor on the route, nudged perpendicular if another switch
            already occupies that exact spot (e.g. two lines leaving the
            same bus in the same direction)."""
                x, y = SldPlotter._switch_anchor(net, bus, other_bus, sw_dist)
                key = (round(x, 3), round(y, 3))
                slot = _sw_taken.get(key, 0)
                _sw_taken[key] = slot + 1
                return x, y + slot * SLD_SYM_SWITCH * 2.6

            for si, row in l_sw.iterrows():
                bus, li = int(row["bus"]), int(row["element"])
                if li not in net.line.index or not _has_geo(bus):
                    continue
                line_row = net.line.loc[li]
                other = int(line_row["to_bus"] if int(line_row["from_bus"]) == bus
                            else line_row["from_bus"])
                if not _has_geo(other):
                    continue
                x, y = _switch_xy(bus, other)
                SldPlotter._draw_switch_square(ax, x, y, False)

            for si, row in t_sw.iterrows():
                bus, ti = int(row["bus"]), int(row["element"])
                if ti not in net.trafo.index or not _has_geo(bus):
                    continue
                trafo_row = net.trafo.loc[ti]
                other = int(trafo_row["lv_bus"] if int(trafo_row["hv_bus"]) == bus
                            else trafo_row["hv_bus"])
                if not _has_geo(other):
                    continue
                x, y = _switch_xy(bus, other)
                SldPlotter._draw_switch_square(ax, x, y, False,
                                                closed_color=trafo_color)

        # ---- impedance (this is one is ward impedance: may read on the internet or documentation) ----
        if "impedance" in net and len(net.impedance):
            for ii, row in net.impedance.iterrows():
                bus_a, bus_b = int(row["from_bus"]), int(row["to_bus"])
                if not (_has_geo(bus_a) and _has_geo(bus_b)):
                    continue
                in_service = bool(row.get("in_service", True))
                style = (dict(color=SLD_IMPEDANCE_COLOR, linewidth=1.1, linestyle="solid") if in_service
                        else dict(color=OOS_COLOR, linewidth=1.0, linestyle=OOS_DASH))
                SldPlotter.draw_orthogonal_connector(
                    ax, SldPlotter._bus_xy(net, bus_a), SldPlotter._bus_xy(net, bus_b),
                    zorder=2, half_width=busbar_half_width, **style)
            rendered_tables.add("impedance")

        # ---- tcsc: series FACTS device, from_bus/to_bus (not a single "bus") ----
        if "tcsc" in net and len(net.tcsc):
            for _, row in net.tcsc.iterrows():
                from_bus, to_bus = int(row["from_bus"]), int(row["to_bus"])
                if not (_has_geo(from_bus) and _has_geo(to_bus)):
                    continue
                in_service = bool(row.get("in_service", True))
                style = (dict(color=TCSC_COLOR, linewidth=1.3, linestyle="solid") if in_service
                        else dict(color=OOS_COLOR, linewidth=1.0, linestyle=OOS_DASH))
                SldPlotter.draw_orthogonal_connector(
                    ax, SldPlotter._bus_xy(net, from_bus), SldPlotter._bus_xy(net, to_bus),
                    zorder=3, half_width=busbar_half_width, **style)
            rendered_tables.add("tcsc")

        # ---- busbars ----
        for bus in net.bus.index:
            bus = int(bus)
            if not _has_geo(bus):
                continue
            x, y = SldPlotter._bus_xy(net, bus)
            spec = bus_color_fn(bus)
            color, linewidth = spec[0], spec[1]
            half_len_mult = spec[2] if len(spec) > 2 else 1.0
            SldPlotter.draw_busbar(ax, x, y, half_length=busbar_half_width * half_len_mult,
                        color=color, linewidth=linewidth, zorder=5, orientation="vertical")
        rendered_tables.add("bus")

        # ---- load / sgen icons (existing style preserved, method untouched) ----
        SldPlotter.draw_load_sgen_icons(ax, net, bus_size, mall_bus=mall_bus,
                            bus_half_length=busbar_half_width,
                            load_color=load_color, sgen_color=sgen_color,
                            line_color=SLD_BUSBAR_COLOR)
        if len(net.load):
            rendered_tables.add("load")
        if len(net.sgen):
            rendered_tables.add("sgen")

        # ---- trafo (2W): existing style + out-of-service split ----
        if len(net.trafo):
            in_mask = net.trafo["in_service"].astype(bool)
            try:
                if in_mask.any():
                    SldPlotter._add_collection_safe(ax, pp_plot.create_trafo_collection(
                        net, trafos=net.trafo.index[in_mask], size=SLD_SYM_TRAFO, color=trafo_color))
                if (~in_mask).any():
                    SldPlotter._add_collection_safe(ax, pp_plot.create_trafo_collection(
                        net, trafos=net.trafo.index[~in_mask], size=SLD_SYM_TRAFO, color=OOS_COLOR))
            except Exception as exc:
                _log(f"pp_plot.create_trafo_collection failed: {exc!r}")
            rendered_tables.add("trafo")

        # ---- trafo3w: use pp_plot if present, else marker fallback ----
        if "trafo3w" in net and len(net.trafo3w):
            has_fn = hasattr(pp_plot, "create_trafo3w_collection")
            drawn = False
            if has_fn:
                try:
                    in_mask = net.trafo3w["in_service"].astype(bool)
                    if in_mask.any():
                        SldPlotter._add_collection_safe(ax, pp_plot.create_trafo3w_collection(
                            net, trafo3ws=net.trafo3w.index[in_mask], color=trafo_color))
                    if (~in_mask).any():
                        SldPlotter._add_collection_safe(ax, pp_plot.create_trafo3w_collection(
                            net, trafo3ws=net.trafo3w.index[~in_mask], color=OOS_COLOR))
                    drawn = True
                except Exception as exc:
                    _log(f"pp_plot.create_trafo3w_collection exists but failed ({exc!r}); "
                        f"using marker fallback.")
            if not drawn:
                for ti, row in net.trafo3w.iterrows():
                    hv_bus = int(row["hv_bus"])
                    if not _has_geo(hv_bus):
                        continue
                    x, y = SldPlotter._bus_xy(net, hv_bus)
                    in_service = bool(row.get("in_service", True))
                    ax.scatter([x], [y], marker="D", s=44, linewidth=1.4, zorder=6,
                            facecolor="none",
                            edgecolor=(trafo_color if in_service else OOS_COLOR))
                if not has_fn:
                    _log("pp_plot.create_trafo3w_collection not found in this pandapower "
                        "version; trafo3w drawn as diamond markers at hv_bus.", "info")
            rendered_tables.add("trafo3w")

        # ---- ext_grid: existing style + out-of-service split ----
        if len(net.ext_grid):
            in_mask = (net.ext_grid["in_service"].astype(bool)
                    if "in_service" in net.ext_grid.columns
                    else pd.Series(True, index=net.ext_grid.index))
            try:
                if in_mask.any():
                    SldPlotter._add_collection_safe(ax, pp_plot.create_ext_grid_collection(
                        net, ext_grids=net.ext_grid.index[in_mask], size=SLD_SYM_EXTGRID))
                if (~in_mask).any():
                    SldPlotter._add_collection_safe(ax, pp_plot.create_ext_grid_collection(
                        net, ext_grids=net.ext_grid.index[~in_mask], size=SLD_SYM_EXTGRID, color=OOS_COLOR))
            except Exception as exc:
                _log(f"pp_plot.create_ext_grid_collection failed: {exc!r}")
            rendered_tables.add("ext_grid")

        # ---- single-bus elements with no dedicated pp_plot collection ----
        # These markers used to be scattered at the exact bus coordinate, i.e.
        # on top of the busbar. Park them below-LEFT of the bar instead (loads
        # and sgens already own the right-hand side) and stack several elements
        # on the same bus downwards so they never land on each other.
        _marker_slot = {}

        def _scatter_bus_elements(table_name, marker, color, size=SLD_SYM_MARKER):
            if table_name not in net or not len(net[table_name]):
                return
            for _, row in net[table_name].iterrows():
                bus = int(row["bus"])
                if not _has_geo(bus):
                    continue
                x, y = SldPlotter._bus_xy(net, bus)
                slot = _marker_slot.get(bus, 0)
                _marker_slot[bus] = slot + 1
                x -= busbar_half_width * 0.8
                y -= busbar_half_width * 1.3 + slot * 0.26
                in_service = bool(row.get("in_service", True))
                ax.scatter([x], [y], marker=marker, s=size, linewidth=1.2, zorder=6,
                        facecolor=(color if in_service else "none"),
                        edgecolor=(color if in_service else OOS_COLOR))
            rendered_tables.add(table_name)

        _scatter_bus_elements("gen", "s", GEN_COLOR)
        _scatter_bus_elements("storage", "P", STORAGE_COLOR)
        _scatter_bus_elements("shunt", "v", SHUNT_COLOR, size=SLD_SYM_MARKER * 0.8)
        _scatter_bus_elements("ward", "x", WARD_COLOR, size=SLD_SYM_MARKER * 0.8)
        _scatter_bus_elements("xward", "X", XWARD_COLOR, size=SLD_SYM_MARKER * 0.8)
        _scatter_bus_elements("svc", "*", SVC_COLOR)
        _scatter_bus_elements("ssc", "*", SSC_COLOR)

        # ---- audit: log any populated element table we did not render ----
        # NOTE: dir(net) (as originally specced) is wrong for a pandapowerNet --
        # it returns methods/dunders too, most not DataFrames -> len() would
        # raise. net is dict-like, so we iterate net.keys() restricted to known
        # electrical element tables and skip res_*/cost/metadata tables.
        KNOWN_ELEMENT_TABLES = {
            "bus", "line", "trafo", "trafo3w", "impedance", "dcline", "switch",
            "load", "sgen", "gen", "ext_grid", "storage", "shunt", "ward",
            "xward", "svc", "ssc", "tcsc", "motor", "asymmetric_load", "asymmetric_sgen",
        }
        for table_name in net.keys():
            if table_name not in KNOWN_ELEMENT_TABLES:
                continue
            try:
                table = net[table_name]
            except Exception:
                continue
            if not hasattr(table, "__len__") or not len(table):
                continue
            if table_name not in rendered_tables:
                _log(f"net.{table_name} has {len(table)} row(s) but was NOT "
                    f"rendered by _draw_sld_base.")


    @staticmethod
    def draw_load_sgen_icons(ax, net, bus_size, mall_bus=None,
                              bus_half_length=0.35, attach_frac=0.85,
                              h_offset=0.55, v_drop=0.42, stack_gap=0.42,
                              load_color=SLD_LOAD_COLOR, sgen_color=SLD_SGEN_COLOR,
                              line_color=SLD_BUSBAR_COLOR,
                              arrow_len=0.26, sgen_radius=0.16):
        """Draws load/sgen icons manually using standard SLD conventions.

    - sgen's stub attaches near the TOP of the busbar
      (bus_y + bus_half_length*attach_frac); load's stub attaches near
      the BOTTOM (bus_y - bus_half_length*attach_frac) -- two distinct
      points on the bus itself, so both visibly connect to it.
    - From each attach point: horizontal segment first, then vertical
      to the icon (sgen circle above, load arrow below).
    - Connector lines are the same color as the busbar (black), not grey,
      so they read as a continuous electrical connection.

    NOTE: bus_half_length should match the busbar_half_width used by
    draw_busbar() for this same plot.
    """
        import numpy as np

        for bus in net.bus.index:
            geo_str = net.bus.at[bus, "geo"]
            if pd.isna(geo_str):
                continue
            bus_x, bus_y = SldPlotter._bus_xy(net, bus)

            sgen_attach_y = bus_y + bus_half_length * attach_frac
            load_attach_y = bus_y - bus_half_length * attach_frac

            def _stub_path(attach_y, icon_x, icon_y):
                ax.plot([bus_x, icon_x], [attach_y, attach_y], color=line_color, linewidth=1.2, zorder=2)
                ax.plot([icon_x, icon_x], [attach_y, icon_y], color=line_color, linewidth=1.2, zorder=2)

            bus_loads = net.load[net.load["bus"] == bus]
            bus_sgens = net.sgen[net.sgen["bus"] == bus]

            for i in range(len(bus_loads)):
                icon_x = bus_x + h_offset + i * stack_gap
                tail_y = load_attach_y - v_drop
                head_y = tail_y - arrow_len
                head_length = arrow_len * 0.5

                _stub_path(load_attach_y, icon_x, tail_y)

                ax.arrow(icon_x, tail_y, 0, head_y - tail_y,
                         head_width=arrow_len * 0.55, head_length=head_length,
                         length_includes_head=True, fc=load_color, ec=load_color,
                         linewidth=1.2, zorder=4)

            for i in range(len(bus_sgens)):
                icon_x = bus_x + h_offset + i * stack_gap
                icon_y = sgen_attach_y + v_drop
                _stub_path(sgen_attach_y, icon_x, icon_y)
                circle = plt.Circle((icon_x, icon_y), sgen_radius, facecolor="white",
                                     edgecolor=sgen_color, linewidth=1.7, zorder=4)
                ax.add_patch(circle)
                xs = np.linspace(-sgen_radius * 0.75, sgen_radius * 0.75, 40)
                ys = np.sin(xs / (sgen_radius * 0.75) * np.pi) * (sgen_radius * 0.35)
                ax.plot(icon_x + xs, icon_y + ys, color=sgen_color, linewidth=1.4, zorder=5)

    @staticmethod
    def plot_soc_and_tracking(opf_results_df, res_actual, scenario_label, violation_details_df=None):
        fig = ScenarioHtmlReport._build_soc_tracking_chart_fig(opf_results_df, res_actual, scenario_label,
                                             violation_details_df=violation_details_df)
        SldPlotter.save_and_show_fig(fig, f"prosumer_soc_tracking_{scenario_label}.png")

    @staticmethod
    def plot_scenario_diagnostics(opf_results_df, res_actual, scenario_label, violation_details_df=None):
        SldPlotter.plot_prosumer_participation(opf_results_df, scenario_label, violation_details_df=violation_details_df)
        SldPlotter.plot_soc_and_tracking(opf_results_df, res_actual, scenario_label, violation_details_df=violation_details_df)

######################################################################################################################
# 12. HTML Scenario Report
#
# With 192 hourly steps, this instead builds one self-contained HTML file per
# scenario summarizing every violation that occurred (what, where, when)
# and exactly how the mall reacted at every one of the 192 steps -- all the
# same numbers as the CSVs, but readable without opening a spreadsheet.
######################################################################################################################

_STATUS_ROW_COLOR = {
    "no_violation_no_flex_needed":       "#e8f5e9",   # light green - all clear
    "opf_success_violations_resolved":   "#fff9c4",   # light yellow - flex used, fixed it
    "opf_failed_fallback_resolved":      "#fff9c4",
    "opf_success_remaining_violations":  "#ffcdd2",   # light red - flex used, not enough
    "opf_failed_fallback_violations":    "#ffcdd2",
    "flex_bounds_infeasible":            "#ffe0b2",   # orange - mall had no room to help
    "pf_with_mall_failed":               "#e0e0e0",   # grey - numerical failure
    "pf_after_ppros_update":             "#e0e0e0",
}
_STATUS_LABEL = {
    "no_violation_no_flex_needed":       "No violation - no action needed",
    "opf_success_violations_resolved":   "Violation resolved by mall flexibility",
    "opf_failed_fallback_resolved":      "Violation resolved (OPF failed, fallback worked)",
    "opf_success_remaining_violations":  "Violation persisted despite mall flexibility",
    "opf_failed_fallback_violations":    "Violation persisted (OPF and fallback both insufficient)",
    "flex_bounds_infeasible":            "Mall had no feasible flexibility this hour",
    "pf_with_mall_failed":               "Power flow failed (numerical)",
    "pf_after_ppros_update":             "Power flow failed after dispatch update",
}

class ScenarioHtmlReport:
    @staticmethod
    def _fig_to_base64(fig):
        import io, base64
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode("utf-8")
        plt.close(fig)
        return encoded

    @staticmethod
    def _build_participation_chart_fig(opf_results_df, scenario_label, violation_details_df=None):
        fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

        ax = axes[0]
        ax.plot(opf_results_df.index, opf_results_df["p_base_mw"], label="Baseline import (no flex)",
                linestyle="--", color="tab:gray")
        ax.plot(opf_results_df.index, opf_results_df["p_opf_mw"], label="Actual setpoint (closed loop)",
                color="tab:blue")
        ax.axhline(0, color="black", linewidth=0.8)
        if violation_details_df is not None:
            SldPlotter._annotate_violation_bands(ax, violation_details_df, phase="before", color="tab:orange", alpha=0.10)
        SldPlotter.style_axis(ax, "Mall grid power [MW]\n(+ import / - export)",
                   f"[{scenario_label}] Baseline vs. flexibility-adjusted dispatch")

        ax = axes[1]
        ax.plot(opf_results_df.index, opf_results_df["mall_feeder_line_loading_before_pct"],
                label="Feeder loading before OPF", linestyle="--", color="tab:gray")
        ax.plot(opf_results_df.index, opf_results_df["mall_feeder_line_loading_after_pct"],
                label="Feeder loading after OPF", color="tab:green")
        ax.axhline(100.0, color="tab:red", linestyle=":", label="100% (limit)")
        if violation_details_df is not None:
            SldPlotter._annotate_violation_bands(ax, violation_details_df, phase="before", color="tab:orange", alpha=0.10)
            summary = SldPlotter._violation_summary_text(violation_details_df, phase="before")
            if summary:
                ax.text(0.01, 0.98, summary, transform=ax.transAxes, fontsize=7, va="top", ha="left",
                        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))
        ax.set_xlabel("Time")
        SldPlotter.style_axis(ax, "Mall feeder line loading [%]",
                   f"[{scenario_label}] Feeder line loading: before vs. after")

        plt.tight_layout()
        return fig

    @staticmethod
    def _build_soc_tracking_chart_fig(opf_results_df, res_actual, scenario_label, violation_details_df=None):
        fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)

        ax = axes[0]
        ax.plot(res_actual.index, res_actual["soc_percent"], label="Thermal storage SOC", color="tab:purple")
        if violation_details_df is not None:
            SldPlotter._annotate_violation_bands(ax, violation_details_df, phase="after", color="tab:red", alpha=0.10)
        SldPlotter.style_axis(ax, "SOC [%]", f"[{scenario_label}] Thermal storage SOC across the run")

        ax = axes[1]
        ax.plot(opf_results_df.index, opf_results_df["p_grid_setpoint_kw"], label="OPF/fallback grid setpoint (kW)")
        ax.plot(opf_results_df.index, opf_results_df["p_updated_grid_kw"], linestyle="--",
                label="Actual pandaprosumer grid power (kW)")
        if violation_details_df is not None:
            SldPlotter._annotate_violation_bands(ax, violation_details_df, phase="after", color="tab:red", alpha=0.10)
            summary = SldPlotter._violation_summary_text(violation_details_df, phase="after")
            if summary:
                ax.text(0.01, 0.98, summary, transform=ax.transAxes, fontsize=7, va="top", ha="left",
                        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))
        ax.set_xlabel("Time")
        SldPlotter.style_axis(ax, "Power [kW]", f"[{scenario_label}] Closed-loop setpoint tracking")

        plt.tight_layout()
        return fig

    @staticmethod
    def build_violation_event_table(violation_details_df):
        """Pivots the flat (time, phase, type, location, value) violation log
    into one row per distinct violation event with its before AND after
    value side by side, so resolution is immediately visible."""
        cols = ["time", "violation_type", "location", "value_before", "value_after", "status"]
        if violation_details_df is None or violation_details_df.empty:
            return pd.DataFrame(columns=cols)

        before = (violation_details_df[violation_details_df["phase"] == "before"]
                  .set_index(["time", "violation_type", "location"])["value"])
        after = (violation_details_df[violation_details_df["phase"] == "after"]
                 .set_index(["time", "violation_type", "location"])["value"])

        combined = pd.DataFrame({"value_before": before}).join(
            pd.DataFrame({"value_after": after}), how="outer")
        combined = combined.reset_index()

        def _status(row):
            return "Resolved" if pd.isna(row["value_after"]) else "Still violating"

        combined["status"] = combined.apply(_status, axis=1)
        combined = combined.sort_values(["time", "violation_type", "location"]).reset_index(drop=True)
        return combined[cols]



    @staticmethod
    def build_scenario_html_report(scenario_label, opf_results_df, violation_details_df,
                                    res_actual, savepath=None):
        """Builds one self-contained HTML file summarizing the full closed-loop
    scenario: headline stats, two diagnostic charts, a full hour-by-hour
    table of the mall's reaction at every step (color-coded by outcome),
    and a violation event log showing each violation's before/after value
    and whether it was resolved. Same underlying numbers as the CSVs, but
    presented for reading rather than spreadsheet-parsing."""

        savepath = savepath or f"grid_scenario_report_{scenario_label}.html"

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
        total_support_mwh = opf_results_df["grid_support_kw"].sum() / 1000.0
        soc_min = res_actual["soc_percent"].min() if len(res_actual) else float("nan")
        soc_max = res_actual["soc_percent"].max() if len(res_actual) else float("nan")

        participation_b64 = ScenarioHtmlReport._fig_to_base64(
            ScenarioHtmlReport._build_participation_chart_fig(opf_results_df, scenario_label, violation_details_df))
        soc_b64 = ScenarioHtmlReport._fig_to_base64(
            ScenarioHtmlReport._build_soc_tracking_chart_fig(opf_results_df, res_actual, scenario_label, violation_details_df))

        event_table = ScenarioHtmlReport.build_violation_event_table(violation_details_df)

        def _cards_html():
            cards = [
                ("Hours simulated", f"{n_total}"),
                ("No violation", f"{n_no_flex} ({n_no_flex / n_total * 100:.0f}%)"),
                ("Violated hours", f"{n_violated} ({n_violated / n_total * 100:.0f}%)"),
                ("Resolved by mall", f"{n_resolved}"),
                ("Remained unresolved", f"{n_remaining}"),
                ("Flex infeasible", f"{n_infeasible}"),
                ("Power-flow failures", f"{n_pf_failed}"),
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
                resolved = row["status"] == "Resolved"
                color = "#e8f5e9" if resolved else "#ffcdd2"
                vb = f"{row['value_before']:.2f}" if pd.notna(row["value_before"]) else "-"
                va = f"{row['value_after']:.2f}" if pd.notna(row["value_after"]) else "-"
                rows_html.append(
                    f'<tr style="background-color:{color};">'
                    f'<td>{row["time"]}</td><td>{row["violation_type"]}</td>'
                    f'<td>{row["location"]}</td><td>{vb}</td><td>{va}</td>'
                    f'<td>{row["status"]}</td></tr>')
            header = ("<tr><th>Time</th><th>Violation type</th><th>Location</th>"
                      "<th>Value before</th><th>Value after</th><th>Status</th></tr>")
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
<img src="data:image/png;base64,{participation_b64}" alt="participation chart">
<img src="data:image/png;base64,{soc_b64}" alt="soc tracking chart">

<h2>Violation Event Log</h2>
<p>
  <span class="legend-swatch" style="background:#e8f5e9;"></span>Resolved by mall &nbsp;&nbsp;
  <span class="legend-swatch" style="background:#ffcdd2;"></span>Still violating after mall dispatch
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

#######################################################################################################################
# 13. Scenario runner
###########################################################################################################################

class ScenarioRunner:
    @staticmethod
    def run_scenario(scenario_label, direction, ses_data_1h_full, heat_data_file,
                      window_start, window_end, mall_bus=MALL_BUS,
                      grid_load_scale=1.0, grid_sgen_scale=1.0,
                      mall_pv_scale=1.0, capacity_derate=1.0,
                      capacity_derate_trafo=1.0, derate_trafo_idx=None,
                      profiles=None, idx=None,
                      derate_line_idx=None, scoped_sgen_idx=None, scoped_load_idx=None,
                      capture_violated_snapshots=True):

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
            net_template = NetFactory.get_net_template(GRID_CODE)
            profiles = sb.get_absolute_values(net_template, profiles_instead_of_study_cases=True)
            idx = pd.date_range(YEAR_START, periods=len(profiles[("load", "p_mw")]), freq="15min")

        q_mall_base_mvar = 0.0
        q_eps = IMPORT_Q_EPS_MVAR
        net_base, mall_load, mall_feeder_line_idx = NetFactory.build_base_net(
            mall_bus=mall_bus, q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps,
            capacity_derate=capacity_derate, derate_line_idx=derate_line_idx,
            capacity_derate_trafo=capacity_derate_trafo, derate_trafo_idx=derate_trafo_idx)

        print(f"[{scenario_label}] Running closed-loop prosumer + grid OPF ({n_steps} hourly steps)...")

        (opf_results_df, updated_flex_target_kw, res_base, res_actual,
         bounds_df, violation_details_df, violated_net_snapshots) = OpfTimeseriesRunner.run_opf_timeseries_for_scenario(
            scenario_label=scenario_label, direction=direction,
            net_base=net_base, mall_load=mall_load, mall_feeder_line_idx=mall_feeder_line_idx,
            profiles=profiles, idx=idx,
            time_series_data_base=time_series_data,
            residual_mall_load_kw=residual_mall_load_kw,
            grid_load_scale=grid_load_scale, grid_sgen_scale=grid_sgen_scale,
            q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps,
            initial_soc=0.0, scoped_sgen_idx=scoped_sgen_idx, scoped_load_idx=scoped_load_idx,
            capture_violated_snapshots=capture_violated_snapshots)

        opf_results_df["p_updated_grid_kw"] = res_actual["p_grid_kw"].reindex(opf_results_df.index)
        opf_results_df["tracking_error_kw"] = opf_results_df["p_updated_grid_kw"] - opf_results_df["p_grid_setpoint_kw"]

        opf_results_df.to_csv(f"grid_opf_timeseries_results_{scenario_label}.csv")
        bounds_df.to_csv(f"grid_flexibility_bounds_{scenario_label}.csv")
        violation_details_df.to_csv(f"grid_violation_details_{scenario_label}.csv", index=False)

        SldPlotter.print_scenario_summary(scenario_label, opf_results_df, violation_details_df, res_actual)

        ScenarioHtmlReport.build_scenario_html_report(scenario_label, opf_results_df, violation_details_df, res_actual)

        return opf_results_df, bounds_df, residual_mall_load_kw, violation_details_df, violated_net_snapshots

    @staticmethod
    def run_for_grid(ses_data_1h_full, best_import_row, grid_code=None):
        global GRID_CODE
        if grid_code is not None:
            GRID_CODE = grid_code

        print(f"\n{'%'*70}\n{GRID_CODE}\n{'%'*70}")
        net_template = NetFactory.get_net_template(GRID_CODE)

        profiles = sb.get_absolute_values(net_template, profiles_instead_of_study_cases=True)
        idx = pd.date_range(YEAR_START, periods=len(profiles[("load", "p_mw")]), freq="15min")
        load_p_15min = pd.DataFrame(profiles[("load", "p_mw")], index=idx)
        load_p_1h = load_p_15min.resample("60min").mean()
        sgen_p_15min = pd.DataFrame(profiles[("sgen", "p_mw")], index=idx)
        sgen_p_1h = sgen_p_15min.resample("60min").mean()

        weakest_leaf_bus, weakest_line = FeederTopology.find_weakest_branch_leaf_bus(net_template)
        MALL_BUS_RESOLVED = weakest_leaf_bus

        print(f"\n[MALL_BUS RESOLUTION] auto-detected weakest-branch leaf bus: {MALL_BUS_RESOLVED} "
              f"(via most-loaded line {weakest_line}) ")

        derate_line_idx = FeederTopology.find_path_lines_to_bus(net_template, MALL_BUS_RESOLVED)
        derate_trafo_idx = FeederTopology.find_path_trafos_to_bus(net_template, MALL_BUS_RESOLVED)
        _, downstream_load_idx, downstream_buses = FeederTopology.find_downstream_elements(
            net_template, MALL_BUS_RESOLVED)

        print(f"[grid diagnostic] mall's own branch: {len(derate_line_idx)} line(s) from ext_grid to bus "
              f"{MALL_BUS_RESOLVED}: {derate_line_idx}")
        print(f"[grid diagnostic] {len(derate_trafo_idx)} trafo(s) on that same path: {derate_trafo_idx}")
        print(f"[grid diagnostic] {len(downstream_load_idx)} load(s) share the mall's branch "
              f"(downstream buses: {sorted(downstream_buses)})")

        print("\n=== Plotting single-line diagram (mall connection point highlighted) ===")
        SldPlotter.plot_single_line_diagram(net_template, mall_bus=MALL_BUS_RESOLVED)

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

        worst_hour_imp = SimbenchProfileSource.find_worst_hour_proxy(
            "import", import_window_start, import_window_end, residual_mall_load_kw_imp, load_p_1h, sgen_p_1h)

        print("\n=== [CASE 1] Calibrating scoped line-capacity derate and scoped real load scale "
              f"INDEPENDENTLY ({len(derate_line_idx)} line(s), {len(downstream_load_idx)} load(s) "
              "on the mall's own branch) -- standalone single-axis violations ===")

        decoupled = GridStressCalibration.calibrate_import_decoupled(
            worst_hour_imp, bounds_df_imp, MALL_BUS_RESOLVED, profiles, idx,
            derate_line_idx=derate_line_idx, scoped_load_idx=downstream_load_idx,
            derate_trafo_idx=derate_trafo_idx)

        chosen_capacity_derate, calib_derate = decoupled["derate_only"]
        chosen_import_load_scale, calib_load = decoupled["load_scale_only"]
        chosen_trafo_derate, calib_trafo_derate = decoupled["trafo_derate_only"]

        print(f"[CASE 1] Chosen capacity_derate (derate-only) = {chosen_capacity_derate:.4f}")
        print(f"[CASE 1] Chosen load_scale (load-only) = {chosen_import_load_scale:.4f}")

        GridStressCalibration.print_calibration_spot_check(calib_derate, chosen_capacity_derate, "import_derate", worst_hour_imp)
        GridStressCalibration.print_calibration_spot_check(calib_load, chosen_import_load_scale, "import_load", worst_hour_imp)

        if chosen_trafo_derate is not None:
            print(f"[CASE 1] Chosen trafo capacity_derate (trafo-derate-only) = {chosen_trafo_derate:.4f}")
            GridStressCalibration.print_calibration_spot_check(calib_trafo_derate, chosen_trafo_derate, "import_trafo_derate", worst_hour_imp)

        print("\n=== Spot-checking each calibrated threshold once more before running scenarios ===")

        snapshot_derate = GridStressCalibration.evaluate_calibration_point(
            "import", worst_hour_imp, bounds_df_imp, MALL_BUS_RESOLVED, profiles, idx,
            mode="derate", value=chosen_capacity_derate, derate_line_idx=derate_line_idx,
            return_net=False)

        snapshot_load = GridStressCalibration.evaluate_calibration_point(
            "import", worst_hour_imp, bounds_df_imp, MALL_BUS_RESOLVED, profiles, idx,
            mode="scale", value=chosen_import_load_scale, scoped_load_idx=downstream_load_idx,
            return_net=False)

        if chosen_trafo_derate is not None:
            snapshot_trafo = GridStressCalibration.evaluate_calibration_point(
                "import", worst_hour_imp, bounds_df_imp, MALL_BUS_RESOLVED, profiles, idx,
                mode="derate_trafo", value=chosen_trafo_derate, derate_trafo_idx=derate_trafo_idx,
                return_net=False)
        else:
            print("[snapshot] trafo-derate axis skipped (no trafo on path, or not binding).")

        print("\n=== Running scenarios and preparing HyperCAP export ===")

        case_dict, manifest_path = ScenarioRunner.run_for_grid_hypercap_tail(
            MALL_BUS_RESOLVED, ses_data_1h_full, heat_data_file,
            import_window_start, import_window_end,
            derate_line_idx, downstream_load_idx,
            chosen_capacity_derate, chosen_import_load_scale,
            profiles, idx, net_template,mall_branch_buses=downstream_buses)

        return case_dict, manifest_path


    @staticmethod
    def run_for_grid_hypercap_tail(MALL_BUS_RESOLVED, ses_data_1h_full, heat_data_file,
                                    import_window_start, import_window_end,
                                    derate_line_idx, downstream_load_idx,
                                    chosen_capacity_derate, chosen_import_load_scale,
                                    profiles, idx, net_template,
                                    mall_branch_buses=None):

        scenario_configs = [
            dict(scenario_label="import_derate_only_window",
                 grid_load_scale=1.0, grid_sgen_scale=1.0,
                 capacity_derate=chosen_capacity_derate,
                 derate_line_idx=derate_line_idx, scoped_load_idx=None),
            dict(scenario_label="import_load_only_window",
                 grid_load_scale=chosen_import_load_scale, grid_sgen_scale=1.0,
                 capacity_derate=1.0,
                 derate_line_idx=None, scoped_load_idx=downstream_load_idx),
        ]

        violation_details_by_case = {}
        combined_snapshots = {}

        for cfg in scenario_configs:
            _, _, _, violation_details, snapshots = ScenarioRunner.run_scenario(
                cfg["scenario_label"], "import", ses_data_1h_full, heat_data_file,
                import_window_start, import_window_end,
                mall_bus=MALL_BUS_RESOLVED,
                grid_load_scale=cfg["grid_load_scale"], grid_sgen_scale=cfg["grid_sgen_scale"],
                capacity_derate=cfg["capacity_derate"],
                derate_line_idx=cfg["derate_line_idx"],
                scoped_load_idx=cfg["scoped_load_idx"],
                profiles=profiles, idx=idx)

            violation_details_by_case[cfg["scenario_label"]] = violation_details
            for hour, net_snapshot in snapshots.items():
                combined_snapshots[(cfg["scenario_label"], hour)] = net_snapshot

        per_scenario_counts = ", ".join(
            f"{cfg['scenario_label']}: "
            f"{sum(1 for k in combined_snapshots if k[0] == cfg['scenario_label'])}"
            for cfg in scenario_configs)
        print(f"\n=== [HyperCAP export] {len(combined_snapshots)} violated-hour case(s) "
              f"across both scenarios ({per_scenario_counts}) ===")

        case_dict, manifest_path = HyperCapExporter.prepare_hypercap_export(
            net_base=net_template,
            violation_details_by_case=violation_details_by_case,
            violated_net_snapshots=combined_snapshots,
            fixed_topology=True,
            eq_type="ward",
            out_dir=f"hypercap_cases_{GRID_CODE.replace(' ', '_')}",
            mall_branch_buses=mall_branch_buses)

        # case_dict (from prepare_hypercap_export -> build_hypercap_scenario_case_dict)
        # already IS the reinforcement-planning input: one merged, Ward-reduced
        # net per scenario. loadcase_ids for a scenario are available at
        # case_metadata[scenario]["loadcase_ids"] if needed downstream.
        return case_dict, manifest_path

########################################################################################################################
# 14. HyperCAP reduced-network export
#
# One HyperCAP case per violating (scenario, hour) snapshot. Only hours with
# residual violations (phase="after") are exported. The buses directly
# involved in a snapshot's violations define its detailed target region;
# boundary buses are the buses immediately outside that region on the
# pandapower topology graph. The actual electrical reduction is performed
# only by pandapower's get_equivalent(..., eq_type="ward", ...) -- there is
# no custom hop expansion, cross-hour region merging, or reimplementation of
# pandapower's own group-reduction logic.
########################################################################################################################

# VALIDATION TOLERANCES (tighten if you want a stricter equivalence check --
# see the notes below build_hypercap_case_dict for why these are conservative)

HYPERCAP_VOLTAGE_TOLERANCE_PU = 1e-4
HYPERCAP_ANGLE_TOLERANCE_DEG = 0.05
HYPERCAP_POWER_TOLERANCE_MW = 1e-1
HYPERCAP_POWER_TOLERANCE_MVAR = 1e-1
HYPERCAP_LOADING_TOLERANCE_PERCENT = 0.5

class HyperCapReducer:
    @staticmethod
    def _run_equivalence_pf(net):
        """Fresh, isolated power flow used only for equivalence validation --
    deliberately separate from the main script's run_pf() (different solver
    settings: voltage angles + Q-limit enforcement, matching what the
    standalone validator used) so it never interferes with the OPF
    calibration/timeseries loop elsewhere in the script. Kept separate from
    the comparison logic below because it's a solve step, not a diff --
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
            return {col: None for col in columns}
 
        reduced_table = reduced_pf[table_name]
        source_table = source_pf[table_name]
 
        common = set(int(x) for x in reduced_table.index) & set(int(x) for x in source_table.index)
        if indices is not None:
            common &= set(int(x) for x in indices)
 
        diffs = {col: [] for col in columns}
        for idx in sorted(common):
            for col in columns:
                if col not in reduced_table.columns or col not in source_table.columns:
                    continue
                rv = _safe_float(reduced_table.at[idx, col])
                sv = _safe_float(source_table.at[idx, col])
                if rv is not None and sv is not None:
                    diffs[col].append(rv - sv)
 
        result = {}
        for col, values in diffs.items():
            finite = [abs(v) for v in values if math.isfinite(v)]
            result[col] = max(finite) if finite else None
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

        Per hour: derives that hour's violation seed buses using the exact
        same helpers as the original per-hour path (collect_violated_element_ids
        + violated_elements_to_seed_buses). Unions the seed buses across every
        hour in the scenario, expands the union through switch-closed groups
        (get_connected_switch_buses_groups) exactly once, then calls
        find_boundary_buses / normalize_boundary_buses exactly once on that
        union -- instead of computing a separate region per hour.

        Topology bus lookups here are read-only (no net is mutated) and use
        the scenario's first hour as the topology reference net, since every
        hour within one scenario shares net_base's topology by construction
        (the same assumption Section 15 / merge_loadcases relies on).

        Returns (detailed_buses, boundary_buses, per_hour_seed_meta) where
        per_hour_seed_meta = {timestamp.isoformat(): {"violation_element_ids":
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
        """Electrical-equivalence check for one HyperCAP case: runs a fresh PF on
    both the reduced network and its exact pre-reduction source, then
    compares voltage/angle/P/Q at internal + boundary buses, loading on any
    commonly retained lines/trafos, and ext_grid P/Q. Returns a dict with
    "passed" (bool), "failed_checks" (list of str), and the raw max-abs
    differences for reference. Never raises on a failed comparison -- only
    on a hard structural problem (e.g. PF not converging), which is itself
    reported via "passed": False rather than an exception, so a single bad
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
        """Background patches marking the internal (detailed), boundary
    (interface), and external (Ward-equivalent) regions. Visualization
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
        """Draws an explanatory 'W' box next to each Ward-equivalent bus,
    stacking multiple wards at the same bus. The Ward elements themselves
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
#PM#5: check why the internal buses and boundary buses are still being check for in the original grid
    @staticmethod
    def plot_hypercap_reduced_sld(net, case_id, case_metadata, savepath, dpi=220,
                                   leaf_step=SLD_LEAF_STEP, depth_step=SLD_DEPTH_STEP,
                                   busbar_half_width=0.35):
        """Visualization-only SLD for one already-reduced HyperCAP network.
    Classification: GREEN = internal (detailed), ORANGE = boundary
    (interface), BLUE = external network (Ward equivalent), HATCH = Ward
    element. Reuses _draw_sld_base() for the base network rendering (same
    renderer plot_single_line_diagram() uses) and only adds the
    classification overlays here. Does not modify net's electrical model --
    only fills in missing net.bus.geo and draws."""
        internal_buses = {int(b) for b in case_metadata.get("detailed_internal_buses", [])}
        boundary_buses = {int(b) for b in case_metadata.get("boundary_buses", [])}
        resolved_mall_bus = int(case_metadata.get("mall_bus", MALL_BUS))

        FeederTopology.compute_hierarchical_layout(net, leaf_step=leaf_step, depth_step=depth_step)
        fig, ax = plt.subplots(figsize=SldPlotter._compute_sld_figsize(net))

        coords = {int(b): SldPlotter._bus_xy(net, b) for b in net.bus.index if pd.notna(net.bus.at[b, "geo"])}
        if not coords:
            raise RuntimeError(f"HyperCAP SLD {case_id}: no bus coordinates available.")

        HyperCapSldPlotter._draw_hypercap_region_patches(ax, coords, internal_buses, boundary_buses)

        def _classify(bus):
            if bus == resolved_mall_bus:
                return SLD_MALL_COLOR, 6.0
            if bus in internal_buses:
                return "#2ca02c", 5.0
            if bus in boundary_buses:
                return "#e69f00", 5.0
            return SLD_BUSBAR_COLOR, 3.0

        # fixed symbol size in layout units; get_collection_sizes() scales
        # with the net's extent and returns absurd values on a large feeder
        bus_size = min(leaf_step, depth_step) * 0.10
        SldPlotter._draw_sld_base(ax, net, bus_size, busbar_half_width=busbar_half_width,
                        bus_color_fn=_classify, mall_bus=resolved_mall_bus)

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
        """Merges N structurally-identical pandapower nets (one per violated
        hour in a scenario) into a single net carrying all N as parallel
        load cases.

        Enforces the precondition that every net shares one topology (same
        bus/line/trafo/load/sgen indices, same order) -- that's what makes
        stacking p_mw/q_mvar row-by-row across nets valid in the first
        place. Returns a deep copy of nets[0] with 'scaling_loadcases'
        (and, if it varies, 'scaling_loadcases_q') columns added to its
        load/sgen tables, plus 'loadcase_labels' / 'n_loadcases' recorded on
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
        """: build ONE frozen Ward-reduction region per scenario, reduce+validate every hour
        against it, merge the per-hour reduced nets per scenario
        (build_hypercap_scenario_case_dict), then write the resulting
        scenario-keyed case dict (+ metadata + source snapshots) to disk,
        render SLDs, and warn if any hour failed electrical-equivalence
        validation. I/O and SLD calls are unchanged from before; only the
        naming shifts from "case_id" (one per hour) to "scenario_label"
        (one per scenario), matching case_dict's new keys."""
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

    @staticmethod
    def build_hypercap_scenario_case_dict(net_base, violation_details_by_case, violated_net_snapshots,
                                           phase="after", eq_type="ward", verbose=True, validate=True):
        """

        For each scenario: builds ONE frozen Ward-reduction region (union of
        every hour's violation seed buses in that scenario --
        HyperCapReducer.build_scenario_region), reduces + validates EVERY
        hour in that scenario against that SAME frozen region (delegated to
        build_hypercap_case_dict, unchanged reduce/validate/metadata shape),
        then merges the N per-hour reduced nets for that scenario into one
        net via HyperCapExporter.merge_loadcases. Merging
        is only sound here because every hour in the scenario was reduced
        against the identical boundary/internal bus set, so the N reduced
        nets are guaranteed structurally identical.

        MEAN-VS-WORST-HOUR CHOICE (documented): merge_loadcases (protected,
        unchanged) deep-copies nets[0] as the merged net's structural +
        fallback-value (mean p_mw) template. Its *topology/geo/labels* come
        from whichever net is nets[0] -- so we explicitly order each
        scenario's net list to put the WORST hour (max |violation value|
        for that scenario/phase) first. This makes the merged net (and any
        SLD rendered from it) represent the worst hour, not an arbitrary
        chronological pick.

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
            """Picks the case_id whose hour has the largest |violation value|
            for this scenario/phase -- see MEAN-VS-WORST-HOUR CHOICE above."""
            worst_case_id, worst_value = case_ids[0], -np.inf
            for cid in case_ids:
                timestamp = pd.Timestamp(per_hour_case_metadata[cid]["time"])
                rows = violation_table[(violation_table["_hypercap_time"] == timestamp)
                                        & (violation_table["_hypercap_phase"] == str(phase))]
                if rows.empty:
                    continue
                peak = rows["value"].abs().max()
                if pd.notna(peak) and peak > worst_value:
                    worst_value = peak
                    worst_case_id = cid
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


##############################################################################################
# 15. Main workflow
#########################################################################################################################

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
        ScenarioRunner.run_for_grid(ses_data_1h_full, best_import_row, grid_code=grid_code)

if __name__ == "__main__":
    main()