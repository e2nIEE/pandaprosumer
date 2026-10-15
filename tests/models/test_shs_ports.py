"""Stratified heat storage — connections at any height (``shs_ports``)."""
import numpy as np
import pytest

from pandaprosumer.controller.models.shs_ports import (
    auto_discharge_layer, auto_inlet_layer, layer_at_height, mix_inverted_layers, parse_auto_ports, plug_order,
    ports_convection_step, ports_resolution_in_time,
)

N = 50
H_M, R_M = 10., .564
A_M2 = np.pi * R_M ** 2
DZ_M = H_M / N
RHO, CP = 975., 4190.
DT_S = 10.
TOP, BOTTOM = N - 1, 0
DEFAULT = (TOP, BOTTOM, TOP, BOTTOM)  # (charge_in, charge_out, discharge_out, discharge_in)
GEOMETRY = dict(t_ext_c=20., cp_j_per_kgk=CP, rho_kg_per_m3=RHO, A_m2=A_M2, dz_m=DZ_M,
                Sl_m2=2 * np.pi * R_M * DZ_M, S1_m2=A_M2 + 2 * np.pi * R_M * DZ_M, SN_m2=A_M2 + 2 * np.pi * R_M * DZ_M,
                k_star_w_per_mk=.6, U_w_per_m2k=.3, U1_w_per_m2k=.3, UN_w_per_m2k=.3)
NO_LOSS = {**GEOMETRY, "U_w_per_m2k": 0., "U1_w_per_m2k": 0., "UN_w_per_m2k": 0.}
STRATIFIED = np.linspace(30., 80., N)


def _energy_kwh(temps_c):
    return float(np.sum(temps_c)) * RHO * A_M2 * DZ_M * CP / 3.6e6


def _hour(temps_c, ports, mdot_charge, t_charge_c, mdot_discharge, t_return_c, geometry=NO_LOSS):
    """One hour of 10 s sub-steps; returns the layers and the heat the connections brought in (kWh)."""
    charge_in, charge_out, discharge_out, discharge_in = ports
    temps_c, brought_kwh = temps_c.copy(), 0.
    for _ in range(360):
        brought_kwh += DT_S * CP * (mdot_charge * (t_charge_c - temps_c[charge_out])
                                    + mdot_discharge * (t_return_c - temps_c[discharge_out])) / 3.6e6
        temps_c = ports_convection_step(temps_c, *ports, mdot_charge, t_charge_c, mdot_discharge, t_return_c,
                                        dt_s=DT_S, **geometry)
    return temps_c, brought_kwh


def test_parse_auto_ports():
    assert parse_auto_ports("") == frozenset()
    assert parse_auto_ports(None) == frozenset()
    assert parse_auto_ports(np.nan) == frozenset()
    assert parse_auto_ports(" charge_in, discharge_out ") == {"charge_in", "discharge_out"}
    with pytest.raises(ValueError, match="unknown"):
        parse_auto_ports("charge_in,top")


def test_layer_at_height():
    assert layer_at_height(None, N, DZ_M, default=TOP) == TOP
    assert layer_at_height(np.nan, N, DZ_M, default=BOTTOM) == BOTTOM
    assert layer_at_height(0., N, DZ_M, default=TOP) == 0
    assert layer_at_height(H_M, N, DZ_M, default=BOTTOM) == TOP
    assert layer_at_height(H_M / 2, N, DZ_M, default=TOP) == N // 2


def test_auto_layers():
    assert auto_inlet_layer(STRATIFIED, 55.) == int(np.flatnonzero(STRATIFIED <= 55.)[-1])
    assert auto_inlet_layer(STRATIFIED, 90.) == TOP  # hotter than the whole tank: the top
    assert auto_inlet_layer(STRATIFIED, 10.) == BOTTOM  # colder than the whole tank: the bottom
    assert auto_discharge_layer(STRATIFIED, 60.) == int(np.flatnonzero(STRATIFIED >= 60.)[0])
    assert auto_discharge_layer(STRATIFIED, 95.) == TOP  # nothing warm enough: the hottest layer


def test_plug_order_runs_from_the_outlet_towards_the_inlet():
    assert plug_order(N, BOTTOM, TOP) == list(range(N))
    assert plug_order(N, TOP, BOTTOM) == list(range(N - 1, -1, -1))
    assert plug_order(N, 10, 30) == list(range(10, 31))  # the layers below 10 are not flushed


@pytest.mark.parametrize("ports", [DEFAULT, (30, 5, 40, 10), (TOP, BOTTOM, 25, BOTTOM), (20, 20, TOP, BOTTOM),
                                   (5, TOP, BOTTOM, 40)])
@pytest.mark.parametrize("mdot_charge, mdot_discharge", [(2., .5), (.5, 2.), (1.5, 0.), (0., 1.5)])
def test_the_layers_gain_exactly_what_the_connections_bring(ports, mdot_charge, mdot_discharge):
    """No wall loss: the heat of the layers changes by what enters minus what leaves, to the Wh."""
    temps_c, brought_kwh = _hour(STRATIFIED, ports, mdot_charge, 75., mdot_discharge, 35.)
    assert _energy_kwh(temps_c) - _energy_kwh(STRATIFIED) == pytest.approx(brought_kwh, abs=0.01)


@pytest.mark.parametrize("ports", [DEFAULT, (30, 5, 40, 10), (5, TOP, BOTTOM, 40)])
def test_no_layer_leaves_the_range_of_the_water_involved(ports):
    temps_c, _ = _hour(STRATIFIED, ports, 3., 85., 2., 25., geometry=GEOMETRY)
    assert temps_c.min() >= 20. - 1e-6 and temps_c.max() <= 85. + 1e-6


def test_the_sub_stepped_solver_is_the_step_repeated():
    temps_c, _ = _hour(STRATIFIED, (30, 5, 40, 10), 1., 70., 1., 35.)
    solved = ports_resolution_in_time(STRATIFIED.copy(), 30, 5, 40, 10, 1., 70., 1., 35.,
                                      resol=3600., max_dt_s=DT_S, **NO_LOSS)
    np.testing.assert_allclose(solved, temps_c)


def test_a_lukewarm_charge_through_an_auto_inlet_leaves_the_hot_top_alone():
    """50 °C into a 30..80 °C tank: entering at the top stirs the hot layers, at its own layer it does not."""
    auto_inlet = auto_inlet_layer(STRATIFIED, 50.)
    top_entry, _ = _hour(STRATIFIED, DEFAULT, 1., 50., 0., 30.)
    lance, _ = _hour(STRATIFIED, (auto_inlet, BOTTOM, TOP, BOTTOM), 1., 50., 0., 30.)
    assert top_entry[-1] < 65.  # the top was cooled by the lukewarm water (mixed with the layers it sank through)
    assert lance[-1] > 79.  # the top is still the hot water it was


def test_an_auto_discharge_keeps_the_hottest_water_for_later():
    """A 55 °C demand drawn at the lowest layer still at 55 °C leaves the top layers hot."""
    outlet = auto_discharge_layer(STRATIFIED, 55.)
    top_draw, _ = _hour(STRATIFIED, DEFAULT, 0., 80., .5, 30.)
    mid_draw, _ = _hour(STRATIFIED, (TOP, BOTTOM, outlet, BOTTOM), 0., 80., .5, 30.)
    assert mid_draw[-1] == pytest.approx(STRATIFIED[-1], abs=.5)
    assert top_draw[-1] < mid_draw[-1] - 5.


def _is_monotone(temps_c, tol_k=1e-9):
    return bool(np.all(np.diff(temps_c) >= -tol_k))


@pytest.mark.parametrize("profile, expected", [
    ([30., 50., 80.], [30., 50., 80.]),  # already stratified: untouched
    ([80., 30.], [55., 55.]),  # hot under cold: the two mix
    ([30., 70., 50., 80.], [30., 60., 60., 80.]),  # one inversion in the middle: a mixed plateau
    ([80., 70., 60., 50.], [65., 65., 65., 65.]),  # fully inverted: uniform
    ([30., 90., 40., 50., 80.], [30., 60., 60., 60., 80.]),  # the plateau grows while it is warmer than the next layer
])
def test_mix_inverted_layers_gives_the_closest_monotone_profile_at_the_same_heat(profile, expected):
    mixed = mix_inverted_layers(np.array(profile))
    np.testing.assert_allclose(mixed, expected)
    assert mixed.sum() == pytest.approx(sum(profile))


def test_an_inverted_tank_mixes_within_one_sub_step():
    """Hot water under cold water does not stay there: after one step, no layer is warmer than the one above."""
    inverted = np.linspace(80., 30., N)
    after = ports_convection_step(inverted, *DEFAULT, 0., 80., 0., 30., dt_s=DT_S, **NO_LOSS)
    assert _is_monotone(after)
    assert np.allclose(after, 55.)  # a fully inverted profile ends uniform at its mean
    assert _energy_kwh(after) == pytest.approx(_energy_kwh(inverted), abs=1e-9)


@pytest.mark.parametrize("ports, mdot_charge, t_charge_c, mdot_discharge, t_return_c, what", [
    (DEFAULT, 0., 80., .5, 60., "a return hotter than the bottom rises through the cold layers"),
    (DEFAULT, 1., 40., 0., 30., "a charge colder than the top sinks through the hot layers"),
    ((TOP, BOTTOM, TOP, 25), 0., 80., .5, 40., "a mid-height return colder than its layer sinks"),
    ((25, BOTTOM, TOP, BOTTOM), 1., 75., 0., 30., "a mid-height charge hotter than its layer rises"),
])
def test_inflows_that_invert_the_layers_are_mixed_by_buoyancy(ports, mdot_charge, t_charge_c, mdot_discharge,
                                                              t_return_c, what):
    """Every hour-long inflow that would leave warm water under cold water ends with a monotone profile, and the
    layers still gain exactly what the connections brought (the mixing moves heat, it does not create it)."""
    temps_c, brought_kwh = _hour(STRATIFIED, ports, mdot_charge, t_charge_c, mdot_discharge, t_return_c)
    assert _is_monotone(temps_c), what
    assert _energy_kwh(temps_c) - _energy_kwh(STRATIFIED) == pytest.approx(brought_kwh, abs=0.01)
    assert temps_c.min() >= min(STRATIFIED.min(), t_charge_c, t_return_c) - 1e-6
    assert temps_c.max() <= max(STRATIFIED.max(), t_charge_c, t_return_c) + 1e-6


def test_a_hot_return_at_the_bottom_warms_the_cold_layers_not_only_the_bottom_one():
    """60 °C into a 30..80 °C bottom: without buoyancy the 60 °C water would sit under 31 °C water."""
    temps_c, _ = _hour(STRATIFIED, DEFAULT, 0., 80., .5, 60.)
    warmed = np.flatnonzero(temps_c > STRATIFIED + 1.)
    assert warmed.size > 1 and warmed[0] == BOTTOM
    assert temps_c[BOTTOM] == pytest.approx(temps_c[warmed[-1]], abs=1e-6)  # one mixed block
    assert temps_c[BOTTOM] < 60.  # mixed with the cold layers it rose through


def test_wall_losses_at_the_top_do_not_leave_a_colder_layer_over_a_warmer_one():
    """The top layer loses through the lid as well; the water it cools sinks instead of staying on top."""
    uniform = np.full(N, 80.)
    temps_c, _ = _hour(uniform, DEFAULT, 0., 80., 0., 30., geometry=GEOMETRY)
    assert _is_monotone(temps_c)
    assert temps_c[-1] < 80. and temps_c[0] < 80.
