"""A stratified heat storage that starts the day full, is drained, and must then ask to be charged again.

Field case (a CHP piped through a 1 000 kWh tank into a district heating network): a tank behind a
CHP starts full (every layer at the 85 degC feed) and serves the night. Drained to 37-44 degC, below its 50 degC
useful temperature, it then never charged again although the CHP had 200 kW to spare: the "tank full" test measured
the remaining capacity from the INITIAL layers (85 degC -> 0 kWh storable at 85 degC) minus the energy stored above
the useful temperature (none) = 0 kWh, i.e. full for the rest of the day.
"""
import numpy as np
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_stratified_heat_storage

T_FEED_C = 85.0
T_RETURN_C = 45.0
N_LAYERS = 20


def _tank(init_c, layers_c):
    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, 3600, name="foo", start="2020-01-01 00:00:00", end="2020-01-01 11:59:59",
                           timezone="utc")
    index = create_controlled_stratified_heat_storage(prosumer, order=0, period=period, tank_height_m=5.0,
                                                      tank_internal_radius_m=1.25, n_layers=N_LAYERS,
                                                      min_useful_temp_c=50., t_ext_c=10., max_dt_s=10,
                                                      init_layer_temps_c=[init_c] * N_LAYERS)
    shs = prosumer.controller.iloc[index].object
    shs._layer_temps_c = np.array(layers_c, dtype=float)
    shs.t_m_to_deliver = lambda _: (T_FEED_C, T_RETURN_C, [3.0])
    shs.time_step(prosumer, "2020-01-01 10:00:00")
    return prosumer, shs


def _expected_kwh(shs, layers_c):
    temps_c = np.asarray(layers_c, dtype=float)
    temps_k = 273.15 + temps_c
    return float(np.sum(np.asarray(shs.fluid.get_density(temps_k)) * shs.A_m2
                        * np.asarray(shs.fluid.get_heat_capacity(temps_k)) * (T_FEED_C - temps_c) * shs.dz_m)) / 3.6e6


@pytest.mark.parametrize("init_c", [T_FEED_C, 50.0, 10.0])
def test_a_drained_tank_is_not_full_whatever_its_start(init_c):
    layers_c = np.linspace(37.0, 44.0, N_LAYERS)
    prosumer, shs = _tank(init_c, layers_c)
    assert not shs._is_tank_full(prosumer, T_FEED_C, 3.0)
    assert shs._get_remaining_capacity_kwh(50.0, T_FEED_C) == pytest.approx(_expected_kwh(shs, layers_c), rel=1e-9)


def test_a_drained_tank_that_started_full_asks_for_a_charge():
    prosumer, shs = _tank(T_FEED_C, np.linspace(37.0, 44.0, N_LAYERS))
    _, _, mdot_kg_per_s = shs.t_m_to_receive(prosumer)
    assert mdot_kg_per_s > 3.0 + 1.0, "the request carries the demand plus a charge"


def test_a_tank_at_the_charge_temperature_is_full():
    prosumer, shs = _tank(50.0, [T_FEED_C] * N_LAYERS)
    assert shs._is_tank_full(prosumer, T_FEED_C, 3.0)
    _, _, mdot_kg_per_s = shs.t_m_to_receive(prosumer)
    assert mdot_kg_per_s <= 3.0 + 1e-6, "a full tank only passes the demand on"


def test_a_charge_below_the_useful_temperature_stores_nothing():
    prosumer, shs = _tank(T_FEED_C, np.linspace(37.0, 44.0, N_LAYERS))
    assert shs._get_remaining_capacity_kwh(50.0, 45.0) == 0.0
