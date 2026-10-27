"""A substation (exchanger -> heat demand) fed from a network that has cooled down below the building's needs.

The run must go on, the building's shortfall must show as uncovered demand, and both sides of the FluidMix
boundary must book the same heat -- see tests/models/test_heat_exchanger_cold_feed.py for the field case.
"""
import pandas as pd
import pytest
from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer import create_controlled_const_profile, create_controlled_heat_exchanger, create_controlled_heat_demand
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.mapping import FluidMixMapping, GenericMapping
from pandaprosumer.run_time_series import run_timeseries
from tests.integrations.test_overflow_strategy_consistency import _assert_interface_consistent

FEEDS_C = [85., 60., 46., 45., 44., 30., 11.02, 4., 0.5]
DEMAND_KW = 50.


def _run(feeds_c):
    prosumer = create_empty_prosumer_container()
    data = pd.DataFrame({"t_feed_c": feeds_c, "demand_kw": [DEMAND_KW] * len(feeds_c)})
    start = '2020-01-01 00:00:00'
    resol = 3600
    end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
    period = create_period(prosumer, resol, start, end, 'utc', 'default')
    data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
    cp = create_controlled_const_profile(prosumer, ["t_feed_c", "demand_kw"], ["t_feed_c", "demand_kw"],
                                         DFData(data), period, 0, 0)
    hx = create_controlled_heat_exchanger(prosumer, level=1, order=0, period=period,
                                          t_1_in_nom_c=85., t_1_out_nom_c=50., t_2_in_nom_c=40., t_2_out_nom_c=70.,
                                          mdot_2_nom_kg_per_s=4., delta_t_hot_default_c=5., min_delta_t_1_c=5.,
                                          max_q_kw=2000.)
    hd = create_controlled_heat_demand(prosumer, level=1, order=1, period=period,
                                       t_feed_demand_c=70., t_return_demand_c=40.)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="demand_kw",
                   responder_id=hd, responder_column="q_demand_kw", order=0)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="t_feed_c",
                   responder_id=hx, responder_column="t_feed_in_c", order=0)
    FluidMixMapping(container=prosumer, initiator_id=hx, responder_id=hd, order=0)
    run_timeseries(prosumer, period, True)
    return prosumer.time_series.loc[0].data_source.df, prosumer.time_series.loc[1].data_source.df


class TestSubstationOnACooledNetwork:

    def test_the_run_goes_through_with_no_negative_temperature(self):
        hx_df, hd_df = _run(FEEDS_C)
        assert (hx_df[["t_1_in_c", "t_1_out_c", "t_2_in_c", "t_2_out_c"]] >= 0.).all().all()
        assert (hd_df[["t_in_c", "t_out_c"]] >= 0.).all().all()

    def test_both_sides_book_the_same_heat(self):
        hx_df, hd_df = _run(FEEDS_C)
        _assert_interface_consistent(hx_df, hd_df, "t_2_out_c", "t_2_in_c", "mdot_2_kg_per_s", "q_exchanged_kw",
                                     rtol_q=1e-2, atol_q=1e-2)

    def test_the_shortfall_shows_as_uncovered_demand(self):
        _, hd_df = _run(FEEDS_C)
        cold = [f <= 45. for f in FEEDS_C]
        assert hd_df.q_received_kw[cold].values == pytest.approx(0., abs=1e-6)
        assert hd_df.q_uncovered_kw[cold].values == pytest.approx(DEMAND_KW, abs=1e-6)
        assert hd_df.q_received_kw.iloc[0] == pytest.approx(DEMAND_KW, rel=1e-2)
        assert 0. < hd_df.q_received_kw.iloc[1] < DEMAND_KW
