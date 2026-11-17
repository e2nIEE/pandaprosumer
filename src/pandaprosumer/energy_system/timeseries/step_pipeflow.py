"""
One transient network state per time step for the pandapipes nets of an energy system.

`run_timeseries` runs a pipeflow for every control level that holds a network controller, plus an initial run
per step. In transient mode each pipeflow call takes the network's current temperatures as the state of the
previous time step (pandapipes copies `TOUTINIT` into `T_OUT_OLD`), so N pipeflows in one step advanced the
network by N x dt: the heat stored in the pipes, and the time the water takes to travel, were N times too short.

`StepPipeflow` makes every solve of step t start from the state the network had at the end of step t - 1,
and skips a solve whose inputs did not change since the last solve of the same step.

The first step is transient too: it starts from the steady state the net holds when the run begins (usually
solved at the supply setpoint and initial demands). pandapipes would otherwise solve step 0 as a steady state,
which does not exist when the plant is too small: the network would start the period already cold.

The proper fix belongs to pandapipes (advance the state only when `simulation_time_step` changes, not on every
call); this is the practical place to do it until then.
"""

import copy
import hashlib

import numpy as np
import pandapipes
import pandas as pd
from pandapipes.idx_branch import ALPHA, LENGTH, TEXT, TOUTINIT, D
from pandapipes.pf.pipeflow_setup import get_lookup

# Inputs are compared at this many decimals: a plant reaching its setpoint writes e.g. 358.149999995 K for
# 358.15 K, which is the same input and must not cost another pipeflow.
FINGERPRINT_DECIMALS = 6

# One-row result table of a pandapipes net, to log with its OutputWriter: the heat its pipes lose to the
# ground in the step (W), every pipe section included. It closes the network's heat balance (pump heat =
# substations' heat + losses + change of the heat stored in the pipes), which pandapipes does not report.
HEAT_BALANCE_TABLE = "res_heat_balance"
HEAT_LOSS_COLUMN = "heat_loss_w"


def create_heat_balance_table(net):
    """
    Add the heat-balance result table to `net` (filled by `StepPipeflow` after each solve).

    Log it with `output_writer.log_variable(HEAT_BALANCE_TABLE, HEAT_LOSS_COLUMN, index=[0])`.
    """
    net[HEAT_BALANCE_TABLE] = pd.DataFrame({HEAT_LOSS_COLUMN: [0.0]})


def pipe_heat_loss_w(net):
    """Heat lost by all the pipes of the latest solve (W), from pandapipes' internal tables (all sections)."""
    lookup = get_lookup(net, "branch", "from_to")
    if "pipe" not in lookup:
        return 0.0
    start, end = lookup["pipe"]
    pipes = net["_pit"]["branch"][start:end]
    return float((pipes[:, ALPHA] * np.pi * pipes[:, D] * pipes[:, LENGTH] * (pipes[:, TOUTINIT] - pipes[:, TEXT])).sum())


def _input_fingerprint(net):
    """Digest of every pipeflow input of the net (the declared input columns of each component table)."""
    digest = hashlib.sha1()
    try:
        for component in net.component_list:
            table = net[component.table_name()]
            columns = [name for name, _ in component.get_component_input() if name in table.columns]
            inputs = table[columns].round(FINGERPRINT_DECIMALS)
            digest.update(component.table_name().encode())
            digest.update(pd.util.hash_pandas_object(inputs, index=True).to_numpy().tobytes())
    except TypeError:  # an unhashable cell: never skip a solve
        return None
    return digest.digest()


class StepPipeflow:
    """
    Pipeflow run function for one pandapipes net, to pass as the net's `run` in the control variables.

    In a transient run, the first solve of a time step keeps a copy of the internal tables as they were at
    the end of the previous step; any further solve of the same step restarts from that copy, so the step
    is integrated over dt exactly once whatever the number of solves. A call whose inputs are the ones of
    the step's last solve returns at once: its results are already in the result tables.
    """

    def __init__(self):
        self.step = None
        self.step_start_pit = None
        self.solved_fingerprint = None
        self.solves = 0

    def __call__(self, net, **kwargs):
        """Solve the net for the step in `kwargs['simulation_time_step']` (or skip the solve, see the class)."""
        step = kwargs.get("simulation_time_step")
        transient = bool(kwargs.get("transient", False)) and step is not None and "_pit" in net
        if transient:  # pandapipes solves its step 0 as a steady state: number the steps from 1
            kwargs = {**kwargs, "simulation_time_step": step + 1}
        fingerprint = _input_fingerprint(net)
        if step != self.step:
            self.step = step
            self.solved_fingerprint = None
            self.step_start_pit = copy.deepcopy(net["_pit"]) if transient else None
        elif fingerprint is not None and fingerprint == self.solved_fingerprint and net.converged:
            return
        elif self.step_start_pit is not None:
            net["_pit"] = copy.deepcopy(self.step_start_pit)
        pandapipes.pipeflow(net, **kwargs)
        self.solves += 1
        self.solved_fingerprint = fingerprint
        if HEAT_BALANCE_TABLE in net:
            net[HEAT_BALANCE_TABLE].loc[0, HEAT_LOSS_COLUMN] = pipe_heat_loss_w(net)
