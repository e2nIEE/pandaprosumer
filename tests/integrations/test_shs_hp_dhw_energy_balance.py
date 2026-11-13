"""Energy balance of a heat pump -> stratified storage -> heat demand chain (a DHW buffer).

Two defects found by replaying a district-loop DHW plant (HP condenser and a CPCU exchanger
charging a 70 m3 tank that serves a 58/51 degC demand), both visible as a demand served with
MORE heat than it asked for (``q_uncovered_kw < 0``):

1. Bypass energy counted above the demand feed only (fixed in 5c948cc).
   When the source delivers less flow than the demand needs, the tank tops the bypass up with a
   residual discharge sized on ``e_demand - e_bypass``. ``e_bypass`` used
   ``t_received_in - t_demand_out`` (feed side), not ``t_received_in - t_demand_in`` (the energy
   the bypass water really gives the demand before it returns). With a source at 65 degC and a
   58/51 demand that is 7 K instead of 14 K: the demand got half the bypass energy twice, i.e.
   over-served by exactly 0.5 x the bypass energy (2.6-8 % of the weekly DHW energy).

2. A heat pump that cannot run handed over the requested condenser flow (fixed: it now hands over none).
   When the evaporator inlet is at or above the requested condenser outlet, ``_calculate_heat_pump``
   shuts down but returns the REQUESTED mass flow at the REQUESTED return temperature
   (``t_cond_out = t_cond_in = t_cond_in_required``): a stream that carries no heat, labelled with
   the return the storage promised. The storage receives it colder than expected, finds itself
   "full" at that temperature (``_is_tank_full``) and bypasses the whole stream onto the demand,
   which returns it at the demand return. The storage books ``mdot * cp * (t_promised_return -
   t_demand_in)`` as received; the heat pump booked 0. The heat is created at the HP -> SHS
   boundary (~600 kW per step at 13 kg/s in the replay). The heat pump now returns no condenser flow when
   it cannot run (like its 'stays off' branch), and the tank serves the demand.
"""

import numpy as np
import pandas as pd
import pytest

from pandaprosumer import (
    create_empty_prosumer_container,
    create_period,
    create_controlled_const_profile,
    create_controlled_heat_pump,
    create_controlled_heat_demand,
    create_controlled_stratified_heat_storage,
    DFData,
)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries

RESOL_S = 300
N_STEPS = 12
N_LAYERS = 20
T_FEED_DEMAND = 58.0
T_RETURN_DEMAND = 51.0
T_CHARGE_TARGET = 65.0


def _build_prosumer(t_evap_in_c, q_demand_kw, max_p_comp_kw, init_layer_temps_c):
    prosumer = create_empty_prosumer_container()
    start = "2020-01-01 00:00:00"
    end = pd.Timestamp(start) + N_STEPS * pd.Timedelta(seconds=RESOL_S) - pd.Timedelta(seconds=1)
    period = create_period(prosumer, RESOL_S, start, end, "utc", "default")
    idx = pd.date_range(start, periods=N_STEPS, freq=f"{RESOL_S}s", tz="utc")
    data = pd.DataFrame({"t_evap_in_c": [t_evap_in_c] * N_STEPS,
                         "q_demand_kw": [q_demand_kw] * N_STEPS}, index=idx)
    cp_idx = create_controlled_const_profile(prosumer, input_columns=list(data.columns),
                                             result_columns=list(data.columns), data_source=DFData(data),
                                             period=period, level=0, order=0)
    hp_idx = create_controlled_heat_pump(prosumer, level=1, order=0, period=period, name="hp",
                                         carnot_efficiency=0.5, pinch_c=0, delta_t_evap_c=4.1,
                                         min_p_comp_kw=0.1, max_p_comp_kw=max_p_comp_kw,
                                         delta_t_hot_default_c=5, max_cop=4.0, mode="carnot")
    shs_idx = create_controlled_stratified_heat_storage(
        prosumer, tank_height_m=10.0, tank_internal_radius_m=1.495, n_layers=N_LAYERS, max_dt_s=30.0,
        max_charge_mdot_kg_per_s=42.0, min_useful_temp_c=T_FEED_DEMAND, t_ext_c=22.5,
        init_layer_temps_c=list(init_layer_temps_c), t_charge_target_c=T_CHARGE_TARGET,
        period=period, level=1, order=1, name="shs")
    hd_idx = create_controlled_heat_demand(prosumer, level=1, order=2, period=period, name="hd",
                                           t_feed_demand_c=T_FEED_DEMAND, t_return_demand_c=T_RETURN_DEMAND)
    GenericMapping(container=prosumer, initiator_id=cp_idx, initiator_column="t_evap_in_c",
                   responder_id=hp_idx, responder_column="t_evap_in_c", order=0)
    GenericMapping(container=prosumer, initiator_id=cp_idx, initiator_column="q_demand_kw",
                   responder_id=hd_idx, responder_column="q_demand_kw", order=1)
    FluidMixMapping(container=prosumer, initiator_id=hp_idx, responder_id=shs_idx, order=0)
    FluidMixMapping(container=prosumer, initiator_id=shs_idx, responder_id=hd_idx, order=0)
    run_timeseries(prosumer, period, False)
    ts = prosumer.time_series
    return ts.loc[0].data_source.df, ts.loc[1].data_source.df, ts.loc[2].data_source.df


def _assert_demand_served_exactly(hd, q_demand_kw):
    over = -hd["q_uncovered_kw"].clip(upper=0)
    worst = int(np.argmax(over.values))
    assert (over <= 1.0).all(), (
        f"demand of {q_demand_kw} kW over-served by up to {over.max():.1f} kW (step {worst}: "
        f"received {hd['q_received_kw'].iloc[worst]:.1f} kW); per step: {np.round(over.values, 1)}")


def test_capped_source_plus_residual_discharge_serves_the_demand_exactly():
    """A source too small for the demand, feeding at 65 degC into a full 65 degC tank: the bypass at
    65 degC plus the residual discharge must give the demand its energy, not 0.5 x the bypass more."""
    q_demand_kw = 400.0
    hp, shs, hd = _build_prosumer(t_evap_in_c=36.0, q_demand_kw=q_demand_kw, max_p_comp_kw=40.0,
                                  init_layer_temps_c=[T_CHARGE_TARGET] * N_LAYERS)
    # the scenario does exercise the branch: some bypass AND some residual discharge
    bypass_kw = shs["q_delivered_kw"] - shs["q_discharge_kw"]
    assert (bypass_kw > 10).any() and (shs["q_discharge_kw"] > 10).any(), (bypass_kw.values, shs["q_discharge_kw"].values)
    _assert_demand_served_exactly(hd, q_demand_kw)


def test_heat_pump_that_cannot_run_hands_over_no_heat():
    """Evaporator inlet above the 65 degC charge target: the HP cannot lift and delivers no heat. The storage
    (asking for a charge: bottom below the target) must book no heat from it, and the demand must get
    exactly its demand, from the tank."""
    q_demand_kw = 90.0
    hp, shs, hd = _build_prosumer(t_evap_in_c=66.0, q_demand_kw=q_demand_kw, max_p_comp_kw=393.0,
                                  init_layer_temps_c=np.linspace(63.0, T_CHARGE_TARGET, N_LAYERS))
    assert (hp["q_cond_kw"].abs() < 1e-6).all(), hp["q_cond_kw"].values  # the HP indeed cannot run
    gap = shs["q_received_kw"] - hp["q_cond_kw"]
    assert (gap.abs() <= 1.0).all(), (
        f"SHS books {shs['q_received_kw'].max():.1f} kW received from a heat pump delivering 0 kW "
        f"(received flow {shs['mdot_received_kg_per_s'].max():.2f} kg/s at {shs['t_received_in_c'].max():.2f} degC, "
        f"returned at {shs['t_received_out_c'].min():.2f} degC)")
    _assert_demand_served_exactly(hd, q_demand_kw)
