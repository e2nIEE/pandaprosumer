"""
Regression tests for a heat exchanger operated far below its nominal duty.

Paris CPCU<->BET exchanger: 4 MW nominal (80/40 primary, 17/57 secondary, 87 m3/h)
asked for ~230 kW in winter (7.9 kg/s from 17 to 24 degC). The LMTD shape
parameter ``a = delta_t_hot / (q_ratio * lmtd_nom)`` exceeds
``HeatExchangerControl.OUT_OF_RANGE_THRESHOLD`` and ``compute_temp`` used to
give up: primary side zeroed (t_1_out = t_1_in, mdot_1 = 0) while the
secondary result (mdot_2, t_2_out) was kept -> energy created at the HX/demand
boundary (hd_dhn booked 35 MWh/week, hx_dhn 14 MWh/week in Dec 2025).

Physically an oversized exchanger at low duty simply pinches the primary
outlet on the secondary inlet (the a -> inf limit of the LMTD solution).
"""
import numpy as np
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_heat_exchanger
from pandaprosumer.constants import HeatExchangerControl
from pandaprosumer.library.heat_exchanger_utils import compute_temp

CP_W = 4186.0

PARIS_CPCU_HX = {
    't_1_in_nom_c': 80,
    't_1_out_nom_c': 40,
    't_2_in_nom_c': 17,
    't_2_out_nom_c': 57,
    'mdot_2_nom_kg_per_s': 87 * 1000 / 3600,
    'delta_t_hot_default_c': 23,
    'min_delta_t_1_c': 10,
    'max_q_kw': 4000,
}


def _period(prosumer):
    return create_period(prosumer, 1, name="p", start="2020-01-01 00:00:00",
                         end="2020-01-01 00:59:59", timezone="utc")


def _run_hx(t_2_out_c, mdot_2_kg_per_s=7.9, t_2_in_c=17., t_1_in_c=80.):
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


class TestOversizedHeatExchanger:

    def test_compute_temp_beyond_threshold_pinches_instead_of_zeroing(self):
        """a > OUT_OF_RANGE_THRESHOLD: primary outlet pinches on the secondary inlet, flow stays finite."""
        q_w = 7.9 * CP_W * (24 - 17)
        q_nom_w = PARIS_CPCU_HX['mdot_2_nom_kg_per_s'] * CP_W * 40
        t_1_out, mdot_1 = compute_temp(q_w / q_nom_w, q_w, 80., 17., 24., 80 - 57, 40 - 17, CP_W,
                                       heat_consumer=False)
        a = (80 - 24) / ((q_w / q_nom_w) * ((23 - 23) if False else 23.))
        assert a > HeatExchangerControl.OUT_OF_RANGE_THRESHOLD  # the regime under test
        assert mdot_1 > 0
        assert t_1_out == pytest.approx(17., abs=0.5)
        assert mdot_1 * CP_W * (80 - t_1_out) == pytest.approx(q_w, rel=1e-6)

    def test_low_duty_primary_side_carries_the_secondary_duty(self):
        """Paris winter case: 7.9 kg/s 17 -> 24 degC on a 4 MW HX. Primary must book the same power."""
        r = _run_hx(t_2_out_c=24.)
        assert r['mdot_2'] == pytest.approx(7.9, rel=1e-3)
        assert r['t_2_out'] == pytest.approx(24.)
        q_secondary_kw = r['mdot_2'] * CP_W * (r['t_2_out'] - r['t_2_in']) / 1e3
        assert r['q_kw'] == pytest.approx(q_secondary_kw, rel=1e-2)
        assert r['mdot_1'] > 0
        assert r['t_1_out'] == pytest.approx(r['t_2_in'], abs=0.5)

    def test_low_duty_is_continuous_across_the_threshold(self):
        """25 degC (a ~ 36.6) and 25.5 degC (a ~ 34) must give the same qualitative answer."""
        below = _run_hx(t_2_out_c=25.5)  # a below threshold: historical OK branch
        above = _run_hx(t_2_out_c=25.0)  # a above threshold: used to zero the primary
        assert above['mdot_1'] == pytest.approx(below['mdot_1'], rel=0.15)
        assert above['t_1_out'] == pytest.approx(below['t_1_out'], abs=0.5)

    def test_primary_stall_never_leaves_a_live_secondary(self):
        """Whatever the regime, mdot_1 == 0 must imply no heat delivered on the secondary."""
        for t_2_out_c in (18., 20., 24., 25., 30., 45., 57.):
            r = _run_hx(t_2_out_c=t_2_out_c)
            if r['mdot_1'] < 1e-6:
                assert r['q_kw'] == pytest.approx(0.)
                assert r['mdot_2'] * (r['t_2_out'] - r['t_2_in']) == pytest.approx(0., abs=1e-6)
            else:
                q_secondary_kw = r['mdot_2'] * CP_W * (r['t_2_out'] - r['t_2_in']) / 1e3
                assert r['q_kw'] == pytest.approx(q_secondary_kw, rel=1e-2)
