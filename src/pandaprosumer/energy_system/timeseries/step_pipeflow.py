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
import math

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


def _array_bytes(values):
    """Bytes standing for one column (or index) of a component table: raw numbers, floats rounded."""
    if values.dtype.kind == "f":  # + 0.0 turns -0.0 into 0.0
        return (np.round(values, FINGERPRINT_DECIMALS) + 0.0).tobytes()
    if values.dtype.kind in "biumM":
        return values.tobytes()
    # names, fluids...: the digest only lives for the run, so the per-process string hash is enough
    return hash(tuple(values.tolist())).to_bytes(8, "little", signed=True)


def _input_fingerprint(net):
    """
    Digest of every pipeflow input of the net (the declared input columns of each component table).

    Called before every pipeflow, so it hashes the columns' numpy buffers directly: hashing the tables with
    `pd.util.hash_pandas_object` cost about a sixth of a whole coupled run.
    """
    digest = hashlib.sha1()
    try:
        for component in net.component_list:
            table = net[component.table_name()]
            digest.update(component.table_name().encode())
            digest.update(_array_bytes(table.index.to_numpy()))
            for name, _ in component.get_component_input():
                if name in table.columns:
                    values = table[name].to_numpy()
                    digest.update(f"{name}:{values.dtype.str}".encode())
                    digest.update(_array_bytes(values))
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

    def __init__(self, step_s=None):
        """
        :param step_s: length of a time step of the run (s). Given, a net whose own `dt` (its user pipeflow option)
            is shorter is solved `step_s / dt` times per time step (sub-steps), so the water moves through its pipes
            in finer steps; its results are the state at the end of the step and its pipe losses the mean over the
            step. Left out, every solve advances the net by the `dt` it is called with, once per step.
        """
        self.step_s = step_s
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
        substeps, dt_s = self._substeps(net, kwargs) if transient else (1, None)
        loss_w = 0.0
        for substep in range(substeps):
            if transient and dt_s is not None:
                # pandapipes advances the net by dt from its current state on every transient call
                kwargs = {**kwargs, "dt": dt_s, "simulation_time_step": step * substeps + substep + 1}
            pandapipes.pipeflow(net, **kwargs)
            if HEAT_BALANCE_TABLE in net:
                loss_w += pipe_heat_loss_w(net)
        self.solves += 1
        self.solved_fingerprint = fingerprint
        if HEAT_BALANCE_TABLE in net:
            net[HEAT_BALANCE_TABLE].loc[0, HEAT_LOSS_COLUMN] = loss_w / substeps

    def _substeps(self, net, kwargs):
        """
        (sub-steps per time step, their length in s) for the net, or (1, None) to keep the caller's `dt`.

        The net's own `dt` (``set_user_pf_options(net, dt=...)``) sets the sub-step; the time step is cut into a
        whole number of equal sub-steps no longer than it.
        """
        if not self.step_s:
            return 1, None
        own_dt = (net.get("user_pf_options") or {}).get("dt") or kwargs.get("dt")
        if not own_dt or own_dt >= self.step_s:
            return 1, float(self.step_s)
        substeps = math.ceil(self.step_s / own_dt - 1e-9)
        return substeps, self.step_s / substeps
