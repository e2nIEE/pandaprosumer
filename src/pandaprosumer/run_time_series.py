import pandas as pd
import tqdm

from pandapower.control import get_controller_order
from pandapower.create import _get_multiple_index_with_check
from pandapower.timeseries import DFData
from pandapower.timeseries.run_time_series import (print_progress, control_time_step, controller_not_converged,
                                                   pf_not_converged, finalize_step)
from pandaprosumer.run_control import run_control, prepare_run_ctrl

from pandapower.control.run_control import ControllerNotConverged



try:
    import pandaplan.core.pplog as pplog
except ImportError:
    import logging as pplog

logger = pplog.getLogger(__name__)
logger.setLevel(level=pplog.WARNING)


def run_timeseries(prosumer, period_index=0, check_results_fct=None, verbose=True):
    start = prosumer.period.at[period_index, 'start']
    end = prosumer.period.at[period_index, 'end']
    resol = int(prosumer.period.at[period_index, 'resolution_s'])
    dur = pd.date_range(start, end, freq='%ss' % resol, tz=prosumer.period.at[period_index, 'timezone'])

    #control_diagnostic_pandaprosumer(prosumer, start, end, resol)
    ts_variables = init_time_series(prosumer, dur, verbose)
    time_series_initialization(ts_variables['controller_order'])
    run_loop(prosumer, ts_variables, output_writer_fct=output_writer_fct, evaluate_net_fct=evaluate_prosumer_fct,
             run_control_fct=run_control, check_results_fct=check_results_fct)
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
    """
    Collect and store controller results for a given timestep.

    This function iterates over all controllers defined in the
    timestep variable structure, extracts their most recent results
    (if available), and writes them into the prosumer's
    `controller_results` dictionary under the current timestep key.

    Parameters
    ----------
    prosumer : object
        Prosumer instance that holds controller objects and will be
        extended with a `controller_results` attribute (dict) if it
        does not already exist.
    time_step : int or hashable
        Identifier of the current simulation timestep.


    Returns
    -------
    None
        The function updates `prosumer.controller_results` in place.
    """
    ...
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
        **prosumer** - The pandaprosumer format network

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

def run_loop(prosumer, ts_variables, run_control_fct=run_control, output_writer_fct=output_writer_fct,
             check_results_fct=None, **kwargs):
    """
    runs the time series loop which calls pp.runpp (or another run function) in each iteration.
    After the initial run there is the option to rerun the timestep. Based on the result of the function check_results

    Parameters
    ----------
    prosumer - pandaprosumer prosumer
    ts_variables - settings for time series

    """
    for i, time_step in enumerate(ts_variables["time_steps"]):
        print_progress(i, time_step, ts_variables["time_steps"], ts_variables["verbose"], ts_variables=ts_variables,
                           **kwargs)
        prosumer.rerun = False
        run_time_step(prosumer, time_step, ts_variables, run_control_fct, output_writer_fct, **kwargs)

        if check_results_fct is not None:
            rerun_time_step = check_results_fct(prosumer, time_step)
        else:
            rerun_time_step = False

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

import json
import os
def check_results(prosumer):
    """
    Check the consistency of prosumer simulation results and, if necessary,
    rerun a local CHP and BHP optimization to adjust setpoints.

    This function inspects the most recent timestep of the prosumer's
    controller results. If the node electrical balance is not satisfied,
    it triggers a small Pyomo optimization model (`model_optimization_chp_fit`)
    using a CHP performance map. If the optimization is feasible, the
    corrected electrical outputs for BHP and CHP are written back into
    the prosumer's dataframe.

    Parameters
    ----------
    prosumer :
        Prosumer object with attributes:
        - controller_results : dict
            Dictionary of timestep results.

    Returns
    -------
    rerun : bool
        True if a feasible optimization was found and results were updated,
        False otherwise.
    """
    rerun = False

    #Results for the timestep
    results_timestep = prosumer.controller_results

    #timestep
    ts = list(results_timestep.keys())[-1]

    #DFData - DataSourceClass for the inut data
    df_data = prosumer.controller.object[0].df_data

    #input data for the const. profile for the timestep
    input = prosumer.controller.object[0].df_data.get_time_step_value(
        time_step=ts,
        profile_name=prosumer.controller.object[0].input_columns
    ).reshape(1, -1)

    #result data for el. power for the timestep (bhp - input, chp - output)
    p_el_out_chp = results_timestep[ts][2]["p_el_out_kw"]
    p_el_floor_bhp = results_timestep[ts][1]["pel_floor_kw"]

    #node balance for the timestep
    node_balance = p_el_out_chp - p_el_floor_bhp + input[0, 7]

    #select the chp_map for the optimization
    here = os.path.dirname(os.path.abspath(__file__))
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
        )

        if results["feasible"]:
            #put the results of the optimization as input data for the const profile for the rerun of the timestep
            col_p_el_bhp = prosumer.controller.object[0].input_columns[8]
            col_p_el_chp = prosumer.controller.object[0].input_columns[9]
            df_data.df.loc[ts, col_p_el_bhp] = results["p_el_bhp"]
            df_data.df.loc[ts, col_p_el_chp] = results["p_el_chp"]


            rerun = True
        else:
            rerun = False

    return rerun

import pyomo.environ as pyo
import numpy as np
def fit_chp_relations(chp_map, degree=1):
    """
    Fit a polynomial relation between CHP electrical power and recovered heat.

    Given a CHP performance map (with arrays of electrical and thermal
    outputs), this function performs a least-squares polynomial regression
    of heat flow as a function of electrical power.

    Parameters
    ----------
    chp_map : dict
        Dictionary containing at least:
        - "power_el_kw" : list of float
            Electrical power values [kW].
        - "heat_flow_recovered_kw" : list of float
            Corresponding recovered heat values [kW].
    degree : int, optional
        Degree of the polynomial fit (default is 1, i.e. linear).

    Returns
    -------
    dict
        Dictionary with keys:
        - "degree" : int
            Polynomial degree used.
        - "coeff_HE" : list of float
            Polynomial coefficients for H(E).
        - "bounds" : dict
            Min/max bounds for E and H.
    """
    # data of the thermal (H) and electric (E) output
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
                               resol=900, degree=1, storage_cap=10000, q_bhp_max=2000):
    """
    Build and solve a Pyomo MINLP for CHP + heat pump + storage dispatch.

    The model decides on CHP electrical output, heat pump consumption,
    and storage charging/discharging to satisfy heat and electrical
    balances at minimum heat pump electricity use. The CHP thermal
    output is approximated by a polynomial fit of electrical power.

    Parameters
    ----------
    heat_demand : float
        Heat demand at the current timestep [kW].
    flex_demand : float
        Flexible electrical demand (e.g. load to be balanced) [kW].
    cop_bhp : float
        Coefficient of performance of the heat pump [-].
    soc : float
        Current state of charge of the thermal storage [0–1].
    chp_map : dict
        CHP performance map with electrical and thermal outputs.
    resol : int, optional
        Timestep resolution in seconds (default 900).
    degree : int, optional
        Degree of polynomial fit for CHP relation (default 1).
    storage_cap : float, optional
        Thermal storage capacity [kWh] (default 10000).
    q_bhp_max : float, optional
        Maximum thermal output of the heat pump [kW] (default 2000).

    Returns
    -------
    dict
        If feasible:
        - "p_el_bhp" : float
            Heat pump electrical consumption [kW].
        - "p_el_chp" : float
            CHP electrical output [kW].
        - "q_th_bhp" : float
            Heat pump thermal output [kW].
        - "q_th_chp" : float
            CHP thermal output [kW].
        - "soc" : float
            State of charge (unchanged).
        - "q_th_discharge" : float
            Storage discharge [kW].
        - "q_th_charge" : float
            Storage charge [kW].
        - "heat_demand" : float
            Heat demand satisfied [kW].
        - "y" : int
            CHP on/off status.
        - "el_balance" : float
            Value of electrical balance constraint.
        - "feasible" : bool
            True if optimization succeeded.
        Otherwise: {"feasible": False}.
    """
    fit = fit_chp_relations(chp_map, degree=degree)

    m = pyo.ConcreteModel()

    # Parameter
    m.heat_demand = pyo.Param(initialize=heat_demand)
    m.flex_demand = pyo.Param(initialize=flex_demand)
    m.cop_bhp     = pyo.Param(initialize=cop_bhp)
    m.q_th_bhp_max   = pyo.Param(initialize=q_bhp_max)
    m.soc         = pyo.Param(initialize=soc)
    m.storage_cap = pyo.Param(initialize=storage_cap)
    m.resol       = pyo.Param(initialize=resol)

    # decision variables for electrical input (BHP) and output (CHP)
    m.p_el_bhp  = pyo.Var(domain=pyo.NonNegativeReals)  # WP Stromverbrauch
    m.p_el_chp = pyo.Var(domain=pyo.NonNegativeReals)  # BHKW Strom

    # binary Variable for chp. To turn the chp of ig´f the load is out of bounds
    m.y_chp = pyo.Var(domain=pyo.Binary)

    # Bounds CHP
    p_el_min_chp = 0.2 * 700
    p_el_max_chp = 700

    #Bound Constraints CHP
    m.p_el_chp_min = pyo.Constraint(expr=m.p_el_chp >= p_el_min_chp * m.y_chp)
    m.p_el_chp_max = pyo.Constraint(expr=m.p_el_chp <= p_el_max_chp * m.y_chp)

    # variables thermal output
    m.q_th_bhp  = pyo.Var(domain=pyo.NonNegativeReals)  # WP Wärme
    m.q_th_chp = pyo.Var(domain=pyo.NonNegativeReals)

    ## Relation between thermal and electric ouput CHP
    # coefficient of the fit curve of thermal and electric output of the CHP
    coeff_HE = fit["coeff_HE"]
    M_chp = 5000  # Big-M

    #  Link q_th_chp to polynomial of p_el_chp only if CHP is on (y_chp = 1), relaxed otherwise
    m.q_th_chp_upper = pyo.Constraint(
        expr=m.q_th_chp <= poly_expr(coeff_HE, m.p_el_chp) + M_chp * (1 - m.y_chp)
    )
    m.q_th_chp_lower = pyo.Constraint(
        expr=m.q_th_chp >= poly_expr(coeff_HE, m.p_el_chp) - M_chp * (1 - m.y_chp)
    )

    # If the CHP is off (y=0) no thermal output is allowed.
    m.q_th_chp_off = pyo.Constraint(expr=m.q_th_chp <= M_chp * m.y_chp)

    ## Relation between thermal and electric ouput BHP
    m.q_th_bhp = pyo.Expression(expr= m.cop_bhp * m.p_el_bhp)

    # capacity bound for the BHP
    m.hp_cap = pyo.Constraint(expr=m.q_th_bhp <= m.q_th_bhp_max)

    # stoage variables
    m.q_th_charge    = pyo.Var(domain=pyo.NonNegativeReals)
    m.q_th_discharge = pyo.Var(domain=pyo.NonNegativeReals)

    # Binary-vriables storage
    m.y_charge = pyo.Var(domain=pyo.Binary)
    m.y_discharge = pyo.Var(domain=pyo.Binary)

    #allows to only charge or discharge the storage. Not both at the same time.
    m.charge_discharge = pyo.Constraint(expr=m.y_discharge + m.y_charge <= 1)

    #bounds for charging or discharging the storge dependend on the soc
    m.q_th_charge_max   = pyo.Constraint(expr=m.q_th_charge <= m.storage_cap * (1 - m.soc) * m.resol / 3600 * m.y_charge)
    m.q_th_discharge_max = pyo.Constraint(expr=m.q_th_discharge <= m.storage_cap * m.soc * m.resol / 3600 * m.y_discharge)

    # balances
    m.heat_bal = pyo.Constraint(expr=m.q_th_bhp + m.q_th_chp + m.q_th_discharge - m.q_th_charge == m.heat_demand)
    m.el_bal   = pyo.Constraint(expr=-m.p_el_bhp + m.p_el_chp + m.flex_demand == 0)

    # objective to minimize the electric power consumption of the whole system.
    m.obj = pyo.Objective(
        expr=m.p_el_bhp,
        sense=pyo.minimize
    )

    # Solver
    solver = pyo.SolverFactory('mindtpy')
    results = solver.solve(m, strategy='OA', mip_solver='glpk', nlp_solver='ipopt')

    if (results.solver.status == SolverStatus.ok and
        results.solver.termination_condition == TerminationCondition.optimal):
        return {
            "p_el_bhp": pyo.value(m.p_el_bhp),
            "p_el_chp": pyo.value(m.p_el_chp),
            "q_th_bhp": pyo.value(m.q_th_bhp),
            "q_th_chp": pyo.value(m.q_th_chp),
            "soc": pyo.value(m.soc),
            "q_th_discharge": pyo.value(m.q_th_discharge),
            "q_th_charge": pyo.value(m.q_th_charge),
            "heat_demand": pyo.value(m.heat_demand),
            "y":pyo.value(m.y_chp),
            "el_balance": pyo.value(m.el_bal),
            "feasible": True
        }
    else:
        return {"feasible": False}



