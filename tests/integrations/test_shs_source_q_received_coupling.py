"""Cross-container energy-conservation test for a charge source -> SHS coupling.

Root cause
----------
A charge source (HeatPump condenser here) delivers heat to the ``StratifiedHeatStorage``
through a ``FluidMix`` coupling. The two containers share the same mass flow and
feed temperature; the only degree of freedom is the *return* temperature of the shared pipe.

The source heats the water from the return temperature it was handed via the
SHS's demand contract (``t_keep_return_c``) up to the feed temperature, so it
books ``q = mdot * cp * (t_feed - t_keep_return_c)``.

The SHS, however, reports ``q_received = mdot * cp * (t_received_in -
t_received_out)`` where ``t_received_out`` is its OWN internally-computed
bottom-layer mixed return. The reapply loop reconciles ``t_received_out`` with
``t_keep_return_c`` -- but its acceptance tolerance was the global
``TEMPERATURE_CONVERGENCE_THRESHOLD_C``, historically 1 K, and it accepts on the
first under-tolerance pass. That leftover return-temperature difference times
``mdot * cp`` is a spurious energy that appears on the SHS side but not on the
source side -- the two containers' result tables disagreed by up to ~1 K worth
of power (tens of kW at the ECS charge mass flows).

The fix tightens ``TEMPERATURE_CONVERGENCE_THRESHOLD_C`` (1 K -> 1e-2 K) so the
reapply loop actually drives the two return temperatures together, conserving
the boundary energy by the iteration itself -- no result-table post-hoc
adjustment. The stagnation guard still bounds the loop when the fixed point is
genuinely irreconcilable.
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


# --- Tank sizing ----
N_LAYERS = 20
MAX_DT_S = 1
RESOL_S = 300
N_STEPS = 14
TANK_H = 10.0
TANK_R = 1.495
T_EXT = 22.5
MIN_USEFUL = 58.0
# Nearly-full tank (bottom already at the demand feed) + a modest source cap.
# This puts the source in the low-power / low-charge-mdot regime (q ~ 240 kW at
# mdot ~ 8 kg/s),
# where the return-temperature residual is largest RELATIVE to q (~7 %, tripping
# check_couplings.py's 5 % tolerance). A high-power source hides the bug: the
# same fixed ~0.1 K residual is negligible next to a 1500 kW duty.
INIT_BOTTOM_C = 58.0
SOURCE_MAX_P_COMP_KW = 60.0

# DHW loop window. A 58/51 demand leaves headroom to charge the tank toward
# 65 C (t_charge_target_c), which produces the low-charge-mdot ramp steps where
# the return-temperature residual is largest.
T_FEED_DEMAND = 58.0
T_RETURN_DEMAND = 51.0
Q_DEMAND = 260.0
T_EVAP_IN = 36.4


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
        prosumer,
        input_columns=list(data.columns),
        result_columns=list(data.columns),
        data_source=data_source,
        period=period,
        level=0,
        order=0,
    )

    hp_params = {
        "carnot_efficiency": 0.5,
        "pinch_c": 0,
        "delta_t_evap_c": 4.1,
        "min_p_comp_kw": 0.1,
        "max_p_comp_kw": SOURCE_MAX_P_COMP_KW,
        "delta_t_hot_default_c": 5,
        "max_cop": 4.0,
    }
    hp_idx = create_controlled_heat_pump(
        prosumer, level=1, order=0, period=period, name="hp_ecs", **hp_params
    )

    init_layer_temps_c = list(np.linspace(INIT_BOTTOM_C, 65.0, N_LAYERS))
    shs_idx = create_controlled_stratified_heat_storage(
        prosumer,
        tank_height_m=TANK_H,
        tank_internal_radius_m=TANK_R,
        n_layers=N_LAYERS,
        max_dt_s=MAX_DT_S,
        max_charge_mdot_kg_per_s=42.0,
        min_useful_temp_c=MIN_USEFUL,
        t_ext_c=T_EXT,
        init_layer_temps_c=init_layer_temps_c,
        t_charge_target_c=65.0,
        period=period,
        level=1,
        order=1,
        name="shs_ecs",
    )

    hd_idx = create_controlled_heat_demand(
        prosumer,
        level=1,
        order=2,
        period=period,
        name="hd_ecs",
        t_feed_demand_c=T_FEED_DEMAND,
        t_return_demand_c=T_RETURN_DEMAND,
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


def test_source_q_equals_shs_q_received():
    """The energy the HP condenser delivers must equal the energy the SHS
    reports receiving, at every timestep.

    Both quantities cross the SAME FluidMix boundary (same mass flow, same feed
    temperature), so by conservation they are identical -- any difference is the
    unreconciled iterative-coupling return-temperature residual this regression
    guards against.
    """
    prosumer, period, pos = _build_prosumer()

    run_timeseries(prosumer, period, True)

    hp_df = prosumer.time_series.loc[pos["hp"]].data_source.df
    shs_df = prosumer.time_series.loc[pos["shs"]].data_source.df

    q_cond = hp_df["q_cond_kw"].values
    q_received = shs_df["q_received_kw"].values

    diff = np.abs(q_cond - q_received)
    scale = np.maximum(np.abs(q_cond), np.abs(q_received))
    # The two powers cross the SAME pipe (identical mdot and feed temp), so they
    # are physically identical -- hold them to a tight absolute band plus a small
    # relative term for cp-evaluation-temperature noise. This is far tighter than
    # the 5 % check_couplings.py had to widen to; pre-fix the residual is ~7 % of
    # q here (~18 kW at 240 kW), so this cleanly separates the two.
    tol = 1.0 + 0.005 * scale

    worst = int(np.argmax(diff))
    assert (diff <= tol).all(), (
        f"HP q_cond and SHS q_received disagree; worst step {worst}: "
        f"q_cond={q_cond[worst]:.3f} kW, q_received={q_received[worst]:.3f} kW, "
        f"|Δ|={diff[worst]:.3f} kW.\n"
        f"Per-step |Δ| (kW): {np.round(diff, 3)}"
    )
