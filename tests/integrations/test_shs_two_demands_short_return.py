"""
A stratified tank whose delivered flow differs from what its two heat demands ask for.

Like a capped producer, the tank's return is then the mix of the demands' returns weighted by the
flows it delivers, a fixed point. The tank's loop stopped at a 1 K step (booked returns 0.15 K off the
mix) and had no iteration cap: when the delivered flow jumped with the assumed return, substitution
cycled between the two sides forever, and a secant step outside the demands' returns drove the layers
below 0 °C. It now shares the producers' :class:`ReturnTemperatureSolver`.

The jump itself was the loop's own doing: each pass handed the next one the plug-flow outlet
temperature of the previous pass as the top-layer temperature, so the discharge sizing switched
between its mixing formula and its energy formula every pass (0.01 kg/s against 0.5 kg/s for a 0.05 K
change of the return, 9 kW off the balance). Every pass now starts from the tank's initial state.

A tank delivering MORE than asked (a full tank bypassing a source held at its minimum) dumps the
surplus on the last demand, and its return is the mix for the flows it delivers as well: booked at the
mix of the demanded flows, 10 kW of a 50 kW bypass vanished between the tank and its demands.
"""
import io
import contextlib

import numpy as np
import pandas as pd
import pytest

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.controller.models.stratified_heat_storage import StratifiedHeatStorageController
from pandaprosumer import (create_period, DFData, create_empty_prosumer_container,
                           create_controlled_const_profile, create_controlled_gas_boiler,
                           create_controlled_stratified_heat_storage, create_controlled_heat_demand)

T_FEED_C = 78.
T_RETURN_1_C = 40.
T_RETURN_2_C = 60.
#: passes of the tank's calculation in one control step beyond which the loop is taken as cycling
MAX_PASSES_PER_STEP = 50


@pytest.fixture
def bounded_shs_loop(monkeypatch):
    """Fail instead of hanging when the tank's rerun loop cycles."""
    calculate = StratifiedHeatStorageController._calculate_heat_storage
    control_step = StratifiedHeatStorageController.control_step
    passes = {"n": 0}

    def counted_calculate(self, *args, **kwargs):
        passes["n"] += 1
        if passes["n"] > MAX_PASSES_PER_STEP:
            raise AssertionError(f"SHS rerun loop still running after {MAX_PASSES_PER_STEP} passes")
        return calculate(self, *args, **kwargs)

    def counted_control_step(self, prosumer):
        passes["n"] = 0
        return control_step(self, prosumer)

    monkeypatch.setattr(StratifiedHeatStorageController, "_calculate_heat_storage", counted_calculate)
    monkeypatch.setattr(StratifiedHeatStorageController, "control_step", counted_control_step)


def _build(q_1_kw, q_2_kw, max_q_kw=1., min_q_kw=np.nan, init_layer_temps_c=None):
    prosumer = create_empty_prosumer_container()
    resol = 900
    start = '2020-01-01 00:00:00'
    end = pd.Timestamp(start) + pd.Timedelta(seconds=resol) - pd.Timedelta("00:00:01")
    period = create_period(prosumer, resol, start, end, 'utc', 'default')
    data = pd.DataFrame({"q_1_kw": [q_1_kw], "q_2_kw": [q_2_kw]},
                        index=pd.date_range(start, end, freq=f'{resol}s', tz='utc'))
    cp = create_controlled_const_profile(prosumer, list(data.columns), list(data.columns), DFData(data), period, 0, 0)
    gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0, max_q_kw=max_q_kw, min_q_kw=min_q_kw,
                                      efficiency_percent=100, heating_value_kj_per_kg=20e3)
    n_layers = 20
    if init_layer_temps_c is None:
        init_layer_temps_c = list(np.linspace(40, 85, n_layers))
    shs = create_controlled_stratified_heat_storage(prosumer, tank_height_m=1.0, tank_internal_radius_m=0.4,
                                                    n_layers=n_layers, min_useful_temp_c=76.,
                                                    init_layer_temps_c=init_layer_temps_c,
                                                    t_charge_target_c=85., period=period, level=1, order=1)
    hd_1 = create_controlled_heat_demand(prosumer, period=period, level=1, order=2,
                                         t_feed_demand_c=T_FEED_C, t_return_demand_c=T_RETURN_1_C)
    hd_2 = create_controlled_heat_demand(prosumer, period=period, level=1, order=3,
                                         t_feed_demand_c=T_FEED_C, t_return_demand_c=T_RETURN_2_C)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q_1_kw",
                   responder_id=hd_1, responder_column="q_demand_kw", order=0)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q_2_kw",
                   responder_id=hd_2, responder_column="q_demand_kw", order=1)
    FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=shs, order=0)
    FluidMixMapping(container=prosumer, initiator_id=shs, responder_id=hd_1, order=0)
    FluidMixMapping(container=prosumer, initiator_id=shs, responder_id=hd_2, order=1)
    with contextlib.redirect_stderr(io.StringIO()):  # progress bar
        run_timeseries(prosumer, period, True)
    ts = prosumer.time_series
    return [ts.loc[i].data_source.df.iloc[0] for i in (0, 1, 2, 3)]


def _mixed_return_c(hd_1, hd_2):
    return ((hd_1.mdot_kg_per_s * hd_1.t_out_c + hd_2.mdot_kg_per_s * hd_2.t_out_c)
            / (hd_1.mdot_kg_per_s + hd_2.mdot_kg_per_s))


def _assert_tank_consistent_with_its_demands(shs, hd_1, hd_2):
    """FluidMix interface with two responders: mass flow, return mix and heat agree."""
    assert shs.mdot_delivered_kg_per_s == pytest.approx(hd_1.mdot_kg_per_s + hd_2.mdot_kg_per_s, rel=1e-6)
    assert shs.t_delivered_in_c == pytest.approx(_mixed_return_c(hd_1, hd_2), abs=.01)
    assert shs.q_delivered_kw == pytest.approx(hd_1.q_received_kw + hd_2.q_received_kw, rel=2e-3)


def test_short_tank_books_the_mixed_return(bounded_shs_loop):
    """Delivered flow continuous in the return: the booked return is the mix to within 0.01 K."""
    _, shs, hd_1, hd_2 = _build(20., 5.)
    assert hd_2.q_uncovered_kw > .01  # the tank is (slightly) short: the second demand gets the rest
    _assert_tank_consistent_with_its_demands(shs, hd_1, hd_2)


@pytest.mark.parametrize("q_1_kw, q_2_kw", [(50., 50.), (20., 50.)])
def test_nearly_spent_tank_books_the_mixed_return(bounded_shs_loop, q_1_kw, q_2_kw):
    """The tank drains over the step (outlet colder than its top layer): the loop ends on the fixed point,
    not on a jump of its own making."""
    _, shs, hd_1, hd_2 = _build(q_1_kw, q_2_kw)
    assert hd_1.q_uncovered_kw > 1.  # the tank is far short: even the first demand is not served
    assert shs.t_delivered_out_c < shs.t_discharge_out_c + 1.  # drawn well below the 85 °C top
    assert T_RETURN_1_C <= shs.t_delivered_in_c <= T_RETURN_2_C
    _assert_tank_consistent_with_its_demands(shs, hd_1, hd_2)


def test_full_tank_dumping_a_surplus_books_the_mixed_return(bounded_shs_loop):
    """A full tank bypasses a boiler held at 50 kW for 25 kW of demand: the surplus goes to the second
    demand, and the tank's return (hence the boiler's) is the mix for the flows actually delivered."""
    gb, shs, hd_1, hd_2 = _build(20., 5., max_q_kw=100., min_q_kw=50., init_layer_temps_c=[85.] * 20)
    assert gb.q_kw == pytest.approx(50., rel=1e-6)
    assert shs.q_charge_kw == pytest.approx(0., abs=.01)
    assert hd_2.q_uncovered_kw < -10.  # over-served with the surplus
    assert shs.mdot_delivered_kg_per_s > 1.5 * (20. + 5.) / (4.19 * (T_FEED_C - T_RETURN_1_C))
    _assert_tank_consistent_with_its_demands(shs, hd_1, hd_2)
    assert gb.t_in_c == pytest.approx(_mixed_return_c(hd_1, hd_2), abs=.01)
    assert gb.q_kw == pytest.approx(shs.q_received_kw, rel=1e-3)
