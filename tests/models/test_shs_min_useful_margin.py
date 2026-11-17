"""Stratified heat storage — the min_useful_temp_c gate on the residual discharge.

The tank asks its source to charge it AT ``min_useful_temp_c``, so a full tank sits exactly on that
threshold and any wall loss leaves its top layer a few mK below it. A strict ``top >= min_useful`` gate
then refuses the residual discharge exactly when the source falls short (observed in
``test_1heatpump_1stratifiedheatstorage_1heatdemand_mapping``: ~617 kWh in a tank whose top sat at
79.998 °C against an 80 °C threshold, 179 kW of demand left uncovered). The gate keeps a
``MIN_USEFUL_MARGIN_K`` margin below the threshold.
"""
import numpy as np
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_stratified_heat_storage
from pandaprosumer.controller.models.stratified_heat_storage import MIN_USEFUL_MARGIN_K


def _controller():
    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, 3600, name="foo", start="2020-01-01 00:00:00", end="2020-01-01 00:59:59",
                           timezone="utc")
    idx = create_controlled_stratified_heat_storage(prosumer, order=0, period=period, tank_height_m=10.,
                                                    tank_internal_radius_m=.564, min_useful_temp_c=80)
    shs = prosumer.controller.iloc[idx].object
    shs._layer_temps_c = np.full(len(shs._layer_temps_c), 80.0)  # a full tank: the stored-energy cap stays out of the way
    return prosumer, shs


@pytest.mark.parametrize("t_top_c", [80.0, 79.998, 80.0 - MIN_USEFUL_MARGIN_K])
def test_a_top_layer_just_under_the_threshold_still_discharges(t_top_c):
    prosumer, shs = _controller()
    mdot = shs._residual_discharge_mdot(prosumer, e_residual_kgk=100.0, t_discharge_out_c=t_top_c, t_demand_in_c=20.0)
    assert mdot == pytest.approx(100.0 / (t_top_c - 20.0))


def test_a_spent_tank_does_not_discharge():
    prosumer, shs = _controller()
    t_top_c = 80.0 - MIN_USEFUL_MARGIN_K - 0.01
    assert shs._residual_discharge_mdot(prosumer, 100.0, t_top_c, 20.0) == 0.0
    # nor at a vanishing usable ΔT, whatever the threshold
    assert shs._residual_discharge_mdot(prosumer, 100.0, 80.0, 79.8) == 0.0
    assert np.isfinite(shs._residual_discharge_mdot(prosumer, 100.0, 80.0, 79.4))


def test_a_nearly_spent_tank_delivers_no_more_than_it_stores():
    prosumer, shs = _controller()
    shs._layer_temps_c = np.array([20.0] * (len(shs._layer_temps_c) - 1) + [80.0])
    rho = float(shs.fluid.get_density(273.15 + 80.0))
    stored_kgk = rho * shs.A_m2 * shs.dz_m * 60.0
    mdot = shs._residual_discharge_mdot(prosumer, e_residual_kgk=100.0, t_discharge_out_c=80.0, t_demand_in_c=20.0)
    assert mdot * shs.resol * 60.0 == pytest.approx(stored_kgk)
    assert mdot < 100.0 / 60.0
