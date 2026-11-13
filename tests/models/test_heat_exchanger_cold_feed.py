"""A primary feed colder than the secondary requires must not drive the guessed secondary return below freezing.

Field case: a 10 kW heat pump for ~300 kW of buildings. The network pump injects exactly the
plant's heat, so the network water cools hour after hour and reaches a care-home substation (85/50 -> 40/70)
at 11 degC. When the feed is colder than the requested secondary outlet, `control_step` slides the outlet down
to `t_1_in - 5` and, once that falls under the secondary return, guesses the return by keeping the secondary
temperature difference: 40 + (6 - 70) = -24 degC, and the `t_2_in_c >= 0` assertion stopped the run.

The guess itself is needed: a responder whose return is an outcome (a dry cooler cooling towards the air) only
reveals it once it receives water, and reruns the exchanger with it. So the guess stays, bounded by the freezing
point of water; a feed too cold to heat even that exchanges nothing. Here the demand is stubbed (no rerun):
these tests pin the exchanger's own first answer. tests/integrations/test_hx_cold_feed_heat_demand.py runs it
against a real heat demand.
"""
import numpy as np
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_heat_exchanger

CP_W = 4186.0

CARE_HOME_HX = {
    't_1_in_nom_c': 85.,
    't_1_out_nom_c': 50.,
    't_2_in_nom_c': 40.,
    't_2_out_nom_c': 70.,
    'mdot_2_nom_kg_per_s': 4.,
    'delta_t_hot_default_c': 5.,
    'min_delta_t_1_c': 5.,
    'max_q_kw': 2000.,
}
#: The care home's 70/40 secondary at 50 kW
MDOT_2_KG_PER_S = 50e3 / (CP_W * 30.)
#: The primary flow a starved exchanger draws, valve open: those 50 kW over the nominal 85/50 degC primary
STARVED_MDOT_1_KG_PER_S = 50e3 / (CP_W * 35.)


def _period(prosumer):
    return create_period(prosumer, 3600, "2020-01-01 00:00:00", "2020-01-01 00:59:59", "utc", "p")


def _run_hx(t_1_in_c, t_2_out_c=70., t_2_in_c=40., mdot_2_kg_per_s=MDOT_2_KG_PER_S):
    prosumer = create_empty_prosumer_container()
    idx = create_controlled_heat_exchanger(prosumer, order=0, period=_period(prosumer), **CARE_HOME_HX)
    hx = prosumer.controller.iloc[idx].object
    hx.inputs = np.array([[t_1_in_c]])
    hx.t_m_to_deliver = lambda x: (t_2_out_c, t_2_in_c, [mdot_2_kg_per_s])
    hx.time_step(prosumer, "2020-01-01 00:00:00")
    hx.control_step(prosumer)
    q_kw, mdot_1, t_1_in, t_1_out, mdot_2, t_2_in, t_2_out = hx.step_results[0]
    return dict(q_kw=q_kw, mdot_1=mdot_1, t_1_in=t_1_in, t_1_out=t_1_out,
                mdot_2=mdot_2, t_2_in=t_2_in, t_2_out=t_2_out)


class TestColdPrimaryFeed:

    @pytest.mark.parametrize("t_1_in_c", [0.5, 4., 5., 6., 11.02, 30., 44., 45., 46., 60., 85.])
    def test_every_feed_gives_a_physical_answer(self, t_1_in_c):
        r = _run_hx(t_1_in_c)
        assert all(np.isfinite(v) for v in r.values())
        assert min(r['t_1_out'], r['t_2_in'], r['t_2_out']) >= 0
        assert r['t_1_out'] <= r['t_1_in']
        assert r['t_2_out'] >= r['t_2_in']
        assert r['q_kw'] == pytest.approx(r['mdot_2'] * CP_W * (r['t_2_out'] - r['t_2_in']) / 1e3,
                                          rel=1e-2, abs=1e-6)

    def test_the_field_case_guesses_a_return_at_the_freezing_point(self):
        """11.02 degC: the outlet slides to 6.02 degC, the guessed return stops at 0 instead of -23.98 degC."""
        r = _run_hx(11.02)
        assert r['t_2_out'] == pytest.approx(6.02)
        assert r['t_2_in'] == pytest.approx(0.)

    def test_the_outlet_landing_on_the_return_exchanges_nothing(self):
        """45 degC: the outlet slides exactly onto the 40 degC return -- a zero difference that used to divide
        into an infinite secondary flow. Nothing to heat: no exchange, the primary passes through valve open.
        (A guessed 10 degC return here would book 50 kW the demand never receives: handed back exactly the
        return it promised, it does not rerun the exchanger.)"""
        r = _run_hx(45.)
        assert r['mdot_1'] == pytest.approx(STARVED_MDOT_1_KG_PER_S, rel=2e-2)
        assert r['t_1_out'] == pytest.approx(45.)
        assert r['q_kw'] == 0
        assert r['t_2_in'] == pytest.approx(40.)
        assert r['t_2_out'] == pytest.approx(40.)

    @pytest.mark.parametrize("t_1_in_c", [0.5, 4., 5.])
    def test_a_feed_too_cold_to_heat_water_exchanges_nothing(self, t_1_in_c):
        """The outlet would land at or below the freezing point: no exchange, the secondary passes at its own return
        and the primary passes through valve open."""
        r = _run_hx(t_1_in_c)
        assert r['mdot_1'] == pytest.approx(STARVED_MDOT_1_KG_PER_S, rel=2e-2)
        assert r['q_kw'] == 0
        assert r['t_1_out'] == pytest.approx(t_1_in_c)
        assert r['t_2_in'] == pytest.approx(40.)
        assert r['t_2_out'] == pytest.approx(40.)
        assert r['mdot_2'] == pytest.approx(MDOT_2_KG_PER_S)

    @pytest.mark.parametrize("t_1_in_c", [46., 52., 60.])
    def test_a_lukewarm_feed_lowers_the_outlet_and_keeps_the_return(self, t_1_in_c):
        r = _run_hx(t_1_in_c)
        assert r['t_2_in'] == pytest.approx(40.)
        assert r['t_2_out'] == pytest.approx(t_1_in_c - 5.)
        assert r['q_kw'] > 0

    def test_a_hot_feed_is_untouched(self):
        r = _run_hx(85.)
        assert r['t_2_in'] == pytest.approx(40.)
        assert r['t_2_out'] == pytest.approx(70.)
        assert r['q_kw'] == pytest.approx(50., rel=1e-2)


class TestFeedJustAboveTheOutlet:
    """
    A feed a fraction of a degree above the requested outlet used to keep that outlet with no hot-end approach:
    in a coupled network (325 kW at 71.1 degC) the primary then left barely cooled at 15.5 kg/s, ten times
    its nominal flow, which drained the network's heat in one hour and starved every substation the next. The
    outlet now slides from 5 K above the requested one, so the primary flow is continuous across that threshold.
    """

    MDOT_2_325_KW = 325e3 / (CP_W * 30.)

    @pytest.mark.parametrize("t_1_in_c", [70.2, 72., 74.9])
    def test_the_outlet_keeps_a_5_k_approach(self, t_1_in_c):
        r = _run_hx(t_1_in_c, mdot_2_kg_per_s=self.MDOT_2_325_KW)
        assert r['t_2_out'] == pytest.approx(t_1_in_c - 5.)
        assert r['t_1_out'] < t_1_in_c - 20., "the primary is cooled, not merely passed through"

    def test_the_primary_flow_is_continuous_around_the_outlet(self):
        flows = [_run_hx(t, mdot_2_kg_per_s=self.MDOT_2_325_KW)['mdot_1'] for t in (69.99, 70.01, 74.99, 75.01)]
        assert flows[1] == pytest.approx(flows[0], rel=1e-2)
        assert flows[3] == pytest.approx(flows[2], rel=1e-2)
        assert max(flows) < 3.5, "about 1.5 x the nominal primary flow of 325 kW over 85/50 degC, no pinch blow-up"


class TestStarvedValveOpen:
    """
    A substation starved by a feed too cold to heat with opens its valve rather than closing it: the network keeps
    circulating through it, unheated, so a heat-led plant sees the load and can warm the network up again. Closed,
    a network cooled overnight drew 0.3 kg/s, a CHP saw 78 kW (under its minimum load) and stayed off all day.
    """

    def test_a_starved_exchanger_draws_its_nominal_flow_and_exchanges_nothing(self):
        r = _run_hx(45.)
        assert r['q_kw'] == 0
        assert r['t_1_out'] == pytest.approx(45.)
        assert r['mdot_1'] == pytest.approx(STARVED_MDOT_1_KG_PER_S, rel=2e-2)

    def test_no_demand_draws_no_flow(self):
        r = _run_hx(45., mdot_2_kg_per_s=0.)
        assert r['mdot_1'] == 0
        assert r['q_kw'] == 0
