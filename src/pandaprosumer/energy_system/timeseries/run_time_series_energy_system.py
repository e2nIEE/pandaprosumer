import pandas as pd
import tqdm

from pandapipes import pandapipesNet
from pandapipes.multinet.timeseries.run_time_series_multinet import _call_output_writer
from pandapipes.timeseries.run_time_series import init_default_outputwriter as init_output_writer_pps
from pandapower import pandapowerNet
from pandapower.control import control_diagnostic
from pandapower.timeseries.run_time_series import init_default_outputwriter as init_output_writer_pp
from pandapower.timeseries.run_time_series import run_loop, get_recycle_settings, init_output_writer
from pandaprosumer.energy_system.control.run_control_energy_system import prepare_run_ctrl, run_control
from pandaprosumer.run_time_series import control_diagnostic_pandaprosumer
from pandaprosumer.run_time_series import time_series_initialization, time_series_finalization

try:
    import pandaplan.core.pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)
logger.setLevel(level=logging.WARNING)


def run_timeseries(energy_system, period_index, continue_on_divergence=False, verbose=True):
    start = energy_system.period.at[period_index, 'start']
    end = energy_system.period.at[period_index, 'end']
    resol = int(energy_system.period.at[period_index, 'resolution_s'])
    tz = energy_system.period.at[period_index, 'timezone']
    dur = pd.date_range(start, end, freq='%ss' % resol, tz=tz)

    ts_variables = init_time_series(energy_system, dur, continue_on_divergence, verbose)

    for net_name in energy_system['nets'].keys():
        control_diagnostic(energy_system['nets'][net_name])
    #for pros_name in energy_system['prosumer'].keys():
    #    control_diagnostic_pandaprosumer(energy_system['prosumer'][pros_name], start, end, resol)
    time_series_initialization(ts_variables['controller_order'])
    run_loop(energy_system, ts_variables, output_writer_fct=_call_output_writer,
             run_control_fct=run_control)
    time_series_finalization(ts_variables['controller_order'])


def init_time_series(energy_system, time_steps, continue_on_divergence=False, verbose=True,
                     **kwargs):
    """
    Initializes the time series calculation.
    Besides it creates the dict ts_variables, which includes necessary variables for the time series / control loop.

    :param multinet: multinet with multinet controllers, net distinct controllers and several pandapipes/pandapower nets
    :type multinet: pandapipes.Multinet
    :param time_steps: the number of times a time series calculation shall be conducted
    :type time_steps: sequence of array_like
    :param continue_on_divergence: What to do if loadflow/pipeflow is not converging, fires control_repair
    :type continue_on_divergence: bool, default: False
    :param verbose: prints progess bar or logger debug messages
    :type verbose: bool, default: True
    :param kwargs: additional keyword arguments handed to each run function
    :type kwargs: dict
    :return: ts_variables which contains all relevant information and boundaries required for time series and
    control analyses
    :rtype: dict
    """
    run = kwargs.get('run', None)

    ts_variables = prepare_run_ctrl(energy_system, None, **kwargs)

    for net_name in energy_system['nets'].keys():
        net = energy_system['nets'][net_name]
        if isinstance(net, pandapowerNet):
            init_output_writer_pp(net, time_steps, **kwargs)
        elif isinstance(net, pandapipesNet):
            init_output_writer_pps(net, time_steps, **kwargs)
        else:
            raise ValueError('Some of the given nets are neither pandapipes nor pandapower nets')
        recycle_options = None
        if hasattr(run, "__name__") and run.__name__ == "runpp":
            # use faster runpp options if possible
            recycle_options = get_recycle_settings(net, **kwargs)
        ts_variables['nets'][net_name]['run'] = run[net_name] if run is not None else ts_variables['nets'][net_name][
            'run']
        ts_variables['nets'][net_name]['recycle_options'] = recycle_options
        init_output_writer(net, time_steps)

    # time steps to be calculated (list or range)
    ts_variables["time_steps"] = time_steps
    # If True, a diverged run is ignored and the next step is calculated
    ts_variables["continue_on_divergence"] = continue_on_divergence
    # print settings
    ts_variables["verbose"] = verbose

    if logger.level != 10 and verbose:
        # simple progress bar
        ts_variables['progress_bar'] = tqdm.tqdm(total=len(time_steps))

    return ts_variables
