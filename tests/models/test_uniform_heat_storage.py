"""
Unit tests of the uniform (fully mixed) heat storage: element creation, the exact mixed-tank step, the request
helpers and the controller alone with a demand (no source).
"""
import warnings

import numpy as np
import pandas as pd
import pytest

from pandaprosumer import (
    DFData,
    create_controlled_const_profile,
    create_controlled_heat_demand,
    create_controlled_uniform_heat_storage,
    create_empty_prosumer_container,
    create_period,
    create_uniform_heat_storage,
)
from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.mapped import EnergyLeakWarning
from pandaprosumer.controller.models.uniform_heat_storage import mixed_tank_step
from pandaprosumer.mapping import FluidMixMapping, GenericMapping
from pandaprosumer.run_time_series import run_timeseries

EXPECTED_COLUMNS = ['name', 'mass_kg', 'e_capacity_kwh', 'min_useful_temp_c', 't_full_c', 'u_w_per_m2k',
                    'area_wall_m2', 't_ext_c', 'max_remaining_capacity_kwh', 't_discharge_out_tol_c',
                    'max_charge_mdot_kg_per_s', 't_charge_target_c', 'in_service']


def _cp_j_per_kgk(prosumer, t_c):
    return float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_c))


class TestDefineElement:

    def test_define_element(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)
        create_uniform_heat_storage(prosumer, mass_kg=2000)

        assert len(prosumer.uniform_heat_storage) == 1
        assert list(prosumer.uniform_heat_storage.columns) == EXPECTED_COLUMNS
        expected_values = [None, 2000., np.nan, 65., np.nan, 0., 0., 22.5, 1, 1e-3, np.nan, np.nan, True]
        assert prosumer.uniform_heat_storage.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)
        create_uniform_heat_storage(prosumer, mass_kg=2000, min_useful_temp_c=55, t_full_c=85, u_w_per_m2k=.4,
                                    area_wall_m2=12, t_ext_c=10, max_remaining_capacity_kwh=2,
                                    t_discharge_out_tol_c=.5, max_charge_mdot_kg_per_s=3, t_charge_target_c=80,
                                    name="tank", in_service=False)
        e_capacity_kwh = 2000 * _cp_j_per_kgk(prosumer, 70) * 30 / 3.6e6
        expected_values = ["tank", 2000., e_capacity_kwh, 55., 85., .4, 12., 10., 2, .5, 3., 80., False]
        assert list(prosumer.uniform_heat_storage.columns) == EXPECTED_COLUMNS
        assert prosumer.uniform_heat_storage.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_capacity_in_kwh_is_converted_to_a_mass(self):
        prosumer = create_empty_prosumer_container()
        create_uniform_heat_storage(prosumer, e_capacity_kwh=100, min_useful_temp_c=50, t_full_c=90)
        mass_kg = prosumer.uniform_heat_storage.mass_kg.iloc[0]
        assert mass_kg == pytest.approx(100 * 3.6e6 / (_cp_j_per_kgk(prosumer, 70) * 40))
        assert prosumer.uniform_heat_storage.e_capacity_kwh.iloc[0] == pytest.approx(100)

    @pytest.mark.parametrize("params, match", [
        ({}, "exactly one of mass_kg and e_capacity_kwh"),
        ({"mass_kg": np.nan}, "exactly one of mass_kg and e_capacity_kwh"),
        ({"mass_kg": 1000, "e_capacity_kwh": 50, "t_full_c": 90}, "exactly one of mass_kg and e_capacity_kwh"),
        ({"mass_kg": 0}, "mass_kg .* must be positive"),
        ({"mass_kg": -5}, "mass_kg .* must be positive"),
        ({"e_capacity_kwh": 50}, "needs t_full_c"),
        ({"e_capacity_kwh": 0, "t_full_c": 90}, "e_capacity_kwh .* must be positive"),
        ({"e_capacity_kwh": 50, "t_full_c": 60}, "t_full_c .* must be above"),
        ({"mass_kg": 1000, "t_full_c": 65}, "t_full_c .* must be above"),
        ({"mass_kg": 1000, "u_w_per_m2k": -1}, "must be non-negative"),
        ({"mass_kg": 1000, "area_wall_m2": -1}, "must be non-negative"),
    ])
    def test_invalid_parameters(self, params, match):
        prosumer = create_empty_prosumer_container()
        with pytest.raises(ValueError, match=match):
            create_uniform_heat_storage(prosumer, **params)


class TestMixedTankStep:

    @pytest.mark.parametrize("inflows, ua_kg_per_s", [
        ([(2.0, 80.0)], 0.0),
        ([(2.0, 80.0), (1.0, 35.0)], 0.0),
        ([(0.3, 90.0), (5.0, 40.0)], 0.05),
        ([], 0.05),
        ([(50.0, 85.0)], 0.01),  # many tank volumes per step
    ])
    @pytest.mark.parametrize("dt_s", [60, 900, 3600, 86400])
    def test_energy_balance_is_exact(self, inflows, ua_kg_per_s, dt_s):
        mass_kg, t_start_c, t_ext_c = 3000.0, 60.0, 10.0
        t_end_c, t_mean_c = mixed_tank_step(t_start_c, mass_kg, inflows, ua_kg_per_s, t_ext_c, dt_s)
        exchanged_kgk = dt_s * (sum(m * (t - t_mean_c) for m, t in inflows) + ua_kg_per_s * (t_ext_c - t_mean_c))
        assert mass_kg * (t_end_c - t_start_c) == pytest.approx(exchanged_kgk, rel=1e-9, abs=1e-6)

    def test_no_flow_no_loss_keeps_the_temperature(self):
        assert mixed_tank_step(70.0, 1000.0, [(0.0, 90.0)], 0.0, 10.0, 3600) == (70.0, 70.0)

    def test_tends_to_the_mixing_temperature(self):
        t_end_c, _ = mixed_tank_step(70.0, 1000.0, [(10.0, 90.0), (10.0, 40.0)], 0.0, 10.0, 86400)
        assert t_end_c == pytest.approx(65.0)

    def test_losses_alone_decay_exponentially(self):
        ua_kg_per_s, mass_kg, dt_s = 0.002, 1000.0, 3600.0
        t_end_c, _ = mixed_tank_step(70.0, mass_kg, [], ua_kg_per_s, 10.0, dt_s)
        assert t_end_c == pytest.approx(10.0 + 60.0 * np.exp(-ua_kg_per_s * dt_s / mass_kg))

    def test_stays_between_the_inflows_whatever_the_step(self):
        for dt_s in [1, 3600, 1e7]:
            t_end_c, t_mean_c = mixed_tank_step(50.0, 10.0, [(100.0, 90.0)], 0.0, 10.0, dt_s)
            assert 50.0 <= t_mean_c <= t_end_c <= 90.0


def _controller(prosumer):
    return prosumer.controller.object.iloc[-1]


class TestRequestHelpers:

    @pytest.fixture
    def tank(self):
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 3600, "2020-01-01 00:00:00", "2020-01-01 00:59:59", "utc", "default")
        create_controlled_uniform_heat_storage(prosumer, mass_kg=2000, u_w_per_m2k=1, area_wall_m2=10,
                                               t_ext_c=10, t_tank_init_c=50, period=period)
        controller = _controller(prosumer)
        controller.resol = 3600
        return controller

    @pytest.mark.parametrize("charge, t_inflow_c", [(True, 80.0), (False, 30.0)])
    @pytest.mark.parametrize("heat_fraction", [0.05, 0.3, 0.55])
    def test_mass_for_heat_inverts_the_outlet(self, tank, charge, t_inflow_c, heat_fraction):
        heat_kgk = heat_fraction * 2000 * abs(t_inflow_c - 50.0)
        mass_kg = tank._mass_for_heat_kg(heat_kgk, t_inflow_c, charge)
        t_out_c = tank._outlet_c(mass_kg, not charge, t_inflow_c)
        exchanged_kgk = mass_kg * ((t_inflow_c - t_out_c) if charge else (t_out_c - t_inflow_c))
        assert exchanged_kgk == pytest.approx(heat_kgk, rel=1e-6)

    def test_mass_for_heat_is_capped(self, tank):
        # a charge: one tank volume per step at most
        assert tank._charge_mass_for_heat_kg(1e9, 80.0) == pytest.approx(2000)
        assert tank._charge_mdot_to_fill(80.0) * 3600 == pytest.approx(2000)
        # close to the charge temperature: the mass that brings the tank within 0.5 K of it
        assert tank._charge_mdot_to_fill(51.0) * 3600 == pytest.approx(2000 * np.log(1.0 / 0.5))
        # a discharge: the mass that brings the tank within 0.5 K of the return
        assert tank._discharge_mass_for_heat_kg(1e9, 30.0) == pytest.approx(2000 * np.log(20.0 / 0.5))

    def test_nothing_to_exchange_with_a_colder_charge_or_a_warmer_return(self, tank):
        assert tank._charge_mass_for_heat_kg(100.0, 45.0) == 0.0
        assert tank._discharge_mass_for_heat_kg(100.0, 55.0) == 0.0
        assert tank._charge_mdot_to_fill(50.2) == 0.0

    def test_remaining_capacity_and_stored_energy(self, tank):
        cp = float(tank.fluid.get_heat_capacity(CELSIUS_TO_K + 50.0))
        assert tank._get_remaining_capacity_kwh(40.0, 80.0) == pytest.approx(2000 * cp * 30 / 3.6e6)
        assert tank._get_remaining_capacity_kwh(90.0, 80.0) == 0.0
        assert tank._get_stored_energy_kwh(-np.inf) == 0.0


def _run_tank_and_demand(q_demand_kw, t_tank_init_c, resol_s=3600, warn_as_error=True, **tank_params):
    """A tank alone serving a heat demand (no source)."""
    prosumer = create_empty_prosumer_container()
    n = len(q_demand_kw)
    start = "2020-01-01 00:00:00"
    end = pd.Timestamp(start) + n * pd.Timedelta(seconds=resol_s) - pd.Timedelta(seconds=1)
    period = create_period(prosumer, resol_s, start, end, "utc", "default")
    data = pd.DataFrame({"q_demand_kw": q_demand_kw},
                        index=pd.date_range(start, periods=n, freq=f"{resol_s}s", tz="utc"))
    cp_idx = create_controlled_const_profile(prosumer, ["q_demand_kw"], ["q_demand_kw"], DFData(data), period, 0, 0)
    params = dict(mass_kg=3000, min_useful_temp_c=55, t_full_c=85)
    params.update(tank_params)
    uhs_idx = create_controlled_uniform_heat_storage(prosumer, t_tank_init_c=t_tank_init_c, period=period,
                                                     level=1, order=0, name="uhs", **params)
    hd_idx = create_controlled_heat_demand(prosumer, t_feed_demand_c=55, t_return_demand_c=30, period=period,
                                           level=1, order=1, name="hd")
    GenericMapping(prosumer, initiator_id=cp_idx, initiator_column="q_demand_kw", responder_id=hd_idx,
                   responder_column="q_demand_kw", order=0)
    FluidMixMapping(prosumer, initiator_id=uhs_idx, responder_id=hd_idx, order=0)
    with warnings.catch_warnings():
        if warn_as_error:
            warnings.simplefilter("error", EnergyLeakWarning)
        run_timeseries(prosumer, period, False)
    return prosumer, _results(prosumer, "uhs"), _results(prosumer, "hd")


def _results(prosumer, name):
    ts = prosumer.time_series
    return ts[ts.name == name].data_source.iloc[0].df


class TestControllerAlone:

    def test_discharges_until_spent_then_stops(self):
        _, uhs, hd = _run_tank_and_demand([50.0] * 8, t_tank_init_c=80)
        served = hd.q_received_kw > 1e-6
        # serves the demand fully while hot enough, then nothing once below min_useful_temp_c (minus 0.5 K)
        assert served.iloc[0] and not served.iloc[-1]
        assert hd.q_uncovered_kw[served].values == pytest.approx(0, abs=0.2)
        assert (uhs.t_tank_c.diff().dropna() <= 1e-9).all()
        # the gate is checked at the start of a step: the last step served drains at most one step of demand
        assert uhs.t_tank_c.min() >= 55 - 0.5 - 50e3 * 3600 / (3000 * 4.17e3)

    def test_tank_energy_balance(self):
        prosumer, uhs, hd = _run_tank_and_demand([20.0, 60.0, 0.0, 40.0, 10.0], t_tank_init_c=80,
                                                 u_w_per_m2k=2., area_wall_m2=20., t_ext_c=10.)
        change_kwh = (uhs.q_charge_kw - uhs.q_discharge_kw - uhs.q_loss_kw).cumsum()
        assert change_kwh.values == pytest.approx(uhs.e_stored_kwh.values, rel=5e-3, abs=0.05)
        assert (uhs.q_loss_kw > 0).all()
        assert uhs.q_delivered_kw.values == pytest.approx(hd.q_received_kw.values, rel=1e-3, abs=1e-3)

    def test_the_exact_step_makes_the_result_independent_of_the_time_step(self):
        """Losses only: one hour in one step or in four 15 min steps ends at the same temperature (up to the
        heat capacity, taken at the tank temperature at the start of each step)."""
        _, hourly, _ = _run_tank_and_demand([0.0], t_tank_init_c=80, u_w_per_m2k=5., area_wall_m2=20.)
        _, quarterly, _ = _run_tank_and_demand([0.0] * 4, t_tank_init_c=80, resol_s=900, u_w_per_m2k=5.,
                                               area_wall_m2=20.)
        assert hourly.t_tank_c.iloc[-1] == pytest.approx(quarterly.t_tank_c.iloc[-1], rel=1e-5)

    def test_default_initial_temperature_is_the_ambient(self):
        _, uhs, _ = _run_tank_and_demand([0.0], t_tank_init_c=None, t_ext_c=70.)
        assert uhs.t_tank_c.iloc[0] == pytest.approx(70.)

    def test_out_of_service_does_nothing(self):
        prosumer, uhs, hd = _run_tank_and_demand([50.0], t_tank_init_c=80, in_service=False)
        assert hd.q_received_kw.iloc[0] == 0
        assert _controller_named(prosumer, "uhs")._layer_temps_c == [80.0]


def _controller_named(prosumer, name):
    return next(c for c in prosumer.controller.object if c.name == name)
