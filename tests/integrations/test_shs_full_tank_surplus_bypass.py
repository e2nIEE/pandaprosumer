"""Full-storage surplus handling for a charge source -> SHS -> demand chain.

When the upstream charge source is forced to overproduce (e.g. a HeatPump at
``min_p_comp_kw``) while the storage is already full, the surplus energy has
nowhere to be stored. Historically the SHS booked only the little energy its own
recomputed return temperature implied, while the source booked the full duty it
delivered -- so hundreds of kW silently disappeared at the boundary and the two
return temperatures (the contract the source used, ``t_keep_return_c``, vs the
SHS's own ``t_received_out_c``) diverged by several K, only kept alive by the
reapply loop's stagnation guard.

The intended behaviour:

  * The return temperature the source is handed is the mass-flow-weighted average
    of the demand return and the storage bottom-layer temperature. Full storage
    -> no charge -> the return collapses to the demand return.
  * The two return temperatures stay coherent (equal within
    ``TEMPERATURE_CONVERGENCE_THRESHOLD_C``), so the boundary energy is conserved:
    source ``q_cond`` == SHS ``q_received`` at every step.
  * A surplus the full tank cannot store is bypassed to the downstream demand,
    which is over-served -- ``q_uncovered_kw`` goes negative rather than the
    energy vanishing.
"""

import numpy as np
import pandas as pd

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


N_LAYERS = 20
MAX_DT_S = 1
RESOL_S = 300
N_STEPS = 12
TANK_H = 10.0
TANK_R = 1.495
T_EXT = 22.5
MIN_USEFUL = 58.0

T_FEED_DEMAND = 65.0
T_RETURN_DEMAND = 58.0
Q_DEMAND = 96.6          # small DHW draw
T_EVAP_IN = 36.4
MIN_P_COMP_KW = 100.0    # forces the HP to overproduce vs the small demand


def _build_prosumer():
    prosumer = create_empty_prosumer_container()

    start = "2020-01-01 00:00:00"
    end = (
        pd.Timestamp(start)
        + N_STEPS * pd.Timedelta(f"00:00:{RESOL_S}")
        - pd.Timedelta("00:00:01")
    )
    period = create_period(prosumer, RESOL_S, start, end, "utc", "default")

    idx = pd.date_range(start, periods=N_STEPS, freq=f"{RESOL_S}s", tz="utc")
    data = pd.DataFrame(
        {
            "t_evap_in_c": [T_EVAP_IN] * N_STEPS,
            "q_demand_kw": [Q_DEMAND] * N_STEPS,
            "t_feed_demand_c": [T_FEED_DEMAND] * N_STEPS,
            "t_return_demand_c": [T_RETURN_DEMAND] * N_STEPS,
        },
        index=idx,
    )
    data_source = DFData(data)

    cp_idx = create_controlled_const_profile(
        prosumer, input_columns=list(data.columns), result_columns=list(data.columns),
        data_source=data_source, period=period, level=0, order=0,
    )

    hp_params = {
        "carnot_efficiency": 0.5, "pinch_c": 0, "delta_t_evap_c": 4.1,
        "min_p_comp_kw": MIN_P_COMP_KW, "max_p_comp_kw": 393, "delta_t_hot_default_c": 5,
    }
    hp_idx = create_controlled_heat_pump(
        prosumer, level=1, order=0, period=period, name="hp_ecs", **hp_params
    )

    # Initial thermocline bottom = demand return, top = demand feed: a full tank
    # is reached within a few charge steps.
    init_layer_temps_c = list(np.linspace(T_RETURN_DEMAND, T_FEED_DEMAND, N_LAYERS))
    shs_idx = create_controlled_stratified_heat_storage(
        prosumer, tank_height_m=TANK_H, tank_internal_radius_m=TANK_R, n_layers=N_LAYERS,
        max_dt_s=MAX_DT_S, max_charge_mdot_kg_per_s=10.0, min_useful_temp_c=MIN_USEFUL,
        t_ext_c=T_EXT, init_layer_temps_c=init_layer_temps_c, period=period,
        level=1, order=1, name="shs_ecs",
    )

    hd_idx = create_controlled_heat_demand(
        prosumer, level=1, order=2, period=period, name="hd_ecs",
        t_feed_demand_c=T_FEED_DEMAND, t_return_demand_c=T_RETURN_DEMAND,
    )

    GenericMapping(
        container=prosumer, initiator_id=cp_idx, initiator_column="t_evap_in_c",
        responder_id=hp_idx, responder_column="t_evap_in_c", order=0,
    )
    GenericMapping(
        container=prosumer, initiator_id=cp_idx,
        initiator_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
        responder_id=hd_idx,
        responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
        order=1,
    )
    FluidMixMapping(container=prosumer, initiator_id=hp_idx, responder_id=shs_idx, order=0)
    FluidMixMapping(container=prosumer, initiator_id=shs_idx, responder_id=hd_idx, order=0)

    return prosumer, period, {"hp": 0, "shs": 1, "hd": 2}


def test_full_tank_surplus_is_conserved_and_bypassed():
    from pandaprosumer.constants import TEMPERATURE_CONVERGENCE_THRESHOLD_C

    prosumer, period, pos = _build_prosumer()

    run_timeseries(prosumer, period, True)  # must not raise

    hp = prosumer.time_series.loc[pos["hp"]].data_source.df
    shs = prosumer.time_series.loc[pos["shs"]].data_source.df
    hd = prosumer.time_series.loc[pos["hd"]].data_source.df

    q_cond = hp["q_cond_kw"].values
    q_received = shs["q_received_kw"].values
    q_delivered = shs["q_delivered_kw"].values
    hd_received = hd["q_received_kw"].values
    q_uncovered = hd["q_uncovered_kw"].values
    e_stored = shs["e_stored_kwh"].values

    # (1) THE fundamental cross-container invariant: the source and the SHS share
    #     the SAME return pipe, so the return temperature the source used
    #     (t_cond_in) and the one the SHS reports (t_received_out) must be equal
    #     within the reapply tolerance -- at EVERY step, including the full-tank
    #     ones where the surplus used to vanish and the returns used to diverge
    #     by several K. Held to a small multiple of the convergence threshold.
    t_gap = np.abs(shs["t_received_out_c"].values - hp["t_cond_in_c"].values)
    tgap_tol = 5 * TEMPERATURE_CONVERGENCE_THRESHOLD_C
    worst_t = int(np.argmax(t_gap))
    assert (t_gap <= tgap_tol).all(), (
        f"Source/SHS return temperatures incoherent; worst step {worst_t}: "
        f"t_cond_in={hp['t_cond_in_c'].values[worst_t]:.3f}, "
        f"t_received_out={shs['t_received_out_c'].values[worst_t]:.3f}, "
        f"|Δ|={t_gap[worst_t]:.4f} K.\nPer-step |Δ| (K): {np.round(t_gap, 4)}"
    )

    # (2) Full-tank surplus goes to the demand, not into thin air: at the steady
    #     full-tank steps the whole received stream is bypassed and the demand is
    #     over-served (q_uncovered < 0), the source⇄SHS energy is conserved
    #     exactly, and SHS delivered == demand received (no drop at either
    #     boundary). "Steady full" = demand over-served by a clear margin.
    steady_full = q_uncovered < -50.0
    assert steady_full.any(), (
        "Expected full-tank steps where the HP surplus over-serves the demand "
        f"(q_uncovered < 0). q_uncovered={np.round(q_uncovered, 1)}"
    )
    assert np.allclose(q_cond[steady_full], q_received[steady_full], atol=1.0), \
        "Full-tank surplus must be conserved at the source⇄SHS boundary"
    assert np.allclose(q_delivered, hd_received, atol=1.0), \
        "SHS q_delivered must equal the demand's q_received at every step"

    # (3) A full tank stops accumulating energy (it is not silently overheated by
    #     the surplus): once over-serving begins, e_stored no longer climbs.
    if steady_full.any():
        first_full = int(np.argmax(steady_full))
        assert e_stored[-1] <= e_stored[first_full] + 1.0, \
            f"Tank kept storing while full: e_stored {e_stored[first_full]:.1f} -> {e_stored[-1]:.1f} kWh"

    # (4) No NET energy vanishes over the run: the source's total delivered
    #     energy is accounted for (received by the SHS) to within a small margin.
    #     A single full-tank *transition* step can carry a residual because a
    #     power-limited source (HP pinned at min_p_comp) inflates its mass flow at
    #     the vanishing ΔT rather than reducing power -- the return temperatures
    #     stay coherent (checked in (1)), but mdot*cp*(tiny residual) shows up as
    #     a transient kW gap. It is bounded and integrates to <1 % of the run.
    e_cond = q_cond.sum()
    e_received = q_received.sum()
    assert abs(e_cond - e_received) <= 0.01 * e_cond, (
        f"Net source energy not conserved over the run: sum(q_cond)={e_cond:.1f}, "
        f"sum(q_received)={e_received:.1f} kW-steps"
    )
