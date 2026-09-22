"""
Regression test — SHS reapply loop against a POWER-CAPPED source with the
tank sitting just below its charge target.

Scenario (the historical ``test_1heatpump_1stratifiedheatstorage_1heatdemand_
mapping.py`` set-up): a 100 kW-compressor HP (q_cond capped at ≈321 kW) charges
a 10 m tall stratified tank (``min_useful_temp_c = 80``) that serves an
80/20 °C demand of exactly 321 kW. After a few charging hours every layer sits
at 79.6–79.7 °C: the tank is energetically full but every layer still counts
as "cold" (< 80 °C), so the forward request asks the HP for the full-volume
charge mass flow (≈2.7 kg/s) on top of the demand bypass (≈1.28 kg/s).

The HP cannot deliver that much at its cap, so it keeps the feed temperature
and shrinks the mass flow. The SHS gives the demand bypass priority, the hot
(79.6 °C) charge share shrinks, and the mass-weighted return drops. The old
reapply branch then re-requested the SAME forward charge mass flow at that
colder return, the capped HP delivered even less mass, the return dropped by
another ≈0.22 K, and so on: a fixed-point iteration whose contraction factor
→ 1 as the bottom layer approaches the feed temperature (the charge stream
carries almost no energy but dominates the mass-weighted return). Neither the
1e-2 K convergence band nor the 1e-2 K stagnation guard could ever trigger, and
the outer ``max_iter`` budget raised ``ControllerNotConverged`` at 08:00.

The reapply request is now anchored on the ENERGY the source actually delivered
on the previous pass, re-split the same way ``_calculate_heat_storage`` will
split it (demand bypass first, remainder to charge), so the request is
self-consistent and the pair converges in one or two passes.
"""

import numpy as np
import pandas as pd
import pytest

from pandaprosumer import (
    create_empty_prosumer_container,
    create_period,
    create_controlled_const_profile,
    create_controlled_heat_pump,
    create_controlled_stratified_heat_storage,
    create_controlled_heat_demand,
    DFData,
)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries


def _build_chain():
    prosumer = create_empty_prosumer_container()
    data = pd.DataFrame({"Tin_evap": [25] * 13,
                         "demand_1": [0] * 5 + [500] * 3 + [321] * 2 + [800] * 3,
                         "t_feed_demand_c": [80] * 13,
                         "t_return_demand_c": [20] * 13})

    start = "2020-01-01 00:00:00"
    resol = 3600
    end = (pd.Timestamp(start) + len(data) * pd.Timedelta(seconds=resol)
           - pd.Timedelta(seconds=1))
    data.index = pd.date_range(start, end, freq=f"{resol}s", tz="utc")
    period = create_period(prosumer, resol, start, end, "utc", "default")
    data_source = DFData(data)

    cp_in = ["Tin_evap", "demand_1", "t_feed_demand_c", "t_return_demand_c"]
    cp_out = ["t_evap_in_c", "qdemand_kw", "t_feed_demand_c", "t_return_demand_c"]
    hp_params = {"carnot_efficiency": 0.5, "pinch_c": 0, "delta_t_evap_c": 5,
                 "max_p_comp_kw": 100}
    shs_params = {"tank_height_m": 10., "tank_internal_radius_m": .564,
                  "tank_external_radius_m": .664, "insulation_thickness_m": .1,
                  "n_layers": 100, "min_useful_temp_c": 80, "t_ext_c": 20,
                  "max_dt_s": 10}
    hd_params = {"t_feed_demand_c": 76.85, "t_return_demand_c": 30}

    cp = create_controlled_const_profile(prosumer, cp_in, cp_out, data_source, period, 0, 0)
    hp = create_controlled_heat_pump(prosumer, period=period, level=1, order=0, **hp_params)
    shs = create_controlled_stratified_heat_storage(prosumer, period=period, level=1, order=1,
                                                    **shs_params)
    hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=2, **hd_params)

    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="t_evap_in_c",
                   responder_id=hp, responder_column="t_evap_in_c", order=0)
    for a, b in zip(["qdemand_kw", "t_feed_demand_c", "t_return_demand_c"],
                    ["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"]):
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column=a,
                       responder_id=hd, responder_column=b, order=0)
    FluidMixMapping(container=prosumer, initiator_id=hp, responder_id=shs, order=0)
    FluidMixMapping(container=prosumer, initiator_id=shs, responder_id=hd, order=0)
    return prosumer, period, hp, shs, hd


def _res(prosumer, idx):
    return prosumer.time_series.loc[idx].data_source.df


def test_power_capped_source_reapply_converges():
    prosumer, period, hp, shs, hd = _build_chain()

    # Historically raised ControllerNotConverged at 2020-01-01 08:00.
    run_timeseries(prosumer, period, True)

    hp_df = _res(prosumer, 0)
    shs_df = _res(prosumer, 1)
    hd_df = _res(prosumer, 2)
    assert len(hp_df) == len(shs_df) == len(hd_df) == 13

    # Source ⇄ SHS boundary conserves energy at EVERY step (the reapply loop's
    # job): what the HP books on its condenser is what the SHS books received.
    q_cond = hp_df.q_cond_kw.values
    q_received = shs_df.q_received_kw.values
    np.testing.assert_allclose(q_received, q_cond, atol=0.5,
                               err_msg="HP q_cond and SHS q_received diverge")

    # The return the HP was promised is the return the SHS actually produced.
    t_gap = np.abs(hp_df.t_cond_in_c.values - shs_df.t_received_out_c.values)
    running = hp_df.mdot_cond_kg_per_s.values > 1e-6
    assert (t_gap[running] < 0.05).all(), f"promised vs actual return gap: {t_gap[running]}"

    # The 321 kW hours are exactly at the HP cap: the demand is covered by the
    # bypass and the tank stays (energetically) full — no phantom charge.
    at_cap = np.zeros(13, dtype=bool)
    at_cap[8:10] = True  # the two 321 kW hours of the demand profile
    assert (hd_df.q_uncovered_kw.values[at_cap] < 1.0).all()
    assert (hp_df.q_cond_kw.values[at_cap] > 320.0).all()
    assert (hp_df.q_cond_kw.values <= 321.1).all()

    # Layers never blew up.
    assert (shs_df.t_discharge_out_c.values > 0).all()
    assert (shs_df.t_discharge_out_c.values < 100).all()
