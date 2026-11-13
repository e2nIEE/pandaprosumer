"""
Tests for the Dry Cooler fan operating-regime limits (power floor / cap).

The fan affinity law makes the fan power scale with the cube of the air flow
(and hence the fan speed), so whenever far more cooling capacity is energised
than the heat-rejection duty requires the computed fan power collapses toward
~0, and whenever the duty exceeds the design point it shoots above the rating.
``min_fan_speed_pct`` / ``min_p_fan_kw`` floor and ``max_fan_speed_pct`` /
``max_p_fan_kw`` cap the energised-fan regime, mirroring the ``min_p_kw`` /
``max_p_kw`` (electric boiler) and ``min_p_comp_kw`` / ``max_p_comp_kw`` (heat
pump) bounds. See ``pandaprosumer/controller/models/dry_cooler.py``.
"""
import numpy as np
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_dry_cooler
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


# Default fan bank used in tests/models/test_dry_cooler.py. With a 334.8 kW
# demand (the ``test_controller_run_control_demand`` scenario below) the fan
# naturally runs at only ~104 rpm (≈14 % of the 730 rpm nominal) and draws a
# mere 0.0275 kW — the collapse the floors are meant to prevent.
N_NOM_RPM = 730
P_FAN_NOM_KW = 9.38
QAIR_NOM_M3_PER_H = 138200

# Per-fan affinity-law coefficient: p_fan = A * n_rpm**3
A = P_FAN_NOM_KW / N_NOM_RPM ** 3

# Baseline (no floor) outputs for the 334.8 kW demand, fans_number=1.
# Taken from tests/models/test_dry_cooler.py::test_controller_run_control_demand.
BASELINE_DEMAND = {
    "q_exchanged_kw": 334.81412,
    "p_fans_kw": 0.027525388,
    "n_rpm": 104.512057,
    "mdot_air_m3_per_h": 19785.70731,
    "mdot_air_kg_per_s": 5.9638259,
    "t_air_in_c": 20.0,
    "t_air_out_c": 75.75057,
    "mdot_fluid_kg_per_s": 2.0,
    "t_fluid_in_c": 80.0,
    "t_fluid_out_c": 40.0,
    "mdot_water_kg_per_s": 0.0,
}


def _period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


def _run_demand_step(prosumer, controller, mdot_kg_per_s=2., t_in_c=80., t_out_c=40., t_air_c=20.):
    """Feed the controller a single demand step and run the control step."""
    controller.inputs = np.array([[mdot_kg_per_s, t_in_c, t_out_c, t_air_c, np.nan]])
    controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_in_c
    controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_kg_per_s
    controller.time_step(prosumer, "2020-01-01 00:00:00")
    controller.control_step(prosumer)


def _make_controller(prosumer, **kwargs):
    params = dict(n_nom_rpm=N_NOM_RPM, p_fan_nom_kw=P_FAN_NOM_KW, qair_nom_m3_per_h=QAIR_NOM_M3_PER_H)
    params.update(kwargs)
    idx = create_controlled_dry_cooler(prosumer, period=_period(prosumer), **params)
    return prosumer.controller.iloc[idx].object


class TestDryCoolerFanPowerLimits:
    """Minimum / maximum fan-speed and fan-power limits on the dry cooler controller."""

    def test_no_floor_matches_baseline(self):
        """Without any floor (NaN defaults), the collapsed fan power is reported as-is."""
        prosumer = create_empty_prosumer_container()
        controller = _make_controller(prosumer)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(BASELINE_DEMAND["p_fans_kw"], rel=1e-4)
        assert res["n_rpm"] == pytest.approx(BASELINE_DEMAND["n_rpm"], rel=1e-4)

    def test_min_fan_speed_pct_floors_speed_and_power(self):
        """A 30 % minimum speed floors n_rpm to 0.3*n_nom and power to 0.3**3 * p_fan_nom."""
        prosumer = create_empty_prosumer_container()
        controller = _make_controller(prosumer, min_fan_speed_pct=30)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        expected_n_rpm = 0.30 * N_NOM_RPM
        expected_p_kw = 0.30 ** 3 * P_FAN_NOM_KW  # single fan
        assert res["n_rpm"] == pytest.approx(expected_n_rpm, rel=1e-6)
        assert res["p_fans_kw"] == pytest.approx(expected_p_kw, rel=1e-6)
        # The floor only touches the fan regime: the thermal duty is unchanged.
        assert res["q_exchanged_kw"] == pytest.approx(BASELINE_DEMAND["q_exchanged_kw"], rel=1e-4)
        assert res["t_fluid_out_c"] == pytest.approx(BASELINE_DEMAND["t_fluid_out_c"], rel=1e-4)
        assert res["mdot_air_m3_per_h"] == pytest.approx(BASELINE_DEMAND["mdot_air_m3_per_h"], rel=1e-4)

    def test_min_p_fan_kw_floors_power_and_keeps_speed_consistent(self):
        """A per-fan power floor raises p_fans and back-derives a consistent n_rpm."""
        prosumer = create_empty_prosumer_container()
        min_p_fan_kw = 2.0
        controller = _make_controller(prosumer, min_p_fan_kw=min_p_fan_kw)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(min_p_fan_kw, rel=1e-6)  # single fan
        # p_fan = A * n_rpm**3  ->  n_rpm = (min_p_fan_kw / A)**(1/3)
        expected_n_rpm = (min_p_fan_kw / A) ** (1. / 3.)
        assert res["n_rpm"] == pytest.approx(expected_n_rpm, rel=1e-6)
        assert res["q_exchanged_kw"] == pytest.approx(BASELINE_DEMAND["q_exchanged_kw"], rel=1e-4)

    def test_min_p_fan_kw_scales_with_fans_number(self):
        """The power floor is per energised fan, so the total floor scales with fans_number."""
        prosumer = create_empty_prosumer_container()
        min_p_fan_kw = 2.0
        fans_number = 4
        controller = _make_controller(prosumer, min_p_fan_kw=min_p_fan_kw, fans_number=fans_number)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(min_p_fan_kw * fans_number, rel=1e-6)

    def test_larger_floor_wins_when_both_set(self):
        """When both floors are set, the larger resulting power wins (here the power floor)."""
        prosumer = create_empty_prosumer_container()
        min_p_fan_kw = 2.0           # -> 2.0 kW
        min_fan_speed_pct = 30       # -> 0.3**3 * 9.38 = 0.253 kW
        controller = _make_controller(prosumer, min_p_fan_kw=min_p_fan_kw, min_fan_speed_pct=min_fan_speed_pct)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert min_p_fan_kw > 0.3 ** 3 * P_FAN_NOM_KW  # sanity: power floor is the larger one
        assert res["p_fans_kw"] == pytest.approx(min_p_fan_kw, rel=1e-6)

    def test_speed_floor_wins_when_larger(self):
        """When the speed floor implies more power than the per-fan power floor, it wins."""
        prosumer = create_empty_prosumer_container()
        min_p_fan_kw = 0.1           # -> 0.1 kW
        min_fan_speed_pct = 30       # -> 0.253 kW (larger)
        controller = _make_controller(prosumer, min_p_fan_kw=min_p_fan_kw, min_fan_speed_pct=min_fan_speed_pct)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        expected_p_kw = 0.30 ** 3 * P_FAN_NOM_KW
        assert expected_p_kw > min_p_fan_kw  # sanity: speed floor is the larger one
        assert res["p_fans_kw"] == pytest.approx(expected_p_kw, rel=1e-6)
        assert res["n_rpm"] == pytest.approx(0.30 * N_NOM_RPM, rel=1e-6)

    def test_floor_not_applied_above_minimum(self):
        """A floor below the natural operating point leaves the outputs untouched."""
        prosumer = create_empty_prosumer_container()
        # Natural speed is ~104 rpm = ~14 % of nominal; a 5 % floor is well below it.
        controller = _make_controller(prosumer, min_fan_speed_pct=5, min_p_fan_kw=0.001)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(BASELINE_DEMAND["p_fans_kw"], rel=1e-4)
        assert res["n_rpm"] == pytest.approx(BASELINE_DEMAND["n_rpm"], rel=1e-4)

    def test_floor_not_applied_when_idle(self):
        """With no heat to reject (t_in == t_out), the floors must NOT energise the fans."""
        prosumer = create_empty_prosumer_container()
        controller = _make_controller(prosumer, min_fan_speed_pct=30, min_p_fan_kw=2.0)
        _run_demand_step(prosumer, controller, t_in_c=80., t_out_c=80.)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(0.0)
        assert res["n_rpm"] == pytest.approx(0.0)
        assert res["mdot_air_m3_per_h"] == pytest.approx(0.0)

    def test_max_fan_speed_pct_caps_speed_and_power(self):
        """A 10 % maximum speed caps n_rpm to 0.1*n_nom and power to 0.1**3 * p_fan_nom."""
        prosumer = create_empty_prosumer_container()
        # Natural speed is ~104 rpm (~14 % of nominal); a 10 % cap binds.
        controller = _make_controller(prosumer, max_fan_speed_pct=10)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["n_rpm"] == pytest.approx(0.10 * N_NOM_RPM, rel=1e-6)
        assert res["p_fans_kw"] == pytest.approx(0.10 ** 3 * P_FAN_NOM_KW, rel=1e-6)
        # Cap touches the fan regime only; the thermal duty is unchanged.
        assert res["q_exchanged_kw"] == pytest.approx(BASELINE_DEMAND["q_exchanged_kw"], rel=1e-4)
        assert res["t_fluid_out_c"] == pytest.approx(BASELINE_DEMAND["t_fluid_out_c"], rel=1e-4)

    def test_max_p_fan_kw_caps_power_and_keeps_speed_consistent(self):
        """A per-fan power cap lowers p_fans and back-derives a consistent n_rpm."""
        prosumer = create_empty_prosumer_container()
        max_p_fan_kw = 0.02  # below the baseline 0.0275 kW
        controller = _make_controller(prosumer, max_p_fan_kw=max_p_fan_kw)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(max_p_fan_kw, rel=1e-6)  # single fan
        expected_n_rpm = (max_p_fan_kw / A) ** (1. / 3.)
        assert res["n_rpm"] == pytest.approx(expected_n_rpm, rel=1e-6)

    def test_max_p_fan_kw_scales_with_fans_number(self):
        """The power cap is per energised fan, so the total cap scales with fans_number."""
        prosumer = create_empty_prosumer_container()
        max_p_fan_kw = 0.02
        fans_number = 4
        controller = _make_controller(prosumer, max_p_fan_kw=max_p_fan_kw, fans_number=fans_number)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(max_p_fan_kw * fans_number, rel=1e-6)

    def test_smaller_cap_wins_when_both_set(self):
        """When both caps are set, the more binding (smaller resulting power) one wins."""
        prosumer = create_empty_prosumer_container()
        max_p_fan_kw = 0.02          # -> 0.02 kW
        max_fan_speed_pct = 10       # -> 0.1**3 * 9.38 = 0.00938 kW (smaller)
        controller = _make_controller(prosumer, max_p_fan_kw=max_p_fan_kw, max_fan_speed_pct=max_fan_speed_pct)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        expected_p_kw = 0.10 ** 3 * P_FAN_NOM_KW
        assert expected_p_kw < max_p_fan_kw  # sanity: speed cap is the more binding one
        assert res["p_fans_kw"] == pytest.approx(expected_p_kw, rel=1e-6)
        assert res["n_rpm"] == pytest.approx(0.10 * N_NOM_RPM, rel=1e-6)

    def test_cap_not_applied_below_maximum(self):
        """A cap above the natural operating point leaves the outputs untouched."""
        prosumer = create_empty_prosumer_container()
        controller = _make_controller(prosumer, max_fan_speed_pct=50, max_p_fan_kw=5.0)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(BASELINE_DEMAND["p_fans_kw"], rel=1e-4)
        assert res["n_rpm"] == pytest.approx(BASELINE_DEMAND["n_rpm"], rel=1e-4)

    def test_floor_and_cap_bracket_the_power(self):
        """A floor and a cap that bracket the natural point: the floor binds, cap is inert."""
        prosumer = create_empty_prosumer_container()
        # baseline 0.0275 kW -> floored to 0.5, well within the 2.0 cap.
        controller = _make_controller(prosumer, min_p_fan_kw=0.5, max_p_fan_kw=2.0)
        _run_demand_step(prosumer, controller)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(0.5, rel=1e-6)

    def test_cap_not_applied_when_idle(self):
        """With no heat to reject, neither floor nor cap energises the fans."""
        prosumer = create_empty_prosumer_container()
        controller = _make_controller(prosumer, max_fan_speed_pct=10, max_p_fan_kw=0.02,
                                      min_fan_speed_pct=30, min_p_fan_kw=2.0)
        _run_demand_step(prosumer, controller, t_in_c=80., t_out_c=80.)

        res = dict(zip(controller.result_columns, controller.step_results[0]))
        assert res["p_fans_kw"] == pytest.approx(0.0)
        assert res["n_rpm"] == pytest.approx(0.0)
