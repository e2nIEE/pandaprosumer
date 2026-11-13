"""
A producer at its maximum serving two heat demands, the second one returning hot water.

The producer cannot deliver all the mass flow its responders ask for: merit order serves the first
demand fully and the second one with what is left. Its return is the mix of the demands' returns
weighted by the flows it delivers, which itself depends on that return (a warmer return lets a
power-capped producer push more flow). Plain substitution on that fixed point slowed down as the
second return approached the feed and stopped with ``did not converge after 20 iterations`` (a
100 kW gas boiler, 95 kW to a 40 °C return, the rest to a 72 °C one, both fed at 80 °C). Gas boiler,
electric boiler, heat pump and heat exchanger shared that loop.
"""
import io
import contextlib

import numpy as np
import pandas as pd
import pytest

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer import (create_period, DFData, create_empty_prosumer_container,
                           create_controlled_const_profile,
                           create_controlled_gas_boiler,
                           create_controlled_electric_boiler,
                           create_controlled_heat_pump,
                           create_controlled_heat_exchanger,
                           create_controlled_heat_demand)

T_FEED_C = 80.
T_RETURN_1_C = 40.

# result columns: (thermal power, mass flow, return, feed)
COLUMNS = {
    "gas_boiler": ("q_kw", "mdot_kg_per_s", "t_in_c", "t_out_c"),
    "electric_boiler": ("q_kw", "mdot_kg_per_s", "t_in_c", "t_out_c"),
    "heat_pump": ("q_cond_kw", "mdot_cond_kg_per_s", "t_cond_in_c", "t_cond_out_c"),
    "heat_exchanger": ("q_exchanged_kw", "mdot_2_kg_per_s", "t_2_in_c", "t_2_out_c"),
}
# heat the producer delivers at most with a 40 °C return (the heat pump's depends on its COP)
MAX_Q_KW = {"gas_boiler": 100., "electric_boiler": 100., "heat_pump": 128.4, "heat_exchanger": 100.}


def _build(producer, t_return_2_c, q_1_kw, q_2_kw):
    prosumer = create_empty_prosumer_container()
    resol = 3600
    start = '2020-01-01 00:00:00'
    end = pd.Timestamp(start) + pd.Timedelta(seconds=resol) - pd.Timedelta("00:00:01")
    period = create_period(prosumer, resol, start, end, 'utc', 'default')
    data = pd.DataFrame({"q_1_kw": [q_1_kw], "q_2_kw": [q_2_kw], "t_source_c": [25. if producer == "heat_pump" else 95.]},
                        index=pd.date_range(start, end, freq=f'{resol}s', tz='utc'))
    cp = create_controlled_const_profile(prosumer, list(data.columns), list(data.columns), DFData(data), period, 0, 0)
    if producer == "gas_boiler":
        pr = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0, max_q_kw=100,
                                          efficiency_percent=100, heating_value_kj_per_kg=20e3)
    elif producer == "electric_boiler":
        pr = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0, max_p_kw=100)
    elif producer == "heat_pump":
        pr = create_controlled_heat_pump(prosumer, period=period, level=1, order=0, mode='carnot',
                                         carnot_efficiency=0.5, pinch_c=0, delta_t_evap_c=5, max_p_comp_kw=40)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="t_source_c",
                       responder_id=pr, responder_column="t_evap_in_c", order=2)
    else:
        pr = create_controlled_heat_exchanger(prosumer, period=period, level=1, order=0, max_q_kw=100,
                                              t_1_in_nom_c=95, t_1_out_nom_c=45, t_2_in_nom_c=40,
                                              t_2_out_nom_c=80, mdot_2_nom_kg_per_s=0.6)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="t_source_c",
                       responder_id=pr, responder_column="t_feed_in_c", order=2)
    hd_1 = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                         t_feed_demand_c=T_FEED_C, t_return_demand_c=T_RETURN_1_C)
    hd_2 = create_controlled_heat_demand(prosumer, period=period, level=1, order=2,
                                         t_feed_demand_c=T_FEED_C, t_return_demand_c=t_return_2_c)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q_1_kw",
                   responder_id=hd_1, responder_column="q_demand_kw", order=0)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q_2_kw",
                   responder_id=hd_2, responder_column="q_demand_kw", order=1)
    FluidMixMapping(container=prosumer, initiator_id=pr, responder_id=hd_1, order=0)
    FluidMixMapping(container=prosumer, initiator_id=pr, responder_id=hd_2, order=1)
    with contextlib.redirect_stderr(io.StringIO()):  # progress bar
        run_timeseries(prosumer, period, True)
    ts = prosumer.time_series
    return [ts.loc[i].data_source.df.iloc[0] for i in (0, 1, 2)]


@pytest.mark.parametrize("producer", list(COLUMNS))
@pytest.mark.parametrize("t_return_2_c", [72., 75., 78.])
@pytest.mark.parametrize("share_1", [.95, .99])
def test_capped_producer_serves_two_demands(producer, t_return_2_c, share_1):
    q_col, mdot_col, t_in_col, t_out_col = COLUMNS[producer]
    q_1_kw = share_1 * MAX_Q_KW[producer]
    q_2_kw = .2 * MAX_Q_KW[producer]
    pr, hd_1, hd_2 = _build(producer, t_return_2_c, q_1_kw, q_2_kw)

    # the producer falls short: the first demand is served, the second gets the rest
    assert hd_1.q_uncovered_kw == pytest.approx(0., abs=.05)
    assert hd_2.q_uncovered_kw > 1.
    assert hd_2.mdot_kg_per_s > 0.

    # FluidMix interface with two responders: feed, mass flow, return mix, heat
    assert hd_1.t_in_c == pytest.approx(pr[t_out_col], abs=1e-3)
    assert hd_2.t_in_c == pytest.approx(pr[t_out_col], abs=1e-3)
    mdot_kg_per_s = hd_1.mdot_kg_per_s + hd_2.mdot_kg_per_s
    assert pr[mdot_col] == pytest.approx(mdot_kg_per_s, rel=1e-6)
    t_return_mix_c = (hd_1.mdot_kg_per_s * hd_1.t_out_c + hd_2.mdot_kg_per_s * hd_2.t_out_c) / mdot_kg_per_s
    assert pr[t_in_col] == pytest.approx(t_return_mix_c, abs=.01)
    assert pr[q_col] == pytest.approx(hd_1.q_received_kw + hd_2.q_received_kw, rel=2e-3)
    if producer != "heat_pump":
        assert pr[q_col] == pytest.approx(MAX_Q_KW[producer], rel=1e-6)
    assert np.isfinite(pr.values.astype(float)).all()


def test_heat_exchanger_books_the_heat_its_demand_receives():
    """The exchanger's heat is the primary stream's m·cp·ΔT: with the primary flow sized on the heat capacity
    at the primary inlet and the heat booked with the capacity at the primary mean temperature, it booked
    0.45 % less than its single, uncapped demand received."""
    pr, hd_1, hd_2 = _build("heat_exchanger", 72., 30., 0.)
    assert hd_1.q_uncovered_kw == pytest.approx(0., abs=1e-6)
    assert hd_2.mdot_kg_per_s == 0.
    assert pr.q_exchanged_kw == pytest.approx(hd_1.q_received_kw, rel=1e-6)
