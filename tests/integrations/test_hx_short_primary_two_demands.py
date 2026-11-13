"""
A heat exchanger short of primary flow, serving two heat demands.

Fed less primary flow than its secondary asks for, the exchanger keeps the secondary outlet it was asked
and delivers the secondary flow that primary can heat to it: the inverse of its forward calculation,
continuous with it (a boiler 0.03 % short leaves the second demand 0.01 % uncovered). Merit order serves
the first demand and gives the second what is left; the return the exchanger books is the mix for the
flows it delivers, like the capped producers and the tank.

Before, the exchanger kept the primary outlet of its forward solution and solved the LMTD for the
secondary outlet with the heat the primary carried to it: a colder outlet with more flow than asked
(2 K colder, 9 % more flow for a boiler 0.03 % short), the surplus split equally over the demands after
the exchanger's loop while the return it booked stayed the mix for the demanded flows (0.3 K off the mix,
1 kW between the exchanger and its demands), and the secondary flow sized with the heat capacity at the
secondary inlet while the demands book with the capacity at their mean temperature (0.15 %).
"""
import io
import contextlib

import numpy as np
import pandas as pd
import pytest

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer import (create_period, DFData, create_empty_prosumer_container,
                           create_controlled_const_profile, create_controlled_gas_boiler,
                           create_controlled_heat_exchanger, create_controlled_heat_demand)

T_FEED_C = 80.
T_RETURN_1_C = 40.
T_RETURN_2_C = 60.


def _build(max_q_kw, q_1_kw, q_2_kw):
    prosumer = create_empty_prosumer_container()
    resol = 3600
    start = '2020-01-01 00:00:00'
    end = pd.Timestamp(start) + pd.Timedelta(seconds=resol) - pd.Timedelta("00:00:01")
    period = create_period(prosumer, resol, start, end, 'utc', 'default')
    data = pd.DataFrame({"q_1_kw": [q_1_kw], "q_2_kw": [q_2_kw]},
                        index=pd.date_range(start, end, freq=f'{resol}s', tz='utc'))
    cp = create_controlled_const_profile(prosumer, list(data.columns), list(data.columns), DFData(data), period, 0, 0)
    gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0, max_q_kw=max_q_kw,
                                      efficiency_percent=100, heating_value_kj_per_kg=20e3)
    hx = create_controlled_heat_exchanger(prosumer, period=period, level=1, order=1, max_q_kw=1000,
                                          t_1_in_nom_c=95, t_1_out_nom_c=45, t_2_in_nom_c=40, t_2_out_nom_c=80,
                                          mdot_2_nom_kg_per_s=0.6)
    hd_1 = create_controlled_heat_demand(prosumer, period=period, level=1, order=2,
                                         t_feed_demand_c=T_FEED_C, t_return_demand_c=T_RETURN_1_C)
    hd_2 = create_controlled_heat_demand(prosumer, period=period, level=1, order=3,
                                         t_feed_demand_c=T_FEED_C, t_return_demand_c=T_RETURN_2_C)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q_1_kw",
                   responder_id=hd_1, responder_column="q_demand_kw", order=0)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q_2_kw",
                   responder_id=hd_2, responder_column="q_demand_kw", order=1)
    FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=hx, order=0)
    FluidMixMapping(container=prosumer, initiator_id=hx, responder_id=hd_1, order=0)
    FluidMixMapping(container=prosumer, initiator_id=hx, responder_id=hd_2, order=1)
    with contextlib.redirect_stderr(io.StringIO()):  # progress bar
        run_timeseries(prosumer, period, True)
    ts = prosumer.time_series
    return [ts.loc[i].data_source.df.iloc[0] for i in (0, 1, 2, 3)]


def _mixed_return_c(hd_1, hd_2):
    return ((hd_1.mdot_kg_per_s * hd_1.t_out_c + hd_2.mdot_kg_per_s * hd_2.t_out_c)
            / (hd_1.mdot_kg_per_s + hd_2.mdot_kg_per_s))


def _assert_consistent_along_the_chain(gb, hx, hd_1, hd_2):
    """Both FluidMix interfaces: feed, mass flow, return mix and heat agree."""
    assert hd_1.t_in_c == pytest.approx(hx.t_2_out_c, abs=1e-3)
    assert hd_2.t_in_c == pytest.approx(hx.t_2_out_c, abs=1e-3)
    assert hx.mdot_2_kg_per_s == pytest.approx(hd_1.mdot_kg_per_s + hd_2.mdot_kg_per_s, rel=1e-6)
    assert hx.t_2_in_c == pytest.approx(_mixed_return_c(hd_1, hd_2), abs=.01)
    assert hx.q_exchanged_kw == pytest.approx(hd_1.q_received_kw + hd_2.q_received_kw, rel=1e-3)
    assert gb.mdot_kg_per_s == pytest.approx(hx.mdot_1_kg_per_s, rel=1e-6)
    assert gb.t_in_c == pytest.approx(hx.t_1_out_c, abs=.01)
    assert gb.q_kw == pytest.approx(hx.q_exchanged_kw, rel=1e-3)
    assert np.isfinite(hx.values.astype(float)).all()


def test_exchanger_barely_short_of_primary_is_barely_short_of_secondary():
    """The boiler's 80 kW is 0.03 % short of the primary flow the demands' 80 kW need: the exchanger keeps the
    outlet asked, serves the first demand and leaves the second barely uncovered, continuous with a boiler
    large enough."""
    gb, hx, hd_1, hd_2 = _build(80., 40., 40.)
    gb_large, hx_large, hd_1_large, hd_2_large = _build(200., 40., 40.)
    assert gb.q_kw == pytest.approx(80., rel=1e-6)
    assert hx.t_2_out_c == pytest.approx(T_FEED_C, abs=1e-6)
    assert hx.mdot_2_kg_per_s < hx_large.mdot_2_kg_per_s
    assert hx.mdot_2_kg_per_s == pytest.approx(hx_large.mdot_2_kg_per_s, rel=1e-3)
    assert hx.t_1_out_c == pytest.approx(hx_large.t_1_out_c, abs=.01)
    assert hd_1.q_uncovered_kw == pytest.approx(0., abs=1e-6)
    assert 0. < hd_2.q_uncovered_kw < .05
    _assert_consistent_along_the_chain(gb, hx, hd_1, hd_2)
    _assert_consistent_along_the_chain(gb_large, hx_large, hd_1_large, hd_2_large)


@pytest.mark.parametrize("q_1_kw, q_2_kw", [(40., 40.), (20., 60.)])
def test_exchanger_far_short_of_primary_books_the_mixed_return(q_1_kw, q_2_kw):
    """A 50 kW boiler for 80 kW of demand: the exchanger keeps the outlet asked and serves the first demand,
    the boiler and the exchanger settle their return together, and the exchanger books the heat its demands
    receive (not 0.15 % less)."""
    gb, hx, hd_1, hd_2 = _build(50., q_1_kw, q_2_kw)
    assert gb.q_kw == pytest.approx(50., rel=1e-6)
    assert hx.t_2_out_c == pytest.approx(T_FEED_C, abs=1e-6)
    assert hd_1.q_uncovered_kw == pytest.approx(0., abs=1e-6)
    assert hd_2.q_uncovered_kw > 10.
    _assert_consistent_along_the_chain(gb, hx, hd_1, hd_2)
