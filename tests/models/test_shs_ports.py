"""Stratified heat storage — connections at any height (``shs_ports``)."""
import numpy as np
import pytest

from pandaprosumer.controller.models.shs_ports import (
    auto_discharge_layer, auto_inlet_layer, layer_at_height, parse_auto_ports, plug_order, ports_convection_step,
    ports_resolution_in_time,
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
    assert top_entry[-1] < 60.  # the top was cooled by the lukewarm water
    assert lance[-1] > 79.  # the top is still the hot water it was


def test_an_auto_discharge_keeps_the_hottest_water_for_later():
    """A 55 °C demand drawn at the lowest layer still at 55 °C leaves the top layers hot."""
    outlet = auto_discharge_layer(STRATIFIED, 55.)
    top_draw, _ = _hour(STRATIFIED, DEFAULT, 0., 80., .5, 30.)
    mid_draw, _ = _hour(STRATIFIED, (TOP, BOTTOM, outlet, BOTTOM), 0., 80., .5, 30.)
    assert mid_draw[-1] == pytest.approx(STRATIFIED[-1], abs=.5)
    assert top_draw[-1] < mid_draw[-1] - 5.
