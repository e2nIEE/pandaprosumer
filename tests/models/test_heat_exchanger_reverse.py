"""
The heat exchanger's LMTD dichotomy and its reverse calculation (primary flow short).

The dichotomy solving ``a x + ln(1 - x) = 0`` was run as on a decreasing function for ``0 < a < 1`` (the
cold approach larger than the hot one) and stopped on the bracket's edge ``(a - 1) / a`` instead of the
root: the primary left 3 K colder than the LMTD allows. Its fixed left edge ``3 (a - 1) / a``, like the
right edge of the dry cooler's variant ``a x - ln(1 + x) = 0``, missed the root below ``a = 0.27``.

The reverse calculation (less primary flow provided than the forward calculation draws) kept the primary
outlet of the forward solution and solved the LMTD for the secondary outlet: not the inverse of the forward
calculation. It is now the forward calculation solved for the secondary flow the provided primary heats to
the outlet asked.
"""
import numpy as np
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_heat_exchanger
from pandaprosumer.library.heat_exchanger_utils import calculate_temperature_difference, compute_temp

# above a = 10 the root has 1 - x below 1e-4 and the dichotomy's 1e-12 threshold on x shows in the residual
A_VALUES = [10., 3., 1.5, 1.05, 1.001, .999, .95, .83, .5, .3, .27, .25, .1, .02]


@pytest.mark.parametrize("a", A_VALUES)
def test_cold_dichotomy_finds_the_root(a):
    delta_t_hot_c = 23.
    x = 1 - calculate_temperature_difference(a, delta_t_hot_c, is_cold=True) / delta_t_hot_c
    assert a * x + np.log(1 - x) == pytest.approx(0., abs=1e-7)
    assert (x > 0) == (a > 1)


@pytest.mark.parametrize("a", A_VALUES)
def test_hot_dichotomy_finds_the_root(a):
    delta_t_cold_c = 23.
    x = calculate_temperature_difference(a, delta_t_cold_c, is_cold=False) / delta_t_cold_c - 1
    assert a * x - np.log(1 + x) == pytest.approx(0., abs=1e-7)
    assert (x < 0) == (a > 1)


@pytest.mark.parametrize("t_1_in_c", [76.85, 69.9])
def test_no_hot_approach_exchanges_nothing(t_1_in_c):
    """A primary feed at or below the secondary outlet asked: no exchange (the dichotomy has no root for
    ``a <= 0``; run on it anyway, it answered a 69.9 degC feed cooled to 43.6 degC by 2.7 kg/s)."""
    t_1_out_c, mdot_1_kg_per_s = compute_temp(.5, 50e3, t_1_in_c, 30., 76.85, 20., 15., 4180., heat_consumer=False)
    assert t_1_out_c == t_1_in_c
    assert mdot_1_kg_per_s == 0.


@pytest.fixture
def exchanger():
    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, 1, name="foo", start="2020-01-01 00:00:00", end="2020-01-01 11:59:59",
                           timezone="utc")
    idx = create_controlled_heat_exchanger(prosumer, order=0, period=period, t_1_in_nom_c=95, t_1_out_nom_c=45,
                                           t_2_in_nom_c=40, t_2_out_nom_c=80, mdot_2_nom_kg_per_s=.6)
    return prosumer, prosumer.controller.iloc[idx].object


@pytest.mark.parametrize("t_2_in_c", [40., 53.3, 60.])
@pytest.mark.parametrize("short_by", [1e-4, 1e-2, .1, .5, .9])
def test_reverse_is_the_inverse_of_the_forward(exchanger, t_2_in_c, short_by):
    """The reverse answers the secondary flow for which the forward calculation draws the primary flow provided,
    at the outlet asked, and that primary flow."""
    prosumer, hx = exchanger
    t_2_out_c, mdot_2_asked_kg_per_s, t_1_in_c = 80., .7, 85.
    forward = hx.calculate_heat_exchanger(prosumer, t_2_out_c, t_2_in_c, mdot_2_asked_kg_per_s, t_1_in_c)
    mdot_1_kg_per_s = forward[0] * (1 - short_by)
    reverse = hx.calculate_heat_exchanger_reverse(prosumer, t_2_out_c, t_2_in_c, mdot_2_asked_kg_per_s, t_1_in_c,
                                                  mdot_1_kg_per_s)
    assert reverse[0] == mdot_1_kg_per_s
    assert reverse[1] == t_1_in_c
    assert reverse[4] == t_2_in_c
    assert reverse[5] == t_2_out_c
    assert 0. < reverse[3] < forward[3]
    assert reverse[2] < forward[2]  # less duty: the primary outlet closer to the secondary inlet
    back = hx.calculate_heat_exchanger(prosumer, t_2_out_c, t_2_in_c, reverse[3], t_1_in_c)
    assert back[0] == pytest.approx(mdot_1_kg_per_s, rel=1e-8)
    assert back[2] == pytest.approx(reverse[2], abs=1e-6)


def test_reverse_is_continuous_with_the_forward(exchanger):
    prosumer, hx = exchanger
    forward = hx.calculate_heat_exchanger(prosumer, 80., 53.3, .7, 85.)
    reverse = hx.calculate_heat_exchanger_reverse(prosumer, 80., 53.3, .7, 85., forward[0] * (1 - 1e-6))
    assert reverse[3] == pytest.approx(forward[3], rel=1e-4)
    assert reverse[2] == pytest.approx(forward[2], abs=1e-3)


def test_reverse_with_no_primary_flow_exchanges_nothing(exchanger):
    prosumer, hx = exchanger
    assert hx.calculate_heat_exchanger_reverse(prosumer, 80., 40., .7, 85., 0.) == (0., 85., 85., 0., 40., 40.)
