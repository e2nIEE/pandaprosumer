import pandas as pd
import tqdm

from pandapower.control import get_controller_order
from pandapower.create import _get_multiple_index_with_check
from pandapower.timeseries import DFData
from pandapower.timeseries.run_time_series import (print_progress, control_time_step, controller_not_converged,
                                                   pf_not_converged, finalize_step)
from pandaprosumer.run_control import run_control, prepare_run_ctrl

from pandapower.control.run_control import ControllerNotConverged

import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

try:
    import pandaplan.core.pplog as pplog
except ImportError:
    import logging as pplog

logger = pplog.getLogger(__name__)
logger.setLevel(level=pplog.WARNING)


def run_timeseries(prosumer, period_index=0, verbose=True):
    start = prosumer.period.at[period_index, 'start']
    end = prosumer.period.at[period_index, 'end']
    resol = int(prosumer.period.at[period_index, 'resolution_s'])
    dur = pd.date_range(start, end, freq='%ss' % resol, tz=prosumer.period.at[period_index, 'timezone'])

    #control_diagnostic_pandaprosumer(prosumer, start, end, resol)
    ts_variables = init_time_series(prosumer, dur, verbose)
    time_series_initialization(ts_variables['controller_order'])
    run_loop(prosumer, ts_variables, output_writer_fct=output_writer_fct, evaluate_net_fct=evaluate_prosumer_fct,
             run_control_fct=run_control)
    time_series_finalization(ts_variables['controller_order'])


def time_series_initialization(controller_order):
    retrieve_data(controller_order, 'time_series_initialization')


def time_series_finalization(controller_order):
    retrieve_data(controller_order, 'time_series_finalization')


def retrieve_data(controller_order, fct_name):
    ctrl_list = []
    for levelorder in controller_order:
        for ctrl, prosumer in levelorder:

            if hasattr(ctrl, 'has_elements') and ctrl.has_elements:  # FixMe: Should be has_elements or has_period ?
                #if ctrl in ctrl_list:
                #    continue
                #else:
                ctrl_list += [ctrl]
                fct = getattr(ctrl, fct_name, None)
                if fct is None or 'time_series' not in prosumer:
                    continue
                res = fct(prosumer)
                data = [DFData(pd.DataFrame(entry, columns=ctrl.result_columns, index=ctrl.time_index)) for entry in res]
                index = _get_multiple_index_with_check(prosumer, 'time_series', None, len(data))
                columns = ['name', 'element', 'element_index', 'period_index', 'data_source']
                for i, idx in enumerate(index):
                    name = prosumer[ctrl.element_name].loc[ctrl.element_index[i], 'name']
                    prosumer['time_series'].loc[idx, columns] = (name, ctrl.element_name, int(ctrl.element_index[i]),
                                                             ctrl.period_index, data[i])

                # else:
                #    name = ctrl.name
                #    prosumer['time_series'].at[idx, columns] = (name, 'controller', int(ctrl.index),
                #                                                ctrl.obj.period_index, ctrl.location_index, data[i])


def control_diagnostic_pandaprosumer(prosumer, start, end, resolution_s):
    _, controller_order = get_controller_order(prosumer, prosumer.controller)
    for levelorder in controller_order:
        for ctrl, _ in levelorder:
            if hasattr(ctrl, 'period_index') and (ctrl.start != start or ctrl.end != end or ctrl.resol != resolution_s):
                raise (UserWarning(r'if you run run_timeseries, all controllers interacting with each other '
                                   r'need to refer to the same period_index'))


def output_writer_fct(prosumer, time_step, pf_converged, ctrl_converged, ts_variables):
    if not hasattr(prosumer, 'controller_results'):
        prosumer.controller_results = {}

    results_this_step = {}

    for level in ts_variables['controller_order']:
        for ctrl, _ in level:
            result = getattr(ctrl, 'last_result', None)
            if result is not None:
                results_this_step[ctrl.index] = result

    prosumer.controller_results[time_step] = results_this_step



def evaluate_prosumer_fct(prosumer, levelorder, ctrl_variables, **kwargs):
    return ctrl_variables


def init_time_series(prosumer, time_steps, verbose=True, **kwargs):
    """
    inits the time series calculation
    creates the dict ts_variables, which includes necessary variables for the time series / control function

    INPUT:
        **net** - The pandapower format network

        **time_steps** (list or tuple, None) - time_steps to calculate as list or tuple (start, stop)
        if None, all time steps from provided data source are simulated

    OPTIONAL:

        **continue_on_divergence** (bool, False) - If True time series calculation continues in case of errors.

        **verbose** (bool, True) - prints progress bar or logger debug messages
    """

    ts_variables = prepare_run_ctrl(prosumer, **kwargs)
    ts_variables['time_steps'] = time_steps
    ts_variables['verbose'] = verbose

    if logger.level != 10 and verbose:
        # simple progress bar
        ts_variables['progress_bar'] = tqdm.tqdm(total=len(time_steps))

    return ts_variables

def run_loop(prosumer, ts_variables, run_control_fct=run_control, output_writer_fct=output_writer_fct, **kwargs):
    """
    runs the time series loop which calls pp.runpp (or another run function) in each iteration

    Parameters
    ----------
    net - pandapower net
    ts_variables - settings for time series

    """
    for i, time_step in enumerate(ts_variables["time_steps"]):
        print_progress(i, time_step, ts_variables["time_steps"], ts_variables["verbose"], ts_variables=ts_variables,
                       **kwargs)
        prosumer.rerun = False
        run_time_step(prosumer, time_step, ts_variables, run_control_fct, output_writer_fct, **kwargs)

        rerun_time_step = check_results(prosumer)

        if rerun_time_step:
            prosumer.rerun = True
            run_time_step(prosumer, time_step, ts_variables, run_control_fct, output_writer_fct, **kwargs)


def run_time_step(prosumer, time_step, ts_variables, run_control_fct=run_control, output_writer_fct=output_writer_fct,
                  **kwargs):
    """
    Time Series step function
    Is called to run the PANDAPOWER AC power flows with the timeseries module

    INPUT:
        **net** - The pandapower format network

        **time_step** (int) - time_step to be calculated

        **ts_variables** (dict) - contains settings for controller and time series simulation. See init_time_series()
    """
    ctrl_converged = True
    pf_converged = True
    # run time step function for each controller

    control_time_step(ts_variables['controller_order'], time_step)

    try:
        # calls controller init, control steps and run function (runpp usually is called in here)
        run_control_fct(prosumer, ctrl_variables=ts_variables, **kwargs)
    except ControllerNotConverged:
        ctrl_converged = False
        # If controller did not converge do some stuff
        controller_not_converged(time_step, ts_variables)
    except ts_variables['errors']:
        # If power flow did not converge simulation aborts or continues if continue_on_divergence is True
        pf_converged = False
        pf_not_converged(time_step, ts_variables)

    output_writer_fct(prosumer, time_step, pf_converged, ctrl_converged, ts_variables)

    finalize_step(ts_variables['controller_order'], time_step)

def check_results(prosumer):
    rerun = False
    results_timestep = prosumer.controller_results
    ts = list(results_timestep.keys())[-1]

    df_data = prosumer.controller.object[0].df_data

    col_p_el_bhp = prosumer.controller.object[0].input_columns[8]
    col_p_el_chp = prosumer.controller.object[0].input_columns[9]

    input = prosumer.controller.object[0].df_data.get_time_step_value(
        time_step=ts,
        profile_name=prosumer.controller.object[0].input_columns
    ).reshape(1, -1)

    p_el_out = results_timestep[ts][2]["p_el_out_kw"]
    p_el_floor = results_timestep[ts][1]["pel_floor_kw"]
    node_balance = p_el_out - p_el_floor + input[0, 7]

    import json
    import os

    here = os.path.dirname(os.path.abspath(__file__))

    # Pfad zu deiner JSON-Datei
    path = os.path.join(here, "library", "chp_maps", "ice_chp_maps.json")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    chp_map_2 = next(m for m in data["chp_ice_map"] if m["__chp_nominal_size_kw__"] == 700)

    if node_balance != 0:
        results = model_optimization_chp_fit(
            heat_demand=input[0, 2],
            flex_demand=input[0, 7],
            cop_bhp=results_timestep[ts][1]["cop_floor"],
            soc=results_timestep[ts][3]["soc"],
            chp_map=chp_map_2,

            # degree=1
        )

        if results["feasible"]:
            df_data.df.loc[ts, col_p_el_bhp] = results["p_el_bhp"]
            df_data.df.loc[ts, col_p_el_chp] = results["p_el_chp"]


            rerun = True
        else:
            rerun = False
        print(ts)
        print(results)

    return rerun

import pyomo.environ as pyo
# import bisect
#
# def interpolate_load_to_fuel(load_percent, load_pts, fuel_pts):
#     """Linear interpolation of fuel input [kW_fuel] at a given load [%]."""
#     # Ensure increasing load points for bisect
#     if load_pts[0] > load_pts[-1]:
#         load_pts = list(reversed(load_pts))
#         fuel_pts = list(reversed(fuel_pts))
#
#     # Clamp
#     if load_percent <= load_pts[0]:
#         return float(fuel_pts[0])
#     if load_percent >= load_pts[-1]:
#         return float(fuel_pts[-1])
#
#     i = bisect.bisect_right(load_pts, load_percent)
#     l0, l1 = load_pts[i-1], load_pts[i]
#     f0, f1 = fuel_pts[i-1], fuel_pts[i]
#     alpha = (load_percent - l0) / (l1 - l0)
#     return float(f0 + alpha * (f1 - f0))
#
#
# def model_optimization_chp(
#     heat_demand,
#     flex_demand,
#     cop_bhp,
#     c_el,
#     c_gas,
#     chp_map,
#     p_hp_max=1000,
# ):
#     m = pyo.ConcreteModel()
#
#     # Variables
#     m.E_HP  = pyo.Var(domain=pyo.NonNegativeReals)   # HP electric consumption [kW]
#     m.H_HP  = pyo.Var(domain=pyo.NonNegativeReals)   # HP heat [kW_th]
#     m.E_CHP = pyo.Var(domain=pyo.NonNegativeReals)   # CHP electric output [kW]
#     m.H_CHP = pyo.Var(domain=pyo.NonNegativeReals)   # CHP recovered heat [kW_th]
#
#     # Heat pump conversion
#     m.hp_conv = pyo.Constraint(expr = m.H_HP == cop_bhp * m.E_HP)
#
#     # CHP map data
#     x_break = [float(x) for x in chp_map["energy_flow_input_kw"]]       # kW_fuel
#     y_el    = [float(y) for y in chp_map["power_el_kw"]]                 # kW_el
#     y_th    = [float(y) for y in chp_map["heat_flow_recovered_kw"]]      # kW_th
#
#     # Ensure domain points are non-decreasing (required by Piecewise)
#     if x_break[0] > x_break[-1]:
#         x_break = list(reversed(x_break))
#         y_el    = list(reversed(y_el))
#         y_th    = list(reversed(y_th))
#
#     # Load bounds → fuel bounds
#     load_min, load_max = chp_map["load_limits_percent"]     # e.g., [20, 100]
#     load_pts = chp_map["engine_load_percent"]               # e.g., [100, 75, 50, 25, 0]
#     fuel_pts = chp_map["energy_flow_input_kw"]
#
#     F_min = interpolate_load_to_fuel(load_min, load_pts, fuel_pts)
#     F_max = interpolate_load_to_fuel(load_max, load_pts, fuel_pts)
#
#     # Domain variable must have bounds for Piecewise
#     # Use intersection of [min(x_break), max(x_break)] and [F_min, F_max]
#     dom_lo = max(min(x_break), F_min)
#     dom_hi = min(max(x_break), F_max)
#     m.F_CHP = pyo.Var(bounds=(dom_lo, dom_hi))
#
#     # Capacity bounds (HP)
#     m.hp_cap = pyo.Constraint(expr = m.E_HP <= p_hp_max)
#
#     # Piecewise mappings (fuel → electric, fuel → heat)
#     m.el_piece = pyo.Piecewise(
#         m.E_CHP, m.F_CHP,
#         pw_pts=x_break,
#         f_rule=y_el,                 # values corresponding to x_break
#         pw_constr_type='EQ',
#         pw_repn='SOS2'
#     )
#     m.th_piece = pyo.Piecewise(
#         m.H_CHP, m.F_CHP,
#         pw_pts=x_break,
#         f_rule=y_th,
#         pw_constr_type='EQ',
#         pw_repn='SOS2'
#     )
#
#     # Balances
#     m.heat_bal = pyo.Constraint(expr = m.H_HP + m.H_CHP == heat_demand)
#     m.el_bal   = pyo.Constraint(expr = -m.E_HP + m.E_CHP + flex_demand == 0)
#
#     # Objective
#     m.obj = pyo.Objective(expr = c_el * m.E_HP + c_gas * m.F_CHP, sense=pyo.minimize)
#
#     solver = pyo.SolverFactory("cbc")
#     results = solver.solve(m, tee=False, keepfiles=False)
#
#
#     if (results.solver.status == SolverStatus.ok) and \
#             (results.solver.termination_condition == TerminationCondition.optimal):
#         # Optimale Lösung vorhanden
#         return {
#             "E_HP": pyo.value(m.E_HP),
#             "E_CHP": pyo.value(m.E_CHP),
#             "H_HP": pyo.value(m.H_HP),
#             "H_CHP": pyo.value(m.H_CHP),
#             "F_CHP": pyo.value(m.F_CHP),
#             "feasible": True
#         }
#     else:
#         # Keine Lösung gefunden
#         return {"feasible": False}

import numpy as np
def fit_chp_relations(chp_map, degree=1):
    # Daten
    E = np.array(chp_map["power_el_kw"], dtype=float)           # elektrische Leistung
    H = np.array(chp_map["heat_flow_recovered_kw"], dtype=float)# thermische Leistung

    # Sortieren nach E
    idx = np.argsort(E)
    E, H = E[idx], H[idx]

    # Vandermonde-Matrix für Regression: [1, E, E^2, ...]
    X = np.vander(E, N=degree+1, increasing=True)

    # Least Squares Fit: H = f(E)
    coeff_HE, *_ = np.linalg.lstsq(X, H, rcond=None)

    # Bounds
    E_min, E_max = float(E.min()), float(E.max())
    H_min, H_max = float(H.min()), float(H.max())

    return {
        "degree": degree,
        "coeff_HE": coeff_HE.tolist(),
        "bounds": {"E": (E_min, E_max), "H": (H_min, H_max)}
    }

def poly_expr(coeffs, x):
    return sum(coeffs[i] * (x**i) for i in range(len(coeffs)))


def model_optimization_chp_fit(heat_demand, flex_demand, cop_bhp, soc, chp_map,
                               resol=900, degree=1, storage_cap=10000, p_bhp_max=1000):
    fit = fit_chp_relations(chp_map, degree=degree)

    m = pyo.ConcreteModel()

    # Parameter
    m.heat_demand = pyo.Param(initialize=heat_demand)
    m.flex_demand = pyo.Param(initialize=flex_demand)
    m.cop_bhp     = pyo.Param(initialize=cop_bhp)
    m.p_el_bhp_max   = pyo.Param(initialize=p_bhp_max)
    m.soc         = pyo.Param(initialize=soc)
    m.storage_cap = pyo.Param(initialize=storage_cap)
    m.resol       = pyo.Param(initialize=resol)

    # Entscheidungsvariablen
    m.p_el_bhp  = pyo.Var(domain=pyo.NonNegativeReals)  # WP Stromverbrauch
    m.p_el_chp = pyo.Var(domain=pyo.NonNegativeReals)  # BHKW Strom

    # Binärvariable für BHKW-Betrieb
    m.y_chp = pyo.Var(domain=pyo.Binary)

    # Lastgrenzen
    p_el_min_chp = 0.2 * 700
    p_el_max_chp = 700

    m.p_el_chp_min = pyo.Constraint(expr=m.p_el_chp >= p_el_min_chp * m.y_chp)
    m.p_el_chp_max = pyo.Constraint(expr=m.p_el_chp <= p_el_max_chp * m.y_chp)



    # Abgeleitete Variablen
    m.q_th_bhp  = pyo.Var(domain=pyo.NonNegativeReals)  # WP Wärme

    # H_CHP als Expression in Abhängigkeit von E_CHP
    coeff_HE = fit["coeff_HE"]
    m.q_th_chp = pyo.Expression(expr=poly_expr(coeff_HE, m.p_el_chp))

    H_max_chp = 611.56
    # H_CHP darf nur >0 sein, wenn y_CHP = 1
    # m.H_chp_max = pyo.Constraint(expr=m.H_CHP <= H_max_chp * m.y_CHP)

    # Speicher-Variablen
    m.q_th_charge    = pyo.Var(domain=pyo.NonNegativeReals)
    m.q_th_discharge = pyo.Var(domain=pyo.NonNegativeReals)

    m.q_th_charge_max    = pyo.Expression(expr=m.storage_cap * (1 - m.soc) * m.resol / 3600)
    m.q_th_discharge_max = pyo.Expression(expr=m.storage_cap * m.soc * m.resol / 3600)

    # Technologiebeziehungen
    m.hp_conv = pyo.Constraint(expr=m.q_th_bhp == m.cop_bhp * m.p_el_bhp)

    # Kapazitätsgrenzen
    m.hp_cap       = pyo.Constraint(expr=m.p_el_bhp <= m.p_el_bhp_max)
    m.charge_cap   = pyo.Constraint(expr=m.q_th_charge <= m.q_th_charge_max)
    m.discharge_cap= pyo.Constraint(expr=m.q_th_discharge <= m.q_th_discharge_max)

    # Bilanzen
    m.heat_bal = pyo.Constraint(expr=m.q_th_bhp + m.q_th_chp + m.q_th_discharge - m.q_th_charge == m.heat_demand)
    m.el_bal   = pyo.Expression(expr=-m.p_el_bhp + m.p_el_chp + m.flex_demand)

    alpha = 1.0  # Gewicht für Bilanzabweichung
    beta = 0.001  # Gewicht für Minimierung von E_CHP

    m.obj = pyo.Objective(expr=alpha * (m.el_bal ** 2) + beta * m.p_el_chp,
                          sense=pyo.minimize)
    # m.obj = pyo.Objective(expr=alpha * (m.el_bal ** 2),
    #                       sense=pyo.minimize)

    # Solver
    solver = pyo.SolverFactory('mindtpy')
    results = solver.solve(m, strategy='OA', mip_solver='glpk', nlp_solver='ipopt')

    if (results.solver.status == SolverStatus.ok and
        results.solver.termination_condition == TerminationCondition.optimal):
        return {
            "p_el_bhp": pyo.value(m.p_el_bhp),
            "p_el_chp": pyo.value(m.p_el_chp),
            "Hq_th_bhp": pyo.value(m.q_th_bhp),
            "q_th_chp": pyo.value(m.q_th_chp),
            "y":pyo.value(m.y_chp),
            "el_balance": pyo.value(m.el_bal),
            "feasible": True
        }
    else:
        return {"feasible": False}



