"""
Integration tests of the uniform (fully mixed) heat storage between a source (gas boiler or heat pump) and a heat
demand, with FluidMixMapping: the interface invariants on both sides of the tank, the tank's energy balance, the
reapply loop converging, and no EnergyLeakWarning.
"""
import warnings

import numpy as np
import pandas as pd
import pytest

from pandaprosumer import (
    DFData,
    create_controlled_const_profile,
    create_controlled_gas_boiler,
    create_controlled_heat_demand,
    create_controlled_heat_pump,
    create_controlled_uniform_heat_storage,
    create_empty_prosumer_container,
    create_period,
)
from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.mapped import EnergyLeakWarning
from pandaprosumer.mapping import FluidMixMapping, GenericMapping
from pandaprosumer.run_time_series import run_timeseries
from tests.integrations.test_overflow_strategy_consistency import _assert_interface_consistent

T_FEED_DEMAND_C = 60.0
T_RETURN_DEMAND_C = 35.0
#: demand profile [kW]: on, off (the tank charges), above the source (the tank discharges), a long full tank
Q_DEMAND_KW = [50, 50, 0, 0, 80, 120, 120, 30, 0, 0, 60, 60]
CHARGE_COL = "mdot_charge_setpoint_kg_per_s"
DISCHARGE_COL = "mdot_discharge_setpoint_kg_per_s"


def _build_and_run(source="gb", resol_s=3600, q_demand_kw=Q_DEMAND_KW, parallel=False, setpoints=None,
                   t_tank_init_c=62.0, max_q_kw=80, **tank_params):
    """
    source -> uniform tank -> heat demand (and source -> heat demand directly if ``parallel``).

    :param setpoints: dict ``{input column: per-step values}`` mapped onto the tank's setpoint inputs
    :return: dict of result data frames by controller name (``src``, ``uhs``, ``hd``)
    """
    n = len(q_demand_kw)
    prosumer = create_empty_prosumer_container()
    start = "2020-01-01 00:00:00"
    end = pd.Timestamp(start) + n * pd.Timedelta(seconds=resol_s) - pd.Timedelta(seconds=1)
    period = create_period(prosumer, resol_s, start, end, "utc", "default")
    columns = {"q_demand_kw": q_demand_kw, "t_evap_in_c": [20.0] * n}
    columns.update(setpoints or {})
    data = pd.DataFrame(columns, index=pd.date_range(start, periods=n, freq=f"{resol_s}s", tz="utc"))
    cp_idx = create_controlled_const_profile(prosumer, input_columns=list(data.columns),
                                             result_columns=list(data.columns), data_source=DFData(data),
                                             period=period, level=0, order=0)
    if source == "gb":
        src_idx = create_controlled_gas_boiler(prosumer, max_q_kw=max_q_kw, heating_value_kj_per_kg=50e3,
                                               efficiency_percent=100, period=period, level=1, order=0, name="src")
    else:
        src_idx = create_controlled_heat_pump(prosumer, carnot_efficiency=0.5, pinch_c=0, delta_t_evap_c=5,
                                              min_p_comp_kw=0.1, max_p_comp_kw=25, delta_t_hot_default_c=5,
                                              max_cop=5.0, period=period, level=1, order=0, name="src")
        GenericMapping(prosumer, initiator_id=cp_idx, initiator_column="t_evap_in_c", responder_id=src_idx,
                       responder_column="t_evap_in_c", order=0)
    params = dict(mass_kg=4000, min_useful_temp_c=T_FEED_DEMAND_C, t_full_c=85, u_w_per_m2k=0.5,
                  area_wall_m2=15, t_ext_c=15, t_charge_target_c=80 if source == "gb" else 70)
    params.update(tank_params)
    uhs_idx = create_controlled_uniform_heat_storage(prosumer, t_tank_init_c=t_tank_init_c, period=period,
                                                     level=1, order=1, name="uhs", **params)
    hd_idx = create_controlled_heat_demand(prosumer, t_feed_demand_c=T_FEED_DEMAND_C,
                                           t_return_demand_c=T_RETURN_DEMAND_C, period=period, level=1, order=2,
                                           name="hd")
    GenericMapping(prosumer, initiator_id=cp_idx, initiator_column="q_demand_kw", responder_id=hd_idx,
                   responder_column="q_demand_kw", order=1)
    if setpoints:
        GenericMapping(prosumer, initiator_id=cp_idx, initiator_column=list(setpoints), responder_id=uhs_idx,
                       responder_column=list(setpoints), order=2)
    if parallel:
        FluidMixMapping(prosumer, initiator_id=src_idx, responder_id=hd_idx, order=0)
        FluidMixMapping(prosumer, initiator_id=src_idx, responder_id=uhs_idx, order=1)
    else:
        FluidMixMapping(prosumer, initiator_id=src_idx, responder_id=uhs_idx, order=0)
    FluidMixMapping(prosumer, initiator_id=uhs_idx, responder_id=hd_idx, order=0)

    with warnings.catch_warnings():
        warnings.simplefilter("error", EnergyLeakWarning)
        run_timeseries(prosumer, period, False)
    ts = prosumer.time_series
    return {name: ts[ts.name == name].data_source.iloc[0].df for name in ("src", "uhs", "hd")}


def _source_columns(source):
    if source == "gb":
        return "t_out_c", "t_in_c", "mdot_kg_per_s", "q_kw"
    return "t_cond_out_c", "t_cond_in_c", "mdot_cond_kg_per_s", "q_cond_kw"


def _assert_tank_balance(uhs, resol_s, t_tank_init_c=62.0, mass_kg=4000.0):
    """
    The tank's balance. Exact in kg·K (the mixed-tank step conserves mdot·ΔT, the losses are booked with the
    heat capacity at the start of the step); in kWh within 1 %: each flow is booked with the heat capacity at
    its own temperatures, the stored energy with the one at the tank temperature.
    """
    fluid = create_empty_prosumer_container().fluid
    t_start_c = np.r_[t_tank_init_c, uhs.t_tank_c.values[:-1]]
    cp_start = np.array([float(fluid.get_heat_capacity(CELSIUS_TO_K + t)) for t in t_start_c])
    exchanged_kgk = resol_s * (uhs.mdot_charge_kg_per_s * (uhs.t_charge_in_c - uhs.t_charge_out_c)
                               - uhs.mdot_discharge_kg_per_s * (uhs.t_discharge_out_c - uhs.t_discharge_in_c)).values
    lost_kgk = resol_s * uhs.q_loss_kw.values * 1e3 / cp_start
    assert mass_kg * (uhs.t_tank_c.values - t_start_c) == pytest.approx(exchanged_kgk - lost_kgk, abs=1e-6)

    change_kwh = ((uhs.q_charge_kw - uhs.q_discharge_kw - uhs.q_loss_kw) * resol_s / 3600).cumsum()
    scale_kwh = max(1.0, uhs.e_stored_kwh.abs().max())
    assert np.abs(change_kwh.values - uhs.e_stored_kwh.values).max() <= 1e-2 * scale_kwh, (
        change_kwh.values, uhs.e_stored_kwh.values)


def _assert_storage_splits_what_it_receives(uhs):
    """received = charge + bypass, delivered = discharge + bypass (energy)."""
    bypass_in_kw = uhs.q_received_kw - uhs.q_charge_kw
    bypass_out_kw = uhs.q_delivered_kw - uhs.q_discharge_kw
    assert bypass_in_kw.values == pytest.approx(bypass_out_kw.values, rel=5e-3, abs=0.05)


@pytest.mark.parametrize("source", ["gb", "hp"])
@pytest.mark.parametrize("resol_s", [900, 3600])
def test_source_tank_demand_chain(source, resol_s):
    dfs = _build_and_run(source=source, resol_s=resol_s)
    src, uhs, hd = dfs["src"], dfs["uhs"], dfs["hd"]

    # the source <-> tank and tank <-> demand interfaces
    t_out, t_in, mdot, q = _source_columns(source)
    _assert_interface_consistent(src, uhs.rename(columns={"t_received_in_c": "t_in_c", "t_received_out_c": "t_out_c",
                                                          "mdot_received_kg_per_s": "mdot_kg_per_s",
                                                          "q_received_kw": "q_received_kw"}),
                                 t_out, t_in, mdot, q, rtol_q=5e-3, atol_q=0.05)
    _assert_interface_consistent(uhs, hd, "t_delivered_out_c", "t_delivered_in_c", "mdot_delivered_kg_per_s",
                                 "q_delivered_kw", rtol_q=5e-3, atol_q=0.05)
    _assert_tank_balance(uhs, resol_s)
    _assert_storage_splits_what_it_receives(uhs)

    # physically: the tank stays between the demand return and the charge temperature, and is used both ways
    assert (uhs.t_tank_c > T_RETURN_DEMAND_C).all() and (uhs.t_tank_c < 85.0 + 1e-6).all()
    assert (uhs.q_charge_kw > 1).any() and (uhs.q_discharge_kw > 1).any()
    # never over-serves the demand by more than the heat-capacity rounding
    assert (hd.q_uncovered_kw > -0.01 * np.array(Q_DEMAND_KW) - 0.05).all()


def test_the_tank_covers_what_the_source_cannot():
    """Demand above the 80 kW boiler: the tank (charged beforehand) serves the rest while it is warm enough."""
    dfs = _build_and_run(source="gb")
    uhs, hd = dfs["uhs"], dfs["hd"]
    peak = np.array(Q_DEMAND_KW) > 80
    assert hd.q_uncovered_kw[peak].values == pytest.approx(0, abs=0.2)
    assert (uhs.q_discharge_kw[peak] > 30).all()


def test_full_tank_bypasses_the_source_to_the_demand():
    """A full tank takes no charge: the source serves the demand through the bypass."""
    dfs = _build_and_run(source="gb", q_demand_kw=[40.0] * 4, t_tank_init_c=79.9)
    uhs, hd = dfs["uhs"], dfs["hd"]
    assert (uhs.q_charge_kw.abs() < 1.0).all()
    assert hd.q_uncovered_kw.values == pytest.approx(0, abs=0.1)


@pytest.mark.parametrize("source, max_q_kw", [("gb", 200), ("gb", 80), ("gb", 60), ("hp", None)])
def test_tank_in_parallel_with_its_source(source, max_q_kw):
    """
    source -> demand and source -> tank -> demand: no leak (EnergyLeakWarning is an error here), the tank is
    charged by the source's surplus.

    A boiler under the 120 kW peak runs at its maximum power while the tank, near its charge temperature, returns
    water above 70 °C: it stopped with ``Gas Boiler ...: did not converge after 20 iterations`` before the boilers
    solved their return with :class:`ReturnTemperatureSolver`.
    """
    dfs = _build_and_run(source=source, parallel=True, max_q_kw=max_q_kw)
    uhs, hd = dfs["uhs"], dfs["hd"]
    _assert_tank_balance(uhs, 3600)
    assert (uhs.q_charge_kw > 1).any()
    assert (hd.q_uncovered_kw > -0.5).all()


class TestSetpoints:

    def test_forced_charge_is_applied(self):
        n = len(Q_DEMAND_KW)
        charge = [0.3] * n
        dfs = _build_and_run(source="gb", setpoints={CHARGE_COL: charge, DISCHARGE_COL: [-1.0] * n})
        uhs = dfs["uhs"]
        charging = (uhs.mdot_received_kg_per_s > 0.3) & (uhs.t_tank_c.shift(fill_value=62.0) < 79.0)
        assert charging.any()
        assert uhs.mdot_charge_kg_per_s[charging].values == pytest.approx(0.3, rel=1e-6)
        _assert_tank_balance(uhs, 3600)

    def test_zero_discharge_setpoint_forces_no_discharge(self):
        n = len(Q_DEMAND_KW)
        dfs = _build_and_run(source="gb", setpoints={DISCHARGE_COL: [0.0] * n})
        uhs, hd = dfs["uhs"], dfs["hd"]
        assert (uhs.mdot_discharge_kg_per_s == 0).all()
        # the peak above the 80 kW boiler is then uncovered
        assert (hd.q_uncovered_kw[np.array(Q_DEMAND_KW) > 80] > 30).all()


def test_a_tank_just_under_the_feed_does_not_flood_the_demand():
    """
    Evening peak drained the tank to ~58 degC, just under the 60 degC feed; then the demand falls to the boiler's
    maximum power and the boiler falls 1e-5 kg/s short of it. The split's mixing valve (hot bypass + tank water to
    reach the feed temperature) used to draw ~5 kg/s of lukewarm water: the 80 kW demand got 211 kW and the tank was
    drained to 35 degC. The draw is capped at the demand energy the bypass leaves.
    """
    q_demand_kw = [20, 15, 15, 15, 20, 40, 70, 90, 60, 40, 30, 30,
                   30, 30, 30, 40, 60, 100, 130, 130, 110, 80, 50, 30]
    dfs = _build_and_run(source="gb", q_demand_kw=q_demand_kw, mass_kg=5000, t_charge_target_c=85,
                         area_wall_m2=17)
    uhs, hd = dfs["uhs"], dfs["hd"]
    # the scenario does reach a tank under the feed while the boiler alone (almost) covers the demand
    t_start_c = np.r_[62.0, uhs.t_tank_c.values[:-1]]
    assert ((t_start_c < T_FEED_DEMAND_C) & (np.array(q_demand_kw) == 80)).any()
    assert hd.q_uncovered_kw.values == pytest.approx(0, abs=0.2)
    assert (uhs.t_tank_c > 55).all()
    _assert_tank_balance(uhs, 3600, mass_kg=5000.0)
