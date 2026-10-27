"""A primary feed colder than the secondary requires must not drive the guessed secondary return below freezing.

Game sandbox, 2026-10-20: a 10 kW heat pump for ~300 kW of buildings. The network pump injects exactly the
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
        into an infinite secondary flow. Nothing to heat: idle. (A guessed 10 degC return here would book 50 kW
        the demand never receives: handed back exactly the return it promised, it does not rerun the exchanger.)"""
        r = _run_hx(45.)
        assert r['mdot_1'] == 0
        assert r['q_kw'] == 0
        assert r['t_2_in'] == pytest.approx(40.)
        assert r['t_2_out'] == pytest.approx(40.)

    @pytest.mark.parametrize("t_1_in_c", [0.5, 4., 5.])
    def test_a_feed_too_cold_to_heat_water_exchanges_nothing(self, t_1_in_c):
        """The outlet would land at or below the freezing point: idle, the secondary passes at its own return."""
        r = _run_hx(t_1_in_c)
        assert r['mdot_1'] == 0
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
