"""
NaN-propagation safety net for the StratifiedHeatStorage controller.

When an SHS sits between a heat-pump charge path and a heat-demand discharge
path, both flows can drop to zero in normal operation: the HP is OFF (e.g.
optimiser sends ``ON_HP=0``) and demand is satisfied from storage alone, or
the demand has gone to zero and the HP can't push warm water until the
upper layer cools enough. In the Paris demo's ECS chain this is the regime
where the SHS sits idle while the rest of the system runs.

In this regime, ``_t_received_in_c`` is NaN because no upstream FluidMix
initiator wrote a temperature. The TVD solver's convective terms then
compute ``mdot_charge_kg_per_s * cp * (t_charge_c - T_1)`` = ``0 * (NaN - T_1)``
= ``NaN``, even though the multiplication should be exactly zero on
physical grounds (no mass, no energy transferred). The NaN propagates
into every layer in the very first sub-step, and on the next timestep
the assertion ``(self._layer_temps_c > 0).all()`` fires with
"The SHS model has diverged - Negative temperature in the storage
layers=[nan nan ... nan]".

In the Paris demo's June scenario this surfaces around iter 9, after 8
iterations of all-zero-flow SHS I/O finally bleed enough NaN into the
``_layer_temps_c`` array via heat-loss + diffusion compounded over the
zero-mdot convection. The result CSV shows ``mdot_charge`` /
``mdot_discharge`` / ``q_*`` all zero throughout, but layer temps go NaN.

The fix replaces any NaN coming from a zero-mdot side with a finite
placeholder (the layer temperature on that side) at the controller
boundary, just before the TVD solver gets the inputs, so the
``0 * NaN`` multiplication can no longer poison the state. This is
safe because the zero-mdot side carries no enthalpy; the temperature
value is mathematically irrelevant. We assert (separately) that NaN
combined with non-zero mdot still surfaces as an error.
"""

import numpy as np
import pandas as pd

from pandaprosumer import (
    create_empty_prosumer_container,
    create_period,
    create_controlled_const_profile,
    create_controlled_heat_demand,
    create_controlled_stratified_heat_storage,
    DFData,
)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries


RESOL_S = 300
N_STEPS = 30   # > 8 to exceed the Paris demo's observed divergence point

SHS_PARAMS = dict(
    tank_height_m=10.0,
    tank_internal_radius_m=1.495,
    n_layers=20,
    max_dt_s=30.0,
    min_useful_temp_c=58.0,
    t_ext_c=22.5,
)

T_FEED_DEMAND_C = 65.0
T_RETURN_DEMAND_C = 58.0


def _build_prosumer(q_demand_kw):
    """Build a SHS + HD chain with NO upstream HP.

    Without the HP, ``_t_received_in_c`` is NaN every step (no FluidMix
    initiator). The SHS is in_service so its control_step runs. The
    demand drives the discharge side; with q=0 there's no discharge
    either, and the layer temps decay only via heat loss/diffusion.
    """
    prosumer = create_empty_prosumer_container()

    start = "2026-06-09 00:00:00"
    end = (
        pd.Timestamp(start)
        + N_STEPS * pd.Timedelta(f"00:00:{RESOL_S}")
        - pd.Timedelta("00:00:01")
    )
    period = create_period(prosumer, RESOL_S, start, end, "utc", "default")

    idx = pd.date_range(start, periods=N_STEPS, freq=f"{RESOL_S}s", tz="utc")
    data = pd.DataFrame(
        {
            "q_demand_kw": [q_demand_kw] * N_STEPS,
            "t_feed_demand_c": [T_FEED_DEMAND_C] * N_STEPS,
            "t_return_demand_c": [T_RETURN_DEMAND_C] * N_STEPS,
        },
        index=idx,
    )

    cp_idx = create_controlled_const_profile(
        prosumer,
        input_columns=list(data.columns),
        result_columns=list(data.columns),
        data_source=DFData(data),
        period=period,
        level=0, order=0,
    )

    # Initial thermocline: bottom = T_RETURN_DEMAND_C, top = T_FEED_DEMAND_C.
    init_layer_temps_c = list(
        np.linspace(T_RETURN_DEMAND_C, T_FEED_DEMAND_C, SHS_PARAMS["n_layers"])
    )
    shs_idx = create_controlled_stratified_heat_storage(
        prosumer,
        init_layer_temps_c=init_layer_temps_c,
        period=period,
        level=1, order=0,
        name="shs_ecs",
        **SHS_PARAMS,
    )

    hd_idx = create_controlled_heat_demand(
        prosumer,
        level=1, order=1,
        period=period,
        name="hd_ecs",
        t_feed_demand_c=T_FEED_DEMAND_C,
        t_return_demand_c=T_RETURN_DEMAND_C,
    )

    GenericMapping(
        container=prosumer, initiator_id=cp_idx,
        initiator_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
        responder_id=hd_idx,
        responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
        order=0,
    )
    FluidMixMapping(
        container=prosumer, initiator_id=shs_idx, responder_id=hd_idx, order=0,
    )

    return prosumer, period, shs_idx


def test_shs_idle_with_nan_upstream_does_not_diverge():
    """SHS with NO charge upstream AND zero demand must not NaN out.

    The pre-fix code propagates NaN through the TVD convective terms via
    ``0 * NaN`` and the layer temps go NaN within a few timesteps. The
    assertion ``(self._layer_temps_c > 0).all()`` then fires.
    """
    prosumer, period, shs_idx = _build_prosumer(q_demand_kw=0.0)
    run_timeseries(prosumer, period, True)  # must not raise

    shs_ctrl = prosumer.controller.loc[shs_idx].object
    assert np.all(np.isfinite(shs_ctrl._layer_temps_c)), (
        f"SHS layer temps went non-finite (NaN/Inf) after a fully-idle run: "
        f"{shs_ctrl._layer_temps_c}"
    )
    assert np.all(np.array(shs_ctrl._layer_temps_c) > 0), (
        f"SHS layer temps went non-positive: {shs_ctrl._layer_temps_c}"
    )

    shs_df = prosumer.time_series.loc[0].data_source.df
    # Pre-fix: rows go NaN around iter 8-9. Post-fix: zero everywhere.
    assert not shs_df.isna().any().any(), (
        f"SHS result CSV contains NaN entries (pre-fix bug)"
    )
    # The idle SHS should report all-zero flow and energy I/O.
    np.testing.assert_allclose(
        shs_df["mdot_charge_kg_per_s"].to_numpy(), np.zeros(N_STEPS), atol=1e-6
    )
    np.testing.assert_allclose(
        shs_df["mdot_discharge_kg_per_s"].to_numpy(), np.zeros(N_STEPS), atol=1e-6
    )
    np.testing.assert_allclose(
        shs_df["q_received_kw"].to_numpy(), np.zeros(N_STEPS), atol=1e-6
    )
    np.testing.assert_allclose(
        shs_df["q_delivered_kw"].to_numpy(), np.zeros(N_STEPS), atol=1e-6
    )

    # Top and bottom layers may drift by a fraction of a degree due to
    # heat losses + diffusion over N_STEPS * RESOL_S seconds, but they
    # must stay close to the initial thermocline endpoints (no runaway).
    assert abs(shs_ctrl._layer_temps_c[0] - T_RETURN_DEMAND_C) < 2.0, (
        f"Bottom layer drifted unexpectedly: {shs_ctrl._layer_temps_c[0]}"
    )
    assert abs(shs_ctrl._layer_temps_c[-1] - T_FEED_DEMAND_C) < 2.0, (
        f"Top layer drifted unexpectedly: {shs_ctrl._layer_temps_c[-1]}"
    )
