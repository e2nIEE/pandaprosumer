"""A secondary request below the 1e-3 K guard must not create heat at the boundary.

Paris coupled run (`noneB50`, 2026-04-10 13:00): the CPCU->BET exchanger was
asked, on the first step of an OFF->ON ramp toward a 0.148 kW plan, to warm
18.78 kg/s by 0.0006 K. `control_step` treats a requested secondary warming
below 1e-3 K as "nothing to exchange" and zeroes the PRIMARY (mdot_1 = 0,
t_1_out = t_1_in, q_exchanged = 0) -- but it still handed the secondary on at
the REQUESTED outlet temperature, so the downstream heat demand booked 0.049 kW
that the exchanger never booked. 4 Wh once, but a boundary that creates heat.
The guard must deliver the secondary at its inlet temperature: both sides 0.
"""
import numpy as np
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_heat_exchanger

CP_W = 4186.0

PARIS_CPCU_HX = {
    't_1_in_nom_c': 80,
    't_1_out_nom_c': 40,
    't_2_in_nom_c': 17,
    't_2_out_nom_c': 57,
    'mdot_2_nom_kg_per_s': 252 * 1000 / 3600,
    'delta_t_hot_default_c': 23,
    'min_delta_t_1_c': 10,
    'max_q_kw': 4000,
}


def _period(prosumer):
    return create_period(prosumer, 1, name="p", start="2020-01-01 00:00:00",
                         end="2020-01-01 00:59:59", timezone="utc")


def _run_hx(t_2_out_c, mdot_2_kg_per_s=18.78, t_2_in_c=17., t_1_in_c=80.):
    prosumer = create_empty_prosumer_container()
    idx = create_controlled_heat_exchanger(prosumer, order=0, period=_period(prosumer), **PARIS_CPCU_HX)
    hx = prosumer.controller.iloc[idx].object
    hx.inputs = np.array([[t_1_in_c]])
    hx.t_m_to_deliver = lambda x: (t_2_out_c, t_2_in_c, [mdot_2_kg_per_s])
    hx.time_step(prosumer, "2020-01-01 00:00:00")
    hx.control_step(prosumer)
    q_kw, mdot_1, t_1_in, t_1_out, mdot_2, t_2_in, t_2_out = hx.step_results[0]
    return dict(q_kw=q_kw, mdot_1=mdot_1, t_1_in=t_1_in, t_1_out=t_1_out,
                mdot_2=mdot_2, t_2_in=t_2_in, t_2_out=t_2_out)


def _secondary_q_kw(r):
    return r['mdot_2'] * CP_W * (r['t_2_out'] - r['t_2_in']) / 1e3


class TestSubThresholdSecondaryRequest:

    def test_below_the_guard_both_sides_book_nothing(self):
        """0.0006 K at 18.78 kg/s (the field case): the primary is idle, so the
        secondary must leave at its inlet temperature -- no 0.049 kW appears
        downstream out of nowhere."""
        r = _run_hx(t_2_out_c=17.0006)
        assert r['mdot_1'] == 0
        assert r['q_kw'] == 0
        assert r['t_2_out'] == pytest.approx(r['t_2_in'], abs=1e-12)
        assert _secondary_q_kw(r) == pytest.approx(0.0, abs=1e-9)

    def test_the_secondary_mass_flow_still_passes_through(self):
        """Idle on heat, not on flow: the downstream contract keeps its mass flow."""
        r = _run_hx(t_2_out_c=17.0006)
        assert r['mdot_2'] == pytest.approx(18.78)

    def test_just_above_the_guard_both_sides_agree(self):
        """0.002 K (the second ramp step is 0.0013 K): the exchanger works and
        the primary booking follows the secondary duty."""
        r = _run_hx(t_2_out_c=17.002)
        assert r['q_kw'] > 0
        assert r['q_kw'] == pytest.approx(_secondary_q_kw(r), rel=1e-2)

    def test_a_zero_secondary_flow_request_is_idle_on_both_sides(self):
        r = _run_hx(t_2_out_c=25., mdot_2_kg_per_s=0.)
        assert r['q_kw'] == 0
        assert _secondary_q_kw(r) == pytest.approx(0.0, abs=1e-9)
