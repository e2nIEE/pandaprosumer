"""
One transient network state per time step (pandaprosumer.energy_system.timeseries.step_pipeflow).

pandapipes 0.12 copies the current temperatures into the "old" state on EVERY transient pipeflow call, so the
several solves of one time step (one per control level) each advanced the network by dt. `StepPipeflow` makes
every solve of a step restart from the end of the previous step, and skips a solve whose inputs did not change.
"""
import pandapipes
import pandas as pd

from pandaprosumer import create_period
from pandaprosumer.energy_system import create_empty_energy_system, add_net_to_energy_system
from pandaprosumer.energy_system.timeseries import run_time_series_energy_system as run_module
from pandaprosumer.energy_system.timeseries.step_pipeflow import (
    HEAT_BALANCE_TABLE, HEAT_LOSS_COLUMN, StepPipeflow, create_heat_balance_table, pipe_heat_loss_w)


def _pipe_net():
    net = pandapipes.create_empty_network(fluid="water", name="net_pipes")
    j0, j1, r1, r0 = (pandapipes.create_junction(net, pn_bar=6, tfluid_k=358.15) for _ in range(4))
    pandapipes.create_circ_pump_const_pressure(net, flow_junction=j0, return_junction=r0, p_flow_bar=6,
                                               plift_bar=1, t_flow_k=358.15, type="pt")
    for a, b in ((j0, j1), (r1, r0)):
        pandapipes.create_pipe_from_parameters(net, a, b, length_km=2, diameter_m=0.2, k_mm=0.01,
                                               u_w_per_m2k=0.4, text_k=283.15)
    pandapipes.create_heat_consumer(net, j1, r1, qext_w=300e3, controlled_mdot_kg_per_s=10)
    pandapipes.set_user_pf_options(net, mode="bidirectional", transient=True, dt=3600, ambient_temperature=283.15)
    pandapipes.pipeflow(net, transient=False)
    return net


def _solve(run, net, step):
    run(net, transient=True, dt=3600, simulation_time_step=step)


def test_every_solve_of_a_step_starts_from_the_end_of_the_previous_step():
    once, twice = _pipe_net(), _pipe_net()
    run_once, run_twice = StepPipeflow(), StepPipeflow()
    for net, run in ((once, run_once), (twice, run_twice)):
        _solve(run, net, 0)
        _solve(run, net, 1)
    # step 2: one net is solved with a provisional supply temperature first, then with the final one
    twice.circ_pump_pressure.t_flow_k = 340.0
    _solve(run_twice, twice, 2)
    twice.circ_pump_pressure.t_flow_k = 350.0
    _solve(run_twice, twice, 2)
    once.circ_pump_pressure.t_flow_k = 350.0
    _solve(run_once, once, 2)
    # the provisional solve left no trace: the step was integrated once, from the end of step 1
    for table in ("res_junction", "res_pipe", "res_circ_pump_pressure"):
        pd.testing.assert_frame_equal(once[table], twice[table], rtol=1e-9, atol=1e-9)


def test_a_solve_with_unchanged_inputs_is_skipped_within_a_step_only():
    net, run = _pipe_net(), StepPipeflow()
    _solve(run, net, 0)
    _solve(run, net, 1)
    solved = run.solves
    _solve(run, net, 1)  # nothing changed: the results are already there
    assert run.solves == solved
    net.circ_pump_pressure.t_flow_k = 358.15 - 1e-9  # float noise is not a change
    _solve(run, net, 1)
    assert run.solves == solved
    _solve(run, net, 2)  # same inputs, but time moved on
    assert run.solves == solved + 1


def test_the_heat_balance_table_reports_the_pipe_losses_of_the_latest_solve():
    net, run = _pipe_net(), StepPipeflow()
    create_heat_balance_table(net)
    _solve(run, net, 0)
    loss_w = net[HEAT_BALANCE_TABLE].at[0, HEAT_LOSS_COLUMN]
    assert loss_w == pipe_heat_loss_w(net)
    # 4 km of DN200 at 0.4 W/m2K, ~75 K above the ground: about 75 kW
    assert 50e3 < loss_w < 100e3


def _energy_system(net):
    energy_system = create_empty_energy_system(name="test_energy_system")
    create_period(energy_system, 3600, "2020-01-01 00:00:00", "2020-01-01 02:00:00", timezone="utc", name="period")
    add_net_to_energy_system(energy_system, net, net_name=net.name)
    return energy_system


def _captured_net_settings(monkeypatch, net, **kwargs):
    captured = {}
    monkeypatch.setattr(run_module, "run_loop", lambda energy_system, ts_variables, **_:
                        captured.update(ts_variables["nets"]))
    run_module.run_timeseries(_energy_system(net), 0, verbose=False, **kwargs)
    return captured[net.name]


def test_run_timeseries_solves_a_pre_solved_pandapipes_net_with_a_step_pipeflow_and_no_initial_run(monkeypatch):
    settings = _captured_net_settings(monkeypatch, _pipe_net(), transient=True, dt=3600)
    assert isinstance(settings["run"], StepPipeflow)
    assert settings["initial_run"] is False


def test_run_timeseries_keeps_the_initial_run_of_a_never_solved_net(monkeypatch):
    net = _pipe_net()
    net.pop("_pit")
    net.converged = False
    settings = _captured_net_settings(monkeypatch, net)
    assert isinstance(settings["run"], StepPipeflow)
    assert settings["initial_run"] is True


def test_run_timeseries_keeps_the_plain_pipeflow_on_request(monkeypatch):
    settings = _captured_net_settings(monkeypatch, _pipe_net(), step_pipeflow=False)
    assert settings["run"] is pandapipes.pipeflow
    assert settings["initial_run"] is True
