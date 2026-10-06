"""External charge / discharge setpoints on the StratifiedHeatStorage.

An external dispatcher (a MILP supervisor, an optimiser result replayed as a
time series, ...) can impose the storage charge and/or discharge mass flow
through the two controller inputs ``mdot_charge_setpoint_kg_per_s`` and
``mdot_discharge_setpoint_kg_per_s``, mapped like any other input (here from a
``ConstProfileController`` through a ``GenericMapping``).

Contract under test
-------------------
- NaN (input not mapped) or a negative value means "no setpoint": the storage's
  own dispatch logic applies for that timestep. ``0.0`` IS a setpoint (force
  no charge / no discharge).
- A charge setpoint is clamped to what upstream actually delivers -- the tank
  can never be charged with mass it did not receive -- and is ignored when the
  tank is already full (same energy-budget test as the request side).
- Whatever is forced, the mass balances close every timestep:
  ``mdot_charge + mdot_bypass == mdot_received`` and
  ``mdot_delivered == mdot_bypass + mdot_discharge``; the free variable (the
  other flow, or the bypass) is chosen so the demand energy is met when
  possible.
- The request to the upstream producer is aligned with the forced split, so
  the source⇄SHS and SHS⇄demand FluidMix interfaces both conserve mass and
  energy (the four AGENTS.md invariants).
"""

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

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

from tests.integrations.test_overflow_strategy_consistency import _assert_interface_consistent


CHARGE_COL = "mdot_charge_setpoint_kg_per_s"
DISCHARGE_COL = "mdot_discharge_setpoint_kg_per_s"

N_LAYERS = 20
MAX_DT_S = 30
RESOL_S = 300
N_STEPS = 8
TANK_H = 10.0
TANK_R = 1.495
T_EXT = 22.5
MIN_USEFUL = 55.0

T_FEED_DEMAND = 58.0
T_RETURN_DEMAND = 51.0
Q_DEMAND = 150.0
T_EVAP_IN = 36.4


def _build(charge_setpoints=None, discharge_setpoints=None, *, with_hp=True,
           hp_max_p_comp_kw=400.0, init_layer_temps_c=None, q_demand_kw=Q_DEMAND,
           t_charge_target_c=np.nan):
    """HP -> SHS -> HD chain (or SHS -> HD when ``with_hp`` is False).

    ``charge_setpoints`` / ``discharge_setpoints``: per-step lists mapped onto
    the SHS setpoint inputs; ``None`` leaves the input unmapped (NaN).
    Returns ``(prosumer, period, positions)`` where positions index
    ``prosumer.time_series``.
    """
    prosumer = create_empty_prosumer_container()
    start = "2020-01-01 00:00:00"
    end = pd.Timestamp(start) + N_STEPS * pd.Timedelta(f"00:00:{RESOL_S}") - pd.Timedelta("00:00:01")
    period = create_period(prosumer, RESOL_S, start, end, "utc", "default")
    idx = pd.date_range(start, periods=N_STEPS, freq=f"{RESOL_S}s", tz="utc")

    columns = {
        "t_evap_in_c": [T_EVAP_IN] * N_STEPS,
        "q_demand_kw": [q_demand_kw] * N_STEPS,
        "t_feed_demand_c": [T_FEED_DEMAND] * N_STEPS,
        "t_return_demand_c": [T_RETURN_DEMAND] * N_STEPS,
    }
    if charge_setpoints is not None:
        columns[CHARGE_COL] = list(charge_setpoints)
    if discharge_setpoints is not None:
        columns[DISCHARGE_COL] = list(discharge_setpoints)
    data = pd.DataFrame(columns, index=idx)

    cp_idx = create_controlled_const_profile(
        prosumer, input_columns=list(data.columns), result_columns=list(data.columns),
        data_source=DFData(data), period=period, level=0, order=0,
    )

    pos = {}
    order = 0
    if with_hp:
        hp_idx = create_controlled_heat_pump(
            prosumer, level=1, order=order, period=period, name="hp",
            carnot_efficiency=0.5, pinch_c=0, delta_t_evap_c=4.1,
            min_p_comp_kw=0.1, max_p_comp_kw=hp_max_p_comp_kw,
            delta_t_hot_default_c=5, max_cop=4.0,
        )
        pos["hp"] = order
        order += 1

    if init_layer_temps_c is None:
        init_layer_temps_c = list(np.linspace(T_RETURN_DEMAND, 60.0, N_LAYERS))
    shs_idx = create_controlled_stratified_heat_storage(
        prosumer, tank_height_m=TANK_H, tank_internal_radius_m=TANK_R, n_layers=N_LAYERS,
        max_dt_s=MAX_DT_S, min_useful_temp_c=MIN_USEFUL, t_ext_c=T_EXT,
        init_layer_temps_c=list(init_layer_temps_c), t_charge_target_c=t_charge_target_c,
        period=period, level=1, order=order, name="shs",
    )
    pos["shs"] = order
    order += 1

    hd_idx = create_controlled_heat_demand(
        prosumer, level=1, order=order, period=period, name="hd",
        t_feed_demand_c=T_FEED_DEMAND, t_return_demand_c=T_RETURN_DEMAND,
    )
    pos["hd"] = order

    if with_hp:
        GenericMapping(container=prosumer, initiator_id=cp_idx, initiator_column="t_evap_in_c",
                       responder_id=hp_idx, responder_column="t_evap_in_c", order=0)
    GenericMapping(
        container=prosumer, initiator_id=cp_idx,
        initiator_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
        responder_id=hd_idx,
        responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
        order=1,
    )
    setpoint_cols = [c for c in (CHARGE_COL, DISCHARGE_COL) if c in data.columns]
    if setpoint_cols:
        GenericMapping(container=prosumer, initiator_id=cp_idx, initiator_column=setpoint_cols,
                       responder_id=shs_idx, responder_column=setpoint_cols, order=2)
    if with_hp:
        FluidMixMapping(container=prosumer, initiator_id=hp_idx, responder_id=shs_idx, order=0)
    FluidMixMapping(container=prosumer, initiator_id=shs_idx, responder_id=hd_idx, order=0)

    return prosumer, period, pos


def _run(**kwargs):
    prosumer, period, pos = _build(**kwargs)
    run_timeseries(prosumer, period, True)
    dfs = {name: prosumer.time_series.loc[i].data_source.df for name, i in pos.items()}
    return dfs


def _shs_controller(prosumer):
    return next(c for c in prosumer.controller.object
                if c.name_class() == "stratified_heat_storage_controller")


def _bypass(shs_df):
    return shs_df["mdot_delivered_kg_per_s"] - shs_df["mdot_discharge_kg_per_s"]


def _assert_shs_balances(shs_df):
    """No NaN, no negative flow, and the two mass balances close every step."""
    assert not shs_df.isna().any().any(), shs_df[shs_df.isna().any(axis=1)]
    for col in ("mdot_received_kg_per_s", "mdot_charge_kg_per_s",
                "mdot_discharge_kg_per_s", "mdot_delivered_kg_per_s"):
        assert (shs_df[col] >= -1e-9).all(), f"{col} negative:\n{shs_df[col]}"
    bypass = _bypass(shs_df)
    assert (bypass >= -1e-9).all(), f"bypass negative:\n{bypass}"
    np.testing.assert_allclose(shs_df["mdot_charge_kg_per_s"] + bypass,
                               shs_df["mdot_received_kg_per_s"], atol=1e-9,
                               err_msg="charge + bypass != received")


def _assert_demand_interface(dfs):
    _assert_interface_consistent(dfs["shs"], dfs["hd"],
                                 "t_delivered_out_c", "t_delivered_in_c",
                                 "mdot_delivered_kg_per_s", "q_delivered_kw")


def _assert_source_interface(dfs):
    """HP condenser duty and SHS received power cross the same pipe."""
    q_cond = dfs["hp"]["q_cond_kw"].values
    q_received = dfs["shs"]["q_received_kw"].values
    diff = np.abs(q_cond - q_received)
    tol = 1.0 + 0.005 * np.maximum(np.abs(q_cond), np.abs(q_received))
    assert (diff <= tol).all(), f"q_cond={np.round(q_cond, 2)}\nq_received={np.round(q_received, 2)}"
    np.testing.assert_allclose(dfs["hp"]["mdot_cond_kg_per_s"], dfs["shs"]["mdot_received_kg_per_s"],
                               rtol=1e-3, atol=1e-3)


class TestNoSetpoint:
    def test_negative_setpoint_equals_unmapped(self):
        """A negative value is 'no setpoint': bit-identical to leaving the input unmapped."""
        free = _run()
        negative = _run(charge_setpoints=[-1.0] * N_STEPS, discharge_setpoints=[-1.0] * N_STEPS)
        assert_frame_equal(free["shs"], negative["shs"])
        assert_frame_equal(free["hd"], negative["hd"])
        assert_frame_equal(free["hp"], negative["hp"])


class TestForcedCharge:
    def test_charge_within_received_is_applied_exactly(self):
        setpoint = 2.0
        dfs = _run(charge_setpoints=[setpoint] * N_STEPS)
        shs = dfs["shs"]
        np.testing.assert_allclose(shs["mdot_charge_kg_per_s"], setpoint, atol=1e-6)
        assert (shs["mdot_received_kg_per_s"] > setpoint).all()
        _assert_shs_balances(shs)
        _assert_demand_interface(dfs)
        _assert_source_interface(dfs)
        # The free discharge / bypass still serve the demand.
        np.testing.assert_allclose(dfs["hd"]["q_uncovered_kw"], 0.0, atol=1.0)

    def test_charge_exceeding_received_is_clamped(self):
        """A power-capped HP cannot deliver 50 kg/s: the charge is clamped to what arrived."""
        dfs = _run(charge_setpoints=[50.0] * N_STEPS, hp_max_p_comp_kw=30.0)
        shs = dfs["shs"]
        assert (shs["mdot_charge_kg_per_s"] <= shs["mdot_received_kg_per_s"] + 1e-9).all()
        assert (shs["mdot_charge_kg_per_s"] < 50.0).all()
        assert (shs["q_charge_kw"] >= -1e-6).all()
        _assert_shs_balances(shs)
        _assert_demand_interface(dfs)
        _assert_source_interface(dfs)

    def test_zero_charge_setpoint_forces_no_charge(self):
        """0.0 is a setpoint, not 'free': the cold tank is never charged."""
        forced = _run(charge_setpoints=[0.0] * N_STEPS)
        free = _run()
        assert (free["shs"]["mdot_charge_kg_per_s"] > 0).any(), "fixture must charge when free"
        np.testing.assert_array_equal(forced["shs"]["mdot_charge_kg_per_s"], 0.0)
        _assert_shs_balances(forced["shs"])
        _assert_demand_interface(forced)
        _assert_source_interface(forced)

    def test_charge_setpoint_on_full_tank_is_ignored(self):
        """A full tank cannot be charged; request and split agree so no energy leaks."""
        hot = [65.0] * N_LAYERS
        dfs = _run(charge_setpoints=[3.0] * N_STEPS, init_layer_temps_c=hot, t_charge_target_c=65.0)
        shs = dfs["shs"]
        # Full at the start: the setpoint is ignored. Losses and the demand return
        # eventually free some capacity, after which the setpoint applies again.
        assert shs["mdot_charge_kg_per_s"].iloc[0] == 0.0
        assert (shs["mdot_charge_kg_per_s"] <= 3.0 + 1e-9).all()
        _assert_shs_balances(shs)
        _assert_demand_interface(dfs)
        _assert_source_interface(dfs)

    def test_setpoint_applies_only_on_its_own_timestep(self):
        """Inputs are reset every step: a setpoint does not stick once it is gone."""
        setpoint = 2.0
        forced_steps = 3
        setpoints = [setpoint] * forced_steps + [-1.0] * (N_STEPS - forced_steps)
        dfs = _run(charge_setpoints=setpoints)
        charge = dfs["shs"]["mdot_charge_kg_per_s"].values
        np.testing.assert_allclose(charge[:forced_steps], setpoint, atol=1e-6)
        assert not np.isclose(charge[forced_steps:], setpoint, atol=1e-6).any()
        _assert_shs_balances(dfs["shs"])
        _assert_demand_interface(dfs)
        _assert_source_interface(dfs)


class TestForcedDischarge:
    def test_discharge_with_upstream_off(self):
        """The MILP use case: source off, the storage alone covers the demand at the imposed flow."""
        setpoint = 1.5
        hot = list(np.linspace(58.0, 65.0, N_LAYERS))
        dfs = _run(discharge_setpoints=[setpoint] * N_STEPS, with_hp=False, init_layer_temps_c=hot)
        shs = dfs["shs"]
        np.testing.assert_allclose(shs["mdot_discharge_kg_per_s"], setpoint, atol=1e-6)
        np.testing.assert_array_equal(shs["mdot_received_kg_per_s"], 0.0)
        np.testing.assert_array_equal(shs["mdot_charge_kg_per_s"], 0.0)
        np.testing.assert_allclose(shs["mdot_delivered_kg_per_s"], setpoint, atol=1e-6)
        np.testing.assert_allclose(dfs["hd"]["mdot_kg_per_s"], setpoint, atol=1e-6)
        assert (shs["q_discharge_kw"] > 0).all()
        _assert_shs_balances(shs)
        _assert_demand_interface(dfs)

    def test_discharge_with_upstream_on_bypass_covers_residual(self):
        """Forced discharge covers part of the demand; the bypass from the HP covers the rest."""
        setpoint = 1.0
        dfs = _run(discharge_setpoints=[setpoint] * N_STEPS)
        shs = dfs["shs"]
        np.testing.assert_allclose(shs["mdot_discharge_kg_per_s"], setpoint, atol=1e-6)
        assert (_bypass(shs) > 0).all()
        np.testing.assert_allclose(dfs["hd"]["q_uncovered_kw"], 0.0, atol=1.0)
        _assert_shs_balances(shs)
        _assert_demand_interface(dfs)
        _assert_source_interface(dfs)

    def test_zero_discharge_setpoint_forces_no_discharge(self):
        """Demand larger than a weak HP can serve: free logic discharges, 0.0 forbids it."""
        hot = list(np.linspace(58.0, 65.0, N_LAYERS))
        free = _run(hp_max_p_comp_kw=10.0, init_layer_temps_c=hot)
        assert (free["shs"]["mdot_discharge_kg_per_s"] > 0).any(), "fixture must discharge when free"
        forced = _run(discharge_setpoints=[0.0] * N_STEPS, hp_max_p_comp_kw=10.0, init_layer_temps_c=hot)
        np.testing.assert_array_equal(forced["shs"]["mdot_discharge_kg_per_s"], 0.0)
        assert (forced["hd"]["q_uncovered_kw"] > 0).all()
        _assert_shs_balances(forced["shs"])
        _assert_demand_interface(forced)
        _assert_source_interface(forced)


class TestBothForced:
    def test_both_setpoints_are_applied(self):
        charge, discharge = 1.0, 0.5
        dfs = _run(charge_setpoints=[charge] * N_STEPS, discharge_setpoints=[discharge] * N_STEPS)
        shs = dfs["shs"]
        np.testing.assert_allclose(shs["mdot_charge_kg_per_s"], charge, atol=1e-6)
        np.testing.assert_allclose(shs["mdot_discharge_kg_per_s"], discharge, atol=1e-6)
        np.testing.assert_allclose(shs["mdot_delivered_kg_per_s"],
                                   shs["mdot_received_kg_per_s"] - charge + discharge, atol=1e-6)
        _assert_shs_balances(shs)
        _assert_demand_interface(dfs)
        _assert_source_interface(dfs)


class TestInputWiring:
    def test_setpoints_are_declared_inputs(self):
        prosumer, _, _ = _build()
        shs = _shs_controller(prosumer)
        assert CHARGE_COL in shs.input_columns
        assert DISCHARGE_COL in shs.input_columns

    def test_unmapped_setpoints_read_as_nan(self):
        prosumer, _, _ = _build()
        shs = _shs_controller(prosumer)
        assert np.isnan(shs._get_input(CHARGE_COL, prosumer))
        assert np.isnan(shs._get_input(DISCHARGE_COL, prosumer))
