"""Stratified heat storage — wall-loss surfaces.

A vertical cylindrical tank split into N equal layers loses heat to the ambient
through:

  * the lateral surface `perimeter · dz` of EVERY layer,
  * plus the bottom disc `A` for layer 1 and the top disc `A` for layer N.

So the total loss surface is `2·A + N·perimeter·dz` and, with a uniform U, an
isothermal idle tank loses `U · (2A + N·S_lat) · (T − T_ext)`.

History: the controller used `S1 = Sl = A + S_lat` (the cross-section counted on
every interior layer as well) and `SN = S_lat` (no top disc) — with 20 layers the
as-coded UA was ≈ 2× the cylinder's. Surfaced by the Paris demo heat-loss study
(`scripts/heat_loss_study.py`, 2026-09-09).
"""
import numpy as np
import pytest

from pandaprosumer import (
    create_empty_prosumer_container,
    create_period,
    create_controlled_stratified_heat_storage,
)
from pandaprosumer.mapping.fluid_mix import FluidMixMapping

H_M = 10.0
R_M = 1.5
N_LAYERS = 10
T_TANK_C = 60.0
T_EXT_C = 20.0


def _build(resol_s=60, n_layers=N_LAYERS):
    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, resol_s, name="foo",
                           start="2020-01-01 00:00:00", end="2020-01-01 01:59:59",
                           timezone="utc")
    idx = create_controlled_stratified_heat_storage(
        prosumer, order=0, period=period,
        tank_height_m=H_M, tank_internal_radius_m=R_M, n_layers=n_layers,
        t_ext_c=T_EXT_C, init_layer_temps_c=[T_TANK_C] * n_layers,
        max_dt_s=resol_s, min_useful_temp_c=0.0,
    )
    return prosumer, prosumer.controller.iloc[idx].object


def _energy_j(shs, t_ref_c=T_TANK_C):
    """Sensible energy with rho·cp frozen at the tank temperature, as the model does
    (it evaluates both at the mean layer temperature once per step); letting them
    vary with T would add T·d(rho·cp)/dT ≈ −2.5 % at 60 °C to the energy difference."""
    rho_cp = float(shs.fluid.get_density(273.15 + t_ref_c)) * float(shs.fluid.get_heat_capacity(273.15 + t_ref_c))
    return sum(rho_cp * shs.A_m2 * shs.dz_m * t for t in shs._layer_temps_c)


def test_loss_surfaces_are_cylinder_surfaces():
    _, shs = _build()
    lateral = 2 * np.pi * R_M * (H_M / N_LAYERS)
    disc = np.pi * R_M ** 2
    assert shs.A_m2 == pytest.approx(disc)
    assert shs.Sl_m2 == pytest.approx(lateral)          # interior layers: lateral only
    assert shs.S1_m2 == pytest.approx(disc + lateral)   # bottom layer: lateral + bottom disc
    assert shs.SN_m2 == pytest.approx(disc + lateral)   # top layer: lateral + top disc
    total = shs.U1_w_per_m2k * shs.S1_m2 + shs.U_w_per_m2k * shs.Sl_m2 * (N_LAYERS - 2) \
        + shs.UN_w_per_m2k * shs.SN_m2
    assert total == pytest.approx(shs.U_w_per_m2k * (2 * disc + N_LAYERS * lateral))


def test_idle_isothermal_tank_loses_ua_delta_t():
    resol_s = 60
    prosumer, shs = _build(resol_s=resol_s)
    # Idle: no charge (NaN input → treated as no flow), no demand.
    shs.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = np.nan
    shs.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = np.nan
    shs.t_m_to_deliver = lambda x: (0, 0, [0])

    e0 = _energy_j(shs)
    shs.time_step(prosumer, "2020-01-01 00:00:00")
    shs.control_step(prosumer)
    e1 = _energy_j(shs)

    q_w = (e0 - e1) / resol_s
    ua_w_per_k = shs.U_w_per_m2k * (2 * shs.A_m2 + N_LAYERS * 2 * np.pi * R_M * shs.dz_m)
    assert q_w == pytest.approx(ua_w_per_k * (T_TANK_C - T_EXT_C), rel=0.02)
    # Every layer cooled; the end layers (extra disc) cooled more than the interior ones.
    t = np.asarray(shs._layer_temps_c)
    assert (t < T_TANK_C).all()
    assert t[0] < t[1] and t[-1] < t[-2]
    assert t[1:-1] == pytest.approx(t[1], abs=1e-9)
