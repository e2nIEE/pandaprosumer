"""
Solar collectors charging a stratified tank: the heat the collectors book is the heat the tank receives.

Field case (SenergyNets "Solar house" demo, one-hour steps): collectors -> stratified tank -> floor heating, a gas
boiler topping the floor heating up. The collectors computed their gain from the 30 degC ``inlet_temperature_C``
input while the tank booked what it received from the water it really gave back (its ~19 degC bottom layer): the
tank received 327 kWh from collectors that made 212 kWh, and the house's balance did not close (115 kWh short).
The collectors now heat the water the tank gives back.
"""
import warnings

import numpy as np
import pandas as pd
import pytest

from pandaprosumer import (DFData, create_controlled_const_profile, create_controlled_gas_boiler,
                           create_controlled_heat_demand, create_controlled_solar_thermal,
                           create_controlled_stratified_heat_storage, create_empty_prosumer_container, create_period)
from pandaprosumer.mapping import FluidMixMapping, GenericMapping
from pandaprosumer.controller.mapped import EnergyLeakWarning
from pandaprosumer.run_time_series import run_timeseries

SUN_W_M2 = [0.0] * 8 + [200.8, 382.2, 525.9, 618.1, 650.0, 618.1, 525.9, 382.2, 200.8] + [0.0] * 7
PROFILE = pd.DataFrame({
    "beam": SUN_W_M2,
    "diffuse": [round(0.2308 * w, 1) for w in SUN_W_M2],
    "ground": [round(0.0308 * w, 1) for w in SUN_W_M2],
    "angle": [30.0] * 24,
    "t_amb": [5.0] * 8 + [6.9, 8.5, 9.9, 10.7, 11.0, 10.7, 9.9, 8.5, 6.9] + [5.0] * 7,
    "mdot": [0.0] * 9 + [1500.0] * 7 + [0.0] * 8,
    "t_in": [30.0] * 24,
    "q_house": [14.0] * 7 + [10.4] * 12 + [14.0] * 5,
})


def _solar_house():
    resol = 3600
    start = "2020-01-01 00:00:00"
    end = pd.Timestamp(start) + 24 * pd.Timedelta(f"{resol}s") - pd.Timedelta("1s")
    data = PROFILE.copy()
    data.index = pd.date_range(start, end, freq=f"{resol}s", tz="utc")

    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, resol, start, end, "utc", "default")
    columns = list(data.columns)
    cp = create_controlled_const_profile(prosumer, columns, columns, DFData(data), period)
    src = create_controlled_solar_thermal(prosumer, name="Solar collectors", order=1, period=period,
                                          number_collectors=30.0, flow_rate=72.0, piping_length=0.0,
                                          collector_slope=40.0)
    tank = create_controlled_stratified_heat_storage(prosumer, name="Solar tank", order=2, period=period,
                                                     tank_height_m=3.0, tank_internal_radius_m=0.9,
                                                     insulation_thickness_m=0.15, n_layers=20,
                                                     min_useful_temp_c=40.0, t_ext_c=15.0, max_dt_s=10.0)
    boiler = create_controlled_gas_boiler(prosumer, name="Backup boiler", order=3, period=period, max_q_kw=30.0,
                                          efficiency_percent=92.0)
    demand = create_controlled_heat_demand(prosumer, name="Floor heating", order=4, period=period,
                                           t_feed_demand_c=40.0, t_return_demand_c=30.0)

    GenericMapping(prosumer, initiator_id=cp, initiator_column=columns[:7], responder_id=src,
                   responder_column=["beam_solar_radiation_w_m2", "diffuse_solar_radiation_w_m2",
                                     "ground_solar_radiation_w_m2", "radiation_incidence_angle_deg",
                                     "ambient_temperature_C", "inlet_mass_flow_rate_kg_h", "inlet_temperature_C"])
    GenericMapping(prosumer, initiator_id=cp, initiator_column="q_house", responder_id=demand,
                   responder_column="q_demand_kw")
    FluidMixMapping(prosumer, initiator_id=src, responder_id=tank, order=0)
    FluidMixMapping(prosumer, initiator_id=tank, responder_id=demand, order=0)
    FluidMixMapping(prosumer, initiator_id=boiler, responder_id=demand, order=0)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", EnergyLeakWarning)
        run_timeseries(prosumer)
    leaks = [w for w in caught if issubclass(w.category, EnergyLeakWarning)]

    by_element = {row.element: row.data_source.df for row in prosumer.time_series.itertuples()}
    return by_element, leaks


@pytest.fixture(scope="module")
def solar_house():
    return _solar_house()


def test_the_tank_receives_what_the_collectors_make(solar_house):
    res, _ = solar_house
    gain_kw = res["solar_thermal"]["energy_gain_W"] / 1e3
    received_kw = res["stratified_heat_storage"]["q_received_kw"]
    # Every hour where the routing of the tank does not flip (see the next test), to the cp rounding
    steady = (gain_kw > 25.0)
    assert steady.sum() >= 5
    assert received_kw[steady].to_numpy() == pytest.approx(gain_kw[steady].to_numpy(), rel=1e-3)
    # Over the day, within the two threshold hours' mismatch (it was 115 kWh: the tank received 327 kWh from
    # collectors that made 212 kWh)
    assert abs(received_kw.sum() - gain_kw.sum()) < 0.1 * gain_kw.sum()


def test_only_the_threshold_hours_leak(solar_house):
    """
    At 9 h and 15 h the collectors' outlet sits around the floor heating's 40 degC feed: the tank routes their
    flow to the demand or into itself depending on it, no inlet temperature is self-consistent, the collectors
    settle on the midpoint and the tank says so (EnergyLeakWarning). Every other hour converges without leaking.
    """
    _, leaks = solar_house
    hours = sorted({str(w.message).split("timestep ")[1][11:13] for w in leaks})
    assert set(hours) <= {"09", "15"}


def test_the_house_balance_closes(solar_house):
    res, _ = solar_house
    tank = res["stratified_heat_storage"]
    supplied_kwh = res["solar_thermal"]["energy_gain_W"].sum() / 1e3 + res["gas_boiler"]["q_kw"].sum()
    used_kwh = res["heat_demand"]["q_received_kw"].sum() + tank["e_stored_kwh"].iloc[-1]
    losses_kwh = tank["q_received_kw"].sum() - tank["q_delivered_kw"].sum() - tank["e_stored_kwh"].iloc[-1]
    assert 0.0 <= losses_kwh < 5.0
    assert supplied_kwh == pytest.approx(used_kwh + losses_kwh, rel=0.05)


def test_the_collectors_heat_the_water_the_tank_gives_back(solar_house):
    res, _ = solar_house
    tank = res["stratified_heat_storage"]
    collectors = res["solar_thermal"]
    sunny = collectors["energy_gain_W"] > 25e3
    # outlet = inlet + gain / (mdot cp): the inlet is the tank's return, well below the 30 degC input
    inlet_c = collectors["outlet_temperature_C"] - 3.6 * collectors["energy_gain_W"] / (
        collectors["outlet_flow_rate_kg_h"] * 4.18)
    assert inlet_c[sunny].to_numpy() == pytest.approx(tank["t_received_out_c"][sunny].to_numpy(), abs=0.2)
    assert (inlet_c[sunny] < 25.0).all()
    assert np.isfinite(tank.to_numpy()).all()
