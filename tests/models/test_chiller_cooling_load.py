"""
A chiller is driven by its cooling load (``q_load_kw``), not by what the consumer of its condenser heat asks for.
"""
import numpy as np
import pytest

from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import create_controlled_chiller


def _chiller(q_load_kw, heat_asked_kw):
    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, 3600, name="foo", start="2020-01-01 00:00:00", end="2020-01-01 11:59:59",
                           timezone="utc")
    idx = create_controlled_chiller(prosumer, order=0, period=period, n_ref="R410A")
    chiller = prosumer.controller.iloc[idx].object

    class _HeatConsumer:  # e.g. a heat demand fed from the condenser through a converter
        def q_to_receive_kw(self, _prosumer):
            return heat_asked_kw

    chiller._get_generic_mapped_responders = lambda _prosumer: [_HeatConsumer()]
    # t_set_pt_c, t_in_ev_c, t_in_cond_c, dt_cond_c, q_load_kw, n_is, q_max_kw, ctrl
    chiller.inputs = np.array([[7.0, 12.0, 30.0, 5.0, q_load_kw, 0.7, 200.0, 1]])
    chiller.time_step(prosumer, prosumer.period.iloc[0]["start"])
    chiller.control_step(prosumer)
    return dict(zip(chiller.obj.result_columns, chiller.step_results[0]))


class TestChillerCoolingLoad:
    def test_the_mapped_cooling_load_drives_the_evaporator(self):
        res = _chiller(q_load_kw=71.72, heat_asked_kw=75.0)
        assert res["q_evap_kw"] == pytest.approx(71.72)
        assert res["unmet_load_kw"] == pytest.approx(0.0, abs=1e-9)
        assert res["q_cond_kw"] > res["q_evap_kw"]  # the cooling plus the compressor work

    def test_the_heat_asked_by_the_condenser_side_is_not_a_cooling_load(self):
        no_heat = _chiller(q_load_kw=50.0, heat_asked_kw=0.0)
        much_heat = _chiller(q_load_kw=50.0, heat_asked_kw=500.0)
        assert no_heat["q_evap_kw"] == pytest.approx(50.0)
        assert much_heat["q_evap_kw"] == pytest.approx(50.0)

    def test_no_cooling_load_means_off(self):
        res = _chiller(q_load_kw=0.0, heat_asked_kw=75.0)
        assert res["q_evap_kw"] == 0.0
        assert res["q_cond_kw"] == 0.0

    def test_an_unmapped_load_falls_back_on_the_responders(self):
        res = _chiller(q_load_kw=np.nan, heat_asked_kw=60.0)
        assert res["q_evap_kw"] == pytest.approx(60.0)

    def test_the_load_is_capped_at_the_capacity(self):
        res = _chiller(q_load_kw=260.0, heat_asked_kw=0.0)
        assert res["q_evap_kw"] == pytest.approx(200.0)
        assert res["unmet_load_kw"] == pytest.approx(60.0)
