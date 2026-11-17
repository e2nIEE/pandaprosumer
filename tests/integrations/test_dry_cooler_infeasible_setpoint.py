"""
External-setpoint saturation for the dry cooler.

A dry cooler can only cool fluid (heat→air), not warm it. When an upstream
optimiser pushes a ``t_out_c`` setpoint that is warmer than the actual
supplied inlet temperature ``t_in_supplied_c``, the LMTD math goes through
the ``min_delta_t_air_c`` constraint branch which produces a negative
``mdot_fluid_kg_per_s``. The ``control_step`` "bypass" energy-balance code
then mixes the negative ``mdot_fluid`` against positive ``mdot_supplied``
to compute a "consistent" outlet temperature -- a mathematically tidy but
physically nonsensical result. For some input combinations the weighted-
average ``t_fluid_out_c`` lands strictly above ``t_fluid_in_c`` and trips
the safeguard assertion at the bottom of ``control_step``::

    assert round(t_fluid_out_c, 4) <= round(t_fluid_in_c, 4)

This is observed in a coupled loop when an upstream optimiser sets the dry
cooler outlet setpoint higher than the actual loop supply temperature
(because the loop hasn't accumulated enough heat to push the secondary
supply that high). The unguarded code either crashes (assertion fires) or
returns unphysical state that breaks downstream couplings.

This test pins the saturation behaviour: when ``t_out_c`` comes from a
mapped input (i.e. it's an externally-driven setpoint, not the nominal
design fallback) AND it asks for an outlet warmer than the supplied
inlet, the controller must stall cleanly -- ``q_exchanged_kw == 0``,
``mdot_fluid == mdot_supplied`` (pass-through), ``t_fluid_out == t_fluid_in``.
The pre-fix code crashes with the ``t_fluid_out > t_fluid_in`` assertion
for the same scenario.

The companion test in ``test_dry_cooler_hx_boot_crash.py`` exercises the
nominal-default path (``t_out_c`` input is NaN -> falls back to
``t_fluid_out_nom_c``) and must keep producing non-zero exchange via the
iterative convergence path. The two tests together pin both regimes.
"""

import numpy as np
import pandas as pd

from pandaprosumer import (
    create_empty_prosumer_container,
    create_period,
    create_controlled_const_profile,
    create_controlled_dry_cooler,
    DFData,
)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries


RESOL_S = 300
N_STEPS = 6

# Air conditions chosen so the adiabatic-saturated wet-bulb temperature lands
# around 19 °C -- typical summer conditions.
T_AIR_C = 26.0
PHI_AIR_PERCENT = 50.0

# Supply fluid is at 30 °C; the external setpoint asks for 39 °C (warmer).
# A dry cooler cannot warm fluid, so the controller must saturate: pass the
# fluid through unchanged (q=0, t_out=t_in).
T_FLUID_SUPPLIED_C = 30.0
MDOT_SUPPLIED_KG_PER_S = 80.0
T_OUT_SETPOINT_INFEASIBLE_C = 39.0   # > T_FLUID_SUPPLIED_C; physically impossible

DC_PARAMS = {
    "n_nom_rpm": 300,
    "p_fan_nom_kw": 0.671,
    "qair_nom_m3_per_h": 9900 * 70,
    "t_air_in_nom_c": 20.0,
    "t_air_out_nom_c": 42.0,
    "t_fluid_in_nom_c": 50.0,
    "t_fluid_out_nom_c": 41.0,
    "fans_number": 70,
    "adiabatic_mode": True,
    "min_delta_t_air_c": 3.0,
}


def _build_prosumer(t_out_setpoint_c):
    prosumer = create_empty_prosumer_container()

    start = "2026-06-09 12:00:00"
    end = (
        pd.Timestamp(start)
        + N_STEPS * pd.Timedelta(f"00:00:{RESOL_S}")
        - pd.Timedelta("00:00:01")
    )
    period = create_period(prosumer, RESOL_S, start, end, "utc", "default")

    idx = pd.date_range(start, periods=N_STEPS, freq=f"{RESOL_S}s", tz="utc")

    fluid_df = pd.DataFrame(
        {
            "fluid_temp_c": [T_FLUID_SUPPLIED_C] * N_STEPS,
            "fluid_mdot_kg_per_s": [MDOT_SUPPLIED_KG_PER_S] * N_STEPS,
        },
        index=idx,
    )
    cp_fluid_idx = create_controlled_const_profile(
        prosumer,
        input_columns=["fluid_temp_c", "fluid_mdot_kg_per_s"],
        result_columns=["fluid_temp_c", "fluid_mdot_kg_per_s"],
        data_source=DFData(fluid_df),
        period=period,
        temp_fluid_map_idx=0,
        mdot_fluid_map_idx=1,
        level=0, order=0,
    )

    air_df = pd.DataFrame(
        {
            "t_air_in_c": [T_AIR_C] * N_STEPS,
            "phi_air_in_percent": [PHI_AIR_PERCENT] * N_STEPS,
            "t_out_c_setpoint": [t_out_setpoint_c] * N_STEPS,
        },
        index=idx,
    )
    cp_air_idx = create_controlled_const_profile(
        prosumer,
        input_columns=["t_air_in_c", "phi_air_in_percent", "t_out_c_setpoint"],
        result_columns=["t_air_in_c", "phi_air_in_percent", "t_out_c_setpoint"],
        data_source=DFData(air_df),
        period=period,
        level=0, order=1,
    )

    dc_idx = create_controlled_dry_cooler(
        prosumer, period=period, level=1, order=0, name="dry_cooler",
        in_service=True, **DC_PARAMS,
    )

    FluidMixMapping(
        container=prosumer, initiator_id=cp_fluid_idx, responder_id=dc_idx, order=0,
    )
    GenericMapping(
        container=prosumer,
        initiator_id=cp_air_idx,
        initiator_column=["t_air_in_c", "phi_air_in_percent", "t_out_c_setpoint"],
        responder_id=dc_idx,
        responder_column=["t_air_in_c", "phi_air_in_percent", "t_out_c"],
        order=0,
    )

    return prosumer, period


def test_dry_cooler_saturates_when_external_setpoint_is_infeasible():
    """External ``t_out_c`` warmer than supplied inlet must stall cleanly.

    The pre-fix code either trips the ``t_fluid_out_c <= t_fluid_in_c``
    assertion in the bypass branch or returns unphysical state. The fix
    saturates ``t_out_required_c`` to ``t_in_supplied_c`` whenever the
    setpoint is mapped from an input AND is infeasible, so the LMTD math
    falls through to the explicit no-exchange branch.
    """
    prosumer, period = _build_prosumer(T_OUT_SETPOINT_INFEASIBLE_C)
    run_timeseries(prosumer, period, True)  # must not raise

    dc_df = prosumer.time_series.loc[0].data_source.df

    # Pass-through: no cooling, no heating, no fan power.
    np.testing.assert_allclose(
        dc_df["t_fluid_out_c"].to_numpy(),
        np.full(N_STEPS, T_FLUID_SUPPLIED_C),
        atol=1e-6,
        err_msg=(
            "With infeasible setpoint t_out_c > t_in_supplied, the dry cooler "
            "must pass fluid through unchanged (t_out == t_in)."
        ),
    )
    np.testing.assert_allclose(
        dc_df["t_fluid_in_c"].to_numpy(),
        np.full(N_STEPS, T_FLUID_SUPPLIED_C),
        atol=1e-6,
    )
    np.testing.assert_allclose(
        dc_df["q_exchanged_kw"].to_numpy(),
        np.zeros(N_STEPS),
        atol=1e-6,
        err_msg="Saturated dry cooler must exchange zero heat.",
    )
    np.testing.assert_allclose(
        dc_df["mdot_air_kg_per_s"].to_numpy(),
        np.zeros(N_STEPS),
        atol=1e-6,
        err_msg="Saturated dry cooler must have zero air mass flow.",
    )

    # Hard assertion the pre-fix code violates: the dry cooler must never
    # report an outlet warmer than its inlet, regardless of setpoint.
    assert (dc_df["t_fluid_out_c"] <= dc_df["t_fluid_in_c"] + 1e-9).all(), (
        "Dry cooler reported t_fluid_out_c > t_fluid_in_c -- this is the "
        "exact regression the fix targets."
    )


def test_dry_cooler_obeys_feasible_external_setpoint():
    """When the external setpoint IS feasible, the cooler must do real work.

    Counter-test to the saturation case: with ``t_out_c = 25 °C`` (below
    the supplied 30 °C inlet), the cooler is asked for a sensible cool-
    down. It must deliver positive q_exchanged and a t_fluid_out close to
    the setpoint (within the LMTD model's air-side approach).
    """
    feasible_setpoint_c = 25.0  # < T_FLUID_SUPPLIED_C
    prosumer, period = _build_prosumer(feasible_setpoint_c)
    run_timeseries(prosumer, period, True)

    dc_df = prosumer.time_series.loc[0].data_source.df

    assert (dc_df["q_exchanged_kw"] > 0).all(), (
        f"Feasible setpoint must produce positive exchange, got "
        f"{dc_df['q_exchanged_kw'].to_numpy()}"
    )
    assert (dc_df["t_fluid_out_c"] < dc_df["t_fluid_in_c"]).all(), (
        "Feasible cooling: t_fluid_out must be strictly below t_fluid_in."
    )
    # The cooler may not hit the setpoint exactly (air-side approach
    # limit), but t_fluid_out should be in the ballpark.
    assert (dc_df["t_fluid_out_c"] <= T_FLUID_SUPPLIED_C).all()
