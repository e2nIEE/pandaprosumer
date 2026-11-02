"""A stratified heat storage whose downstream reports a return below the freezing point of water.

Field case (SenergyNets game, a plant piped through a 2 000 kWh tank into a district heating network): when the
electricity price rose the tank stopped charging, the network cooled within the hour and, between two iterations
of the step, its pump reported the water coming back at -7.3 degC. The tank asserted ``t_demand_in_c >= 0`` and
stopped the whole run. Liquid water below 0 degC is an artefact of an unsettled network solve: the tank takes it as
water at the freezing point (as the heat exchanger already bounds its guessed return) and the step goes on, the
network then settling on what the plant can really deliver.
"""
import numpy as np
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_stratified_heat_storage
from pandaprosumer.controller.models.stratified_heat_storage import WATER_FREEZING_POINT_C
from pandaprosumer.mapping.fluid_mix import FluidMixMapping

T_FEED_C = 85.0
T_RETURN_SUBZERO_C = -7.324020929836819
MDOT_DEMAND_KG_PER_S = 5.92


def _tank(t_return_c):
    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, 3600, name="foo", start="2020-01-01 00:00:00", end="2020-01-01 11:59:59",
                           timezone="utc")
    # the field tank (2 000 kWh), full of 85 degC water
    index = create_controlled_stratified_heat_storage(prosumer, order=0, period=period, tank_height_m=6.302,
                                                      tank_internal_radius_m=1.576, n_layers=20,
                                                      min_useful_temp_c=50., t_ext_c=10., max_dt_s=10,
                                                      init_layer_temps_c=[85.] * 20)
    shs = prosumer.controller.iloc[index].object
    shs.t_m_to_deliver = lambda _: (T_FEED_C, t_return_c, [MDOT_DEMAND_KG_PER_S])
    shs.time_step(prosumer, "2020-01-01 06:00:00")
    return prosumer, shs


def test_a_subzero_return_does_not_stop_the_step():
    prosumer, shs = _tank(T_RETURN_SUBZERO_C)
    shs.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = np.nan
    shs.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = np.nan

    shs.control_step(prosumer)

    results = dict(zip(shs.result_columns, shs.step_results[0]))
    assert results["t_delivered_in_c"] == pytest.approx(WATER_FREEZING_POINT_C), "the return is taken at 0 degC"
    assert results["q_delivered_kw"] > 0, "a full tank still discharges into the cooled network"
    assert all(np.isfinite(value) for value in results.values())
    assert min(shs._layer_temps_c) >= WATER_FREEZING_POINT_C, "no layer is filled with sub-zero water"


def test_the_request_upstream_bounds_the_return_too():
    prosumer, shs = _tank(T_RETURN_SUBZERO_C)
    _, t_return_c, _ = shs.t_m_to_receive(prosumer)
    assert t_return_c >= WATER_FREEZING_POINT_C


def test_a_return_above_freezing_is_untouched():
    prosumer, shs = _tank(40.0)
    shs.control_step(prosumer)
    results = dict(zip(shs.result_columns, shs.step_results[0]))
    assert results["t_delivered_in_c"] == pytest.approx(40.0)
    assert shs.t_m_to_receive(prosumer)[1] >= 40.0 - 1e-9
