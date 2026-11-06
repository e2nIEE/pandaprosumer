"""
The booster heat pump's COP stays within its correlations' range: a small (or negative) lift no longer gives
COPs of 20+, a large one no longer climbs back up past the fit's minimum, and mode 3 computes the radiator COP
from the radiator sink.
"""
import numpy as np
import pytest

from pandaprosumer.controller.models.booster_heat_pump import MIN_LIFT_K, booster_cop
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import create_controlled_booster_heat_pump

WATER_WATER2 = [23.69, -0.986, 0.012]
AIR_WATER = [5.06, -0.05, 0.00006]


def _cop(lift_k, coeff):
    return coeff[0] + coeff[1] * lift_k + coeff[2] * lift_k ** 2


class TestBoosterCop:
    def test_a_small_lift_gets_the_cop_of_the_smallest_fitted_lift(self):
        # The demo flat: a 20 degC source and a 23 degC floor-heating sink gave a COP of 20.7
        assert booster_cop(23.1, 20.0, WATER_WATER2) == pytest.approx(_cop(MIN_LIFT_K, WATER_WATER2))
        assert booster_cop(23.1, 20.0, WATER_WATER2) < 12.0

    def test_a_negative_lift_is_not_better_than_the_smallest_fitted_one(self):
        assert booster_cop(15.0, 30.0, WATER_WATER2) == pytest.approx(booster_cop(35.0, 20.0, WATER_WATER2))

    def test_a_realistic_lift_follows_the_fit(self):
        assert booster_cop(45.0, 20.0, WATER_WATER2) == pytest.approx(_cop(25.0, WATER_WATER2))
        assert 6.0 < booster_cop(45.0, 20.0, WATER_WATER2) < 7.0

    def test_the_cop_does_not_rise_again_past_the_fits_minimum(self):
        lowest_lift_k = 0.986 / (2 * 0.012)
        assert booster_cop(20.0 + 60.0, 20.0, WATER_WATER2) == pytest.approx(_cop(lowest_lift_k, WATER_WATER2))
        cops = [booster_cop(20.0 + lift, 20.0, WATER_WATER2) for lift in np.arange(10.0, 70.0, 1.0)]
        assert all(later <= earlier + 1e-12 for earlier, later in zip(cops, cops[1:]))

    def test_a_fit_without_a_minimum_in_range_follows_it(self):
        assert booster_cop(80.0, 20.0, AIR_WATER) == pytest.approx(_cop(60.0, AIR_WATER))


class TestBoosterMode3:
    def test_radiator_cop_uses_the_radiator_sink(self):
        """Ambient 0 degC: floor sink 30 degC, radiator sink 40 degC, from a 10 degC source (lifts 20 and 30 K)."""
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 1, name="foo", start="2020-01-01 00:00:00", end="2020-01-01 11:59:59",
                               timezone="utc")
        idx = create_controlled_booster_heat_pump(prosumer, order=0, period=period,
                                                  bhp_type='water-water2', q_max_kw=100.0)
        bhp = prosumer.controller.iloc[idx].object
        # t_amb_k, t_source_k, t_sink_k, demand, mode, q_received_kw, p_received_kw
        bhp.inputs = np.array([[273.15, 283.15, np.nan, 10.0, 3, 0, 0]])
        bhp.q_requested_kw = lambda _prosumer: 10.0
        bhp.time_step(prosumer, "2020-01-01 00:00:00")
        bhp.control_step(prosumer)

        cop_floor, cop_radiator, p_floor, p_radiator = bhp.step_results[0, :4]
        assert cop_floor == pytest.approx(_cop(20.0, WATER_WATER2))
        assert cop_radiator == pytest.approx(_cop(30.0, WATER_WATER2))
        assert p_floor == pytest.approx(10.0 / cop_floor)
        assert p_radiator == pytest.approx(10.0 / cop_radiator)
