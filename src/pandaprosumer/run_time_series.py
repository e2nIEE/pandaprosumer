import pandas as pd
import tqdm

from pandapower.control import get_controller_order
from pandapower.create import _get_multiple_index_with_check
from pandapower.timeseries import DFData
from pandapower.timeseries.run_time_series import run_loop
from pandaprosumer2.run_control import run_control, prepare_run_ctrl

try:
    import pandaplan.core.pplog as pplog
except ImportError:
    import logging as pplog

logger = pplog.getLogger(__name__)
logger.setLevel(level=pplog.WARNING)


def run_timeseries(prosumer, period_index, verbose=True):
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
    pass


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
