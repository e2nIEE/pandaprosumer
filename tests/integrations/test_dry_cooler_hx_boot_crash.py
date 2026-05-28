"""
Boot-time robustness check for the dry-cooler + heat-exchanger chain.

Setup mirrors the Paris BET demo site's `dry_cooler_prosumer`:

    ConstProfile  (BET-side fluid: t=36.4 °C, mdot=80 kg/s)
       │ FluidMix ───────────────────────────► hx_dc (heat_exchanger)
    ConstProfile  (air-side: t_air_in_c, phi_air_in_percent)
       │ Generic ────────────────────────────► dc_dc (dry_cooler)
                                                  │
       hx_dc  ── FluidMix order=0 ─────────────►  dc_dc

The HX is the bridge between the BET water loop (primary) and the BDRY
glycol-water loop (secondary). The dry cooler dissipates the BDRY heat to
ambient via fans. With `dry_cooler.in_service=True` from t=0 this used to
crash on the very first timestep: heat_exchanger.control_step called
t_m_to_deliver, which propagated down to dry_cooler._t_m_to_receive_init
and tripped `assert mdot_required_kg_per_s >= 0` because no upstream had
mapped a fluid input yet (all three reads were nan). One revision later
the same root cause surfaced one level up as a negative t_2_in_c in the HX
(observed as `t_2_in_c is negative (-101.7)` on the Paris demo site).

The dry-cooler controller now falls back to its nominal design point when
no upstream input or previous-step history is available, which lets the
upstream HX bootstrap a consistent first-step state. This test pins that
behavior with a positive steady-state assertion (energy balance, sensible
temperatures, non-zero exchanged heat).
"""

import numpy as np
import pandas as pd

from pandaprosumer import (
    create_empty_prosumer_container,
    create_period,
    create_controlled_const_profile,
    create_controlled_heat_exchanger,
    create_controlled_dry_cooler,
    DFData,
)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries


HX_PARAMS = {
    "t_1_in_nom_c": 46.0,
    "t_1_out_nom_c": 40.0,
    "t_2_in_nom_c": 39.0,
    "t_2_out_nom_c": 45.0,
    "mdot_2_nom_kg_per_s": 11.0,
    "delta_t_hot_default_c": 46.0 - 45.0,
    "max_q_kw": 1500.0,
    "min_delta_t_1_c": 5.0,
    "primary_fluid": "water",
}

DC_PARAMS = {
    "n_nom_rpm": 300,
    "p_fan_nom_kw": 0.671,
    "qair_nom_m3_per_h": 9900 * 14,
    "t_air_in_nom_c": 20.0,
    "t_air_out_nom_c": 42.0,
    "t_fluid_in_nom_c": 50.0,
    "t_fluid_out_nom_c": 41.0,
    "fans_number": 14,
    "adiabatic_mode": True,
    "min_delta_t_air_c": 3.0,
}

RESOL_S = 300
N_STEPS = 12


def _build_prosumer():
    prosumer = create_empty_prosumer_container()

    start = "2020-06-23 12:00:00"
    end = (
        pd.Timestamp(start)
        + N_STEPS * pd.Timedelta(f"00:00:{RESOL_S}")
        - pd.Timedelta("00:00:01")
    )
    period = create_period(prosumer, RESOL_S, start, end, "utc", "default")

    idx = pd.date_range(start, periods=N_STEPS, freq=f"{RESOL_S}s", tz="utc")

    bet_df = pd.DataFrame(
        {"bet_temp_c": [36.4] * N_STEPS, "bet_mdot_kg_per_s": [80.0] * N_STEPS},
        index=idx,
    )
    cp_bet_idx = create_controlled_const_profile(
        prosumer,
        input_columns=["bet_temp_c", "bet_mdot_kg_per_s"],
        result_columns=["bet_temp_c", "bet_mdot_kg_per_s"],
        data_source=DFData(bet_df),
        period=period,
        temp_fluid_map_idx=0,
        mdot_fluid_map_idx=1,
        level=0,
        order=0,
    )

    air_df = pd.DataFrame(
        {"t_air_in_c": [26.0] * N_STEPS, "phi_air_in_percent": [50.0] * N_STEPS},
        index=idx,
    )
    cp_air_idx = create_controlled_const_profile(
        prosumer,
        input_columns=["t_air_in_c", "phi_air_in_percent"],
        result_columns=["t_air_in_c", "phi_air_in_percent"],
        data_source=DFData(air_df),
        period=period,
        level=0,
        order=1,
    )

    hx_idx = create_controlled_heat_exchanger(
        prosumer, period=period, level=1, order=0, name="hx_dc", **HX_PARAMS
    )

    dc_idx = create_controlled_dry_cooler(
        prosumer, period=period, level=1, order=1, name="dc_dc",
        in_service=True, **DC_PARAMS,
    )

    FluidMixMapping(
        container=prosumer, initiator_id=cp_bet_idx, responder_id=hx_idx, order=0,
    )
    GenericMapping(
        container=prosumer,
        initiator_id=cp_air_idx,
        initiator_column=["t_air_in_c", "phi_air_in_percent"],
        responder_id=dc_idx,
        responder_column=["t_air_in_c", "phi_air_in_percent"],
        order=0,
    )
    FluidMixMapping(
        container=prosumer, initiator_id=hx_idx, responder_id=dc_idx, order=0,
    )

    return prosumer, period


def test_dry_cooler_hx_chain_boots_into_steady_state():
    """hx_dc → dc_dc must boot into a consistent steady state at t=0.

    With dry_cooler.in_service=True from t=0 and no upstream fluid history,
    the dry-cooler controller must fall back to its nominal design point so
    the upstream HX can compute a sensible first-step operating state.
    """
    prosumer, period = _build_prosumer()
    run_timeseries(prosumer, period, True)

    hx_df = prosumer.time_series.loc[0].data_source.df
    dc_df = prosumer.time_series.loc[1].data_source.df

    assert not hx_df.isna().any().any(), f"HX results contain NaN:\n{hx_df}"
    assert not dc_df.isna().any().any(), f"Dry-cooler results contain NaN:\n{dc_df}"

    q_hx = hx_df["q_exchanged_kw"].to_numpy()
    q_dc = dc_df["q_exchanged_kw"].to_numpy()

    assert (q_hx > 0).all(), f"HX should exchange positive heat at every step, got {q_hx}"
    assert (q_dc > 0).all(), f"Dry cooler should dissipate positive heat at every step, got {q_dc}"
    np.testing.assert_allclose(
        q_hx, q_dc, rtol=0.02,
        err_msg="HX and dry cooler heat exchange should match (energy balance)",
    )

    assert (hx_df["t_1_in_c"] > hx_df["t_1_out_c"]).all(), "BET-side should be cooled by HX"
    assert (hx_df["t_2_out_c"] > hx_df["t_2_in_c"]).all(), "Secondary side should be heated by HX"
    assert (dc_df["t_fluid_in_c"] > dc_df["t_fluid_out_c"]).all(), "Dry cooler should cool the fluid"
    assert (dc_df["t_air_out_c"] >= dc_df["t_air_in_c"]).all(), "Air should be heated by dry cooler"

    assert (hx_df[["t_1_in_c", "t_1_out_c", "t_2_in_c", "t_2_out_c"]] >= 0).all().all(), \
        "All HX temperatures must be non-negative"
    assert (dc_df[["t_fluid_in_c", "t_fluid_out_c"]] >= 0).all().all(), \
        "All dry-cooler fluid temperatures must be non-negative"

    np.testing.assert_allclose(
        hx_df["t_2_out_c"].to_numpy(), dc_df["t_fluid_in_c"].to_numpy(), rtol=0.01,
        err_msg="HX secondary outlet should match dry-cooler fluid inlet",
    )
    np.testing.assert_allclose(
        hx_df["mdot_2_kg_per_s"].to_numpy(), dc_df["mdot_fluid_kg_per_s"].to_numpy(), rtol=0.01,
        err_msg="HX secondary mass flow should match dry-cooler fluid mass flow",
    )
