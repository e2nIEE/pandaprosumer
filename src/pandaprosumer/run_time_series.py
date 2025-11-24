import pandas as pd
import tqdm

from pandapower.control import get_controller_order
from pandapower.create import _get_multiple_index_with_check
from pandapower.timeseries import DFData

# from pandapower.timeseries.run_time_series import (print_progress, control_time_step, controller_not_converged,
#                                                    pf_not_converged, finalize_step)

from pandapower.timeseries.run_time_series import print_progress, run_time_step, _call_output_writer

from pandaprosumer.run_control import run_control, prepare_run_ctrl



try:
    import pandaplan.core.pplog as pplog
except ImportError:
    import logging as pplog

logger = pplog.getLogger(__name__)
logger.setLevel(level=pplog.WARNING)



def run_loop(net, ts_variables, run_control_fct=run_control, output_writer_fct=_call_output_writer,
             check_results_fct=None, **kwargs):
    """
    runs the time series loop which calls runpp (or another run function) in each iteration

    Parameters
    ----------
    net - pandapower net
    ts_variables - settings for time series

    """
    for i, time_step in enumerate(ts_variables["time_steps"]):
        print_progress(i, time_step, ts_variables["time_steps"], ts_variables["verbose"], ts_variables=ts_variables, **kwargs)
        if "transient" in kwargs:
            kwargs["simulation_time_step"] = i

        net.rerun = False
        run_time_step(net, time_step, ts_variables, run_control_fct, output_writer_fct, **kwargs)

        if check_results_fct is not None:
            rerun_time_step = check_results_fct(net, time_step)
        else:
            rerun_time_step = False

        if rerun_time_step:
            net.rerun = True
            run_time_step(net, time_step, ts_variables, run_control_fct, output_writer_fct, **kwargs)


def run_timeseries(prosumer, period_index=0, verbose=True, check_results_fct=None):

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

# def run_loop(prosumer, ts_variables, run_control_fct=run_control, output_writer_fct=output_writer_fct,
#              check_results_fct=None, **kwargs):
#     """
#     runs the time series loop which calls pp.runpp (or another run function) in each iteration.
#     After the initial run there is the option to rerun the timestep. Based on the result of the function check_results
#
#     Parameters
#     ----------
#     prosumer - pandaprosumer prosumer
#     ts_variables - settings for time series
#
#     """
#     for i, time_step in enumerate(ts_variables["time_steps"]):
#         print_progress(i, time_step, ts_variables["time_steps"], ts_variables["verbose"], ts_variables=ts_variables,
#                            **kwargs)
#         prosumer.rerun = False
#         run_time_step(prosumer, time_step, ts_variables, run_control_fct, output_writer_fct, **kwargs)
#
#         if check_results_fct is not None:
#             rerun_time_step = check_results_fct(prosumer, time_step)
#         else:
#             rerun_time_step = False
#
#         if rerun_time_step:
#             prosumer.rerun = True
#             run_time_step(prosumer, time_step, ts_variables, run_control_fct, output_writer_fct, **kwargs)
#
#
# def run_time_step(prosumer, time_step, ts_variables, run_control_fct=run_control, output_writer_fct=output_writer_fct,
#                   **kwargs):
#     """
#     Time Series step function
#     Is called to run the PANDAPOWER AC power flows with the timeseries module
#
#     INPUT:
#         **net** - The pandapower format network
#
#         **time_step** (int) - time_step to be calculated
#
#         **ts_variables** (dict) - contains settings for controller and time series simulation. See init_time_series()
#     """
#     ctrl_converged = True
#     pf_converged = True
#     # run time step function for each controller
#
#     control_time_step(ts_variables['controller_order'], time_step)
#
#     try:
#         # calls controller init, control steps and run function (runpp usually is called in here)
#         run_control_fct(prosumer, ctrl_variables=ts_variables, **kwargs)
#     except ControllerNotConverged:
#         ctrl_converged = False
#         # If controller did not converge do some stuff
#         controller_not_converged(time_step, ts_variables)
#     except ts_variables['errors']:
#         # If power flow did not converge simulation aborts or continues if continue_on_divergence is True
#         pf_converged = False
#         pf_not_converged(time_step, ts_variables)
#
#     output_writer_fct(prosumer, time_step, pf_converged, ctrl_converged, ts_variables)
#
#     finalize_step(ts_variables['controller_order'], time_step)





