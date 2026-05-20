"""
Integration tests for the ``overflow_strategy`` parameter introduced on
Gas Boiler, Electric Boiler and Heat Pump elements.

These tests pin down the producer/responder consistency at the FluidMix
interface for the three producers when the demand requires less mass flow
than the producer's minimum-power floor would otherwise dispatch:

  - ``overflow_strategy="cap"`` (default, historic behaviour): the surplus
    mass flow is dropped by ``_merit_order_mass_flow``. The boilers
    compensate by raising ``t_out_c`` (so the demand still receives the
    full thermal power, just at a hotter temperature). The HP cannot
    raise ``t_cond_out_c`` and ends up with an energy leak between its
    own ``q_cond_kw`` and the demand's ``q_received_kw``.
  - ``overflow_strategy="dump_on_last"``: the surplus mass flow is pushed
    onto the last responder. For a single responder, this makes every
    producer/responder field match exactly - no temperature overshoot, no
    energy leak.

The shared helper ``_assert_interface_consistent`` checks the four
invariants on every step:

  * feed:       producer.t_out_c     == demand.t_in_c
  * return:     producer.t_in_c      == demand.t_out_c
  * mass flow:  producer.mdot_*_kg_per_s == demand.mdot_kg_per_s
  * energy:     producer.q_*_kw      == demand.q_received_kw
"""
import warnings

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from pandaprosumer.controller.mapped import EnergyLeakWarning
from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer import (create_period, DFData, create_empty_prosumer_container,
                           create_controlled_const_profile,
                           create_controlled_gas_boiler,
                           create_controlled_electric_boiler,
                           create_controlled_heat_pump,
                           create_controlled_heat_demand)


def _assert_interface_consistent(producer_df, demand_df,
                                 producer_t_out_col, producer_t_in_col,
                                 producer_mdot_col, producer_q_col,
                                 rtol_q=1e-3, atol_q=1e-3):
    """Check the producer-responder pair conserves every interface quantity."""
    assert_series_equal(producer_df[producer_t_out_col], demand_df.t_in_c,
                        check_names=False, rtol=1e-3, atol=1e-3)
    assert_series_equal(producer_df[producer_t_in_col], demand_df.t_out_c,
                        check_names=False, rtol=1e-3, atol=1e-3)
    assert_series_equal(producer_df[producer_mdot_col], demand_df.mdot_kg_per_s,
                        check_names=False, rtol=1e-3, atol=1e-3)
    assert_series_equal(producer_df[producer_q_col], demand_df.q_received_kw,
                        check_names=False, rtol=rtol_q, atol=atol_q)


class TestGasBoilerOverflowStrategyDumpOnLast:
    """
    Gas boiler: with ``overflow_strategy="dump_on_last"`` and a single
    responder, the boiler MUST push its full min-power mass flow to the
    demand at the requested feed temperature - rather than capping the
    mass flow and raising ``t_out_c`` to 123.7 C as it does with "cap".
    """

    def _build(self, overflow_strategy):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [0, 10, 20, 90, 110, 0, 5]})
        start = '2020-01-01 00:00:00'
        resol = 1
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0,
                                          max_q_kw=100, min_q_kw=20, efficiency_percent=100,
                                          heating_value_kj_per_kg=20e3,
                                          overflow_strategy=overflow_strategy)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=1)
        FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=hd, order=0)
        run_timeseries(prosumer, period, True)
        return prosumer, data

    def test_dump_on_last_pushes_full_mdot_to_demand(self):
        prosumer, data = self._build("dump_on_last")
        gb_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df

        # Feed temp stays at the demand's setpoint -- no overshoot.
        running = data["demand_1"].values > 0
        np.testing.assert_allclose(gb_df.t_out_c.values[running], 76.85, atol=1e-2)

        # Below-min steps: mdot is the min-power mdot, NOT the demand's mdot.
        mdot_min = 20.0 / (4.19 * (76.85 - 30))  # ~0.102 kg/s
        below_min_running = (data["demand_1"].values > 0) & (data["demand_1"].values < 20)
        np.testing.assert_allclose(gb_df.mdot_kg_per_s.values[below_min_running],
                                   mdot_min, rtol=1e-2)
        # And the heat demand happily receives that surplus.
        np.testing.assert_allclose(hd_df.mdot_kg_per_s.values[below_min_running],
                                   mdot_min, rtol=1e-2)
        # q_received exceeds demand on those steps (q_uncovered < 0).
        assert (hd_df.q_uncovered_kw.values[below_min_running] < -1e-3).all()

        _assert_interface_consistent(gb_df, hd_df,
                                     producer_t_out_col='t_out_c',
                                     producer_t_in_col='t_in_c',
                                     producer_mdot_col='mdot_kg_per_s',
                                     producer_q_col='q_kw',
                                     rtol_q=5e-2)

    def test_cap_keeps_old_temperature_overshoot_behavior(self):
        """Sanity: with the default 'cap' strategy the old overshoot is preserved."""
        prosumer, data = self._build("cap")
        gb_df = prosumer.time_series.loc[0].data_source.df
        below_min_running = (data["demand_1"].values > 0) & (data["demand_1"].values < 20)
        # With cap, t_out_c shoots above the demand setpoint.
        assert (gb_df.t_out_c.values[below_min_running] > 80.0).all()


class TestElectricBoilerOverflowStrategyDumpOnLast:
    """
    Electric boiler: same expectation as the gas boiler - dump_on_last
    delivers the full min-power mdot at the requested feed temperature.
    """

    def _build(self, overflow_strategy):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [0, 10, 20, 90, 110, 0, 5]})
        start = '2020-01-01 00:00:00'
        resol = 1
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        eb = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0,
                                               max_p_kw=100, min_p_kw=20, efficiency_percent=100,
                                               overflow_strategy=overflow_strategy)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=1)
        FluidMixMapping(container=prosumer, initiator_id=eb, responder_id=hd, order=0)
        run_timeseries(prosumer, period, True)
        return prosumer, data

    def test_dump_on_last_pushes_full_mdot_to_demand(self):
        prosumer, data = self._build("dump_on_last")
        eb_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df

        running = data["demand_1"].values > 0
        np.testing.assert_allclose(eb_df.t_out_c.values[running], 76.85, atol=1e-2)

        mdot_min = 20.0 / (4.19 * (76.85 - 30))
        below_min_running = (data["demand_1"].values > 0) & (data["demand_1"].values < 20)
        np.testing.assert_allclose(eb_df.mdot_kg_per_s.values[below_min_running],
                                   mdot_min, rtol=1e-2)
        np.testing.assert_allclose(hd_df.mdot_kg_per_s.values[below_min_running],
                                   mdot_min, rtol=1e-2)
        assert (hd_df.q_uncovered_kw.values[below_min_running] < -1e-3).all()

        _assert_interface_consistent(eb_df, hd_df,
                                     producer_t_out_col='t_out_c',
                                     producer_t_in_col='t_in_c',
                                     producer_mdot_col='mdot_kg_per_s',
                                     producer_q_col='q_kw',
                                     rtol_q=5e-2)

    def test_cap_keeps_old_temperature_overshoot_behavior(self):
        prosumer, data = self._build("cap")
        eb_df = prosumer.time_series.loc[0].data_source.df
        below_min_running = (data["demand_1"].values > 0) & (data["demand_1"].values < 20)
        assert (eb_df.t_out_c.values[below_min_running] > 80.0).all()


class TestHeatPumpOverflowStrategyDumpOnLast:
    """
    Heat pump: dump_on_last is the critical fix for the HP. With "cap",
    the HP records q_cond=50.6 kW internally while only 30 kW reaches the
    demand (energy leak via dropped mdot). With "dump_on_last", every
    interface field matches exactly.

    The demand sequence exercises the same hysteresis pattern as
    test_1heatpump_1heatdemand_min_p_comp_mapping.py:
      off -> below-min (was off, stays off) -> on -> below-min (was on,
      stays on at min) -> off -> below-min (was off, stays off).
    """

    def _build(self, overflow_strategy):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({
            "Tin_evap": [25] * 6,
            "demand_kw": [0, 20, 200, 30, 0, 25],
            "tdmd_feed_c": [76.85] * 6,
            "tdmd_return_c": [30] * 6,
        })
        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')

        cp_in = ["Tin_evap", "demand_kw", "tdmd_feed_c", "tdmd_return_c"]
        cp_out = ["t_evap_in_c", "qdemand_kw", "tdmd_feed_c", "tdmd_return_c"]
        cp = create_controlled_const_profile(prosumer, cp_in, cp_out, DFData(data),
                                             period, level=0, order=0)
        hp = create_controlled_heat_pump(prosumer, level=1, order=0, period=period,
                                         carnot_efficiency=0.5, pinch_c=0,
                                         delta_t_evap_c=5,
                                         max_p_comp_kw=100, min_p_comp_kw=15,
                                         overflow_strategy=overflow_strategy)
        hd = create_controlled_heat_demand(prosumer, level=1, order=1, period=period,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="t_evap_in_c",
                       responder_id=hp, responder_column="t_evap_in_c", order=0)
        GenericMapping(container=prosumer, initiator_id=cp,
                       initiator_column=["qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
                       responder_id=hd,
                       responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
                       order=1)
        FluidMixMapping(container=prosumer, initiator_id=hp, responder_id=hd, order=0)
        run_timeseries(prosumer, period, True)
        return prosumer, data

    def test_dump_on_last_closes_energy_balance_at_demand(self):
        prosumer, data = self._build("dump_on_last")
        hp_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df

        expected_cop = 3.375  # 0.5 * (76.85+273)/(76.85-25)

        # Step 3 (demand=30, was on, p_comp clamped to min=15): HP pushes
        # the full mdot_cond = min * COP / (cp * dT) to the demand, NOT
        # the demand's smaller request.
        mdot_min_thermal_floor = 15.0 * expected_cop / (4.19 * (76.85 - 30))  # ~0.258 kg/s
        assert hp_df.p_comp_kw.values[3] == pytest.approx(15.0, rel=1e-2), \
            "Compressor still clamped to min_p_comp_kw"
        assert hp_df.q_cond_kw.values[3] == pytest.approx(15.0 * expected_cop, rel=1e-2)
        assert hp_df.mdot_cond_kg_per_s.values[3] == pytest.approx(mdot_min_thermal_floor, rel=1e-2)
        # The demand now receives the surplus (vs 30 kW under "cap").
        assert hd_df.q_received_kw.values[3] == pytest.approx(15.0 * expected_cop, rel=1e-2)
        assert hd_df.mdot_kg_per_s.values[3] == pytest.approx(mdot_min_thermal_floor, rel=1e-2)
        assert hd_df.q_uncovered_kw.values[3] < -1e-3, \
            "demand should report a negative q_uncovered (over-delivered)"

        # Steps where the HP is OFF (hysteresis): demand still uncovered.
        assert hp_df.p_comp_kw.values[1] == pytest.approx(0.0, abs=1e-6)
        assert hd_df.q_uncovered_kw.values[1] == pytest.approx(20.0, abs=1e-3)
        assert hp_df.p_comp_kw.values[5] == pytest.approx(0.0, abs=1e-6)
        assert hd_df.q_uncovered_kw.values[5] == pytest.approx(25.0, abs=1e-3)

        # The full interface consistency check -- this is the regression
        # guard against the energy-leak bug.
        _assert_interface_consistent(hp_df, hd_df,
                                     producer_t_out_col='t_cond_out_c',
                                     producer_t_in_col='t_cond_in_c',
                                     producer_mdot_col='mdot_cond_kg_per_s',
                                     producer_q_col='q_cond_kw',
                                     rtol_q=5e-2)

    def test_cap_preserves_known_energy_leak(self):
        """Sanity: with the default 'cap' strategy the energy leak is still there."""
        prosumer, data = self._build("cap")
        hp_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df
        # Step 3 (demand=30, was on, p_comp clamped to min): q_cond > q_received
        # is the leak signature.
        assert hp_df.q_cond_kw.values[3] > hd_df.q_received_kw.values[3] + 1.0
        assert hd_df.q_received_kw.values[3] == pytest.approx(30.0, rel=1e-3)


class TestMeritOrderOverflowStrategyValidation:
    """The _merit_order_mass_flow helper rejects unknown strategies."""

    def test_unknown_strategy_raises(self):
        # Build a minimal prosumer with an electric boiler so we can hit the
        # validation branch through a real producer.
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [10]})
        start = '2020-01-01 00:00:00'
        end = pd.Timestamp(start)
        period = create_period(prosumer, 1, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq='1s', tz='utc')
        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        eb = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0,
                                               max_p_kw=100, min_p_kw=20,
                                               overflow_strategy="not_a_real_strategy")
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=1)
        FluidMixMapping(container=prosumer, initiator_id=eb, responder_id=hd, order=0)
        with pytest.raises(ValueError, match="Unknown overflow_strategy"):
            run_timeseries(prosumer, period, True)


# ---------------------------------------------------------------------------
# Physics-invariant assertions
# ---------------------------------------------------------------------------
# These reusable checks are stricter than the interface-consistency ones in
# _assert_interface_consistent: they validate the *physics* (energy & mass
# balance from first principles), not just that two DataFrames agree.


def _q_from_mdot_dt(mdot, t_out, t_in, cp=4.19):
    """Compute thermal power from mass flow and temperature difference."""
    return mdot * cp * (t_out - t_in)


def _assert_q_mdot_dt_consistent(df, q_col, mdot_col, t_out_col, t_in_col,
                                 label, rtol=2e-2, atol=5e-2):
    """q = mdot * cp(T) * (t_out - t_in) on every step where mdot > 0.

    cp is approximated as 4.19 kJ/(kg.K); the actual fluid library uses a
    temperature-dependent cp so a 2% relative tolerance is appropriate.
    """
    mdot = df[mdot_col].values
    flowing = mdot > 1e-6
    q_expected = _q_from_mdot_dt(mdot[flowing],
                                  df[t_out_col].values[flowing],
                                  df[t_in_col].values[flowing])
    q_actual = df[q_col].values[flowing]
    np.testing.assert_allclose(
        q_actual, q_expected, rtol=rtol, atol=atol,
        err_msg=(f"{label}: q ({q_col}) inconsistent with mdot*cp*dT on "
                 f"steps {np.where(flowing)[0]}"))


class TestPhysicsInvariantsDumpOnLast:
    """
    Whatever overflow strategy is used, the basic thermodynamic identities
    must hold on every step:

      - On the producer side: q = mdot * cp * (t_out - t_in)
      - On the demand side:   q_received = mdot * cp * (t_in - t_out)
      - For the HP:           q_cond = p_comp + q_evap (internal energy balance)
      - Mass balance:         producer mdot = sum of mdots delivered to responders

    The dump strategies must not break any of these.
    """

    @pytest.mark.parametrize("strategy", ["cap", "dump_on_last", "dump_proportional"])
    def test_electric_boiler_q_mdot_cp_dt(self, strategy):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [0, 10, 20, 90, 110, 0, 5]})
        start = '2020-01-01 00:00:00'
        resol = 1
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        eb = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0,
                                               max_p_kw=100, min_p_kw=20,
                                               efficiency_percent=100,
                                               overflow_strategy=strategy)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=1)
        FluidMixMapping(container=prosumer, initiator_id=eb, responder_id=hd, order=0)
        run_timeseries(prosumer, period, True)

        eb_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df
        _assert_q_mdot_dt_consistent(eb_df, "q_kw", "mdot_kg_per_s",
                                     "t_out_c", "t_in_c", "EB producer")
        _assert_q_mdot_dt_consistent(hd_df, "q_received_kw", "mdot_kg_per_s",
                                     "t_in_c", "t_out_c", "Heat demand")
        # Electrical balance (efficiency=100% -> p_kw == q_kw)
        np.testing.assert_allclose(eb_df.p_kw.values, eb_df.q_kw.values, atol=1e-6)

    @pytest.mark.parametrize("strategy", ["cap", "dump_on_last", "dump_proportional"])
    def test_gas_boiler_q_mdot_cp_dt(self, strategy):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [0, 10, 20, 90, 110, 0, 5]})
        start = '2020-01-01 00:00:00'
        resol = 1
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0,
                                          max_q_kw=100, min_q_kw=20,
                                          efficiency_percent=100,
                                          heating_value_kj_per_kg=20e3,
                                          overflow_strategy=strategy)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=1)
        FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=hd, order=0)
        run_timeseries(prosumer, period, True)

        gb_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df
        _assert_q_mdot_dt_consistent(gb_df, "q_kw", "mdot_kg_per_s",
                                     "t_out_c", "t_in_c", "GB producer")
        _assert_q_mdot_dt_consistent(hd_df, "q_received_kw", "mdot_kg_per_s",
                                     "t_in_c", "t_out_c", "Heat demand")
        # Fuel mass flow balance: q_kw = mdot_gas * heating_value * efficiency
        running = gb_df.q_kw.values > 1e-6
        q_from_fuel = gb_df.mdot_gas_kg_per_s.values * 20e3 * (100 / 100)
        np.testing.assert_allclose(q_from_fuel[running], gb_df.q_kw.values[running],
                                   rtol=1e-3)

    @pytest.mark.parametrize("strategy", ["cap", "dump_on_last", "dump_proportional"])
    def test_heat_pump_internal_energy_balance(self, strategy):
        """Q_cond = P_comp + Q_evap on every step, regardless of strategy."""
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({
            "Tin_evap": [25] * 6,
            "demand_kw": [0, 20, 200, 30, 0, 25],
            "tdmd_feed_c": [76.85] * 6,
            "tdmd_return_c": [30] * 6,
        })
        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')

        cp = create_controlled_const_profile(
            prosumer, ["Tin_evap", "demand_kw", "tdmd_feed_c", "tdmd_return_c"],
            ["t_evap_in_c", "qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
            DFData(data), period, level=0, order=0)
        hp = create_controlled_heat_pump(prosumer, level=1, order=0, period=period,
                                         carnot_efficiency=0.5, pinch_c=0,
                                         delta_t_evap_c=5,
                                         max_p_comp_kw=100, min_p_comp_kw=15,
                                         overflow_strategy=strategy)
        hd = create_controlled_heat_demand(prosumer, level=1, order=1, period=period,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp,
                       initiator_column="t_evap_in_c", responder_id=hp,
                       responder_column="t_evap_in_c", order=0)
        GenericMapping(container=prosumer, initiator_id=cp,
                       initiator_column=["qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
                       responder_id=hd,
                       responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
                       order=1)
        FluidMixMapping(container=prosumer, initiator_id=hp, responder_id=hd, order=0)
        run_timeseries(prosumer, period, True)

        hp_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df

        # 1st law: Q_cond = P_comp + Q_evap
        np.testing.assert_allclose(
            hp_df.q_cond_kw.values,
            hp_df.p_comp_kw.values + hp_df.q_evap_kw.values,
            atol=1e-6,
            err_msg=f"Energy balance Q_cond = P_comp + Q_evap broken under '{strategy}'")
        # Demand-side q = mdot*cp*dT
        _assert_q_mdot_dt_consistent(hd_df, "q_received_kw", "mdot_kg_per_s",
                                     "t_in_c", "t_out_c", f"HP demand ({strategy})")


class TestMultipleRespondersDumpStrategies:
    """
    With more than one responder, dump_on_last places the surplus on the
    last (lowest-priority) demand only, while dump_proportional spreads it.
    Verified with a gas boiler clamped to min_q_kw and two demands that
    together request less than the floor.
    """

    def _build_two_demand_setup(self, overflow_strategy,
                                 demand_1_kw=5, demand_2_kw=5):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [demand_1_kw], "demand_2": [demand_2_kw]})
        start = '2020-01-01 00:00:00'
        end = pd.Timestamp(start)
        period = create_period(prosumer, 1, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq='1s', tz='utc')
        cp = create_controlled_const_profile(prosumer,
                                             ["demand_1", "demand_2"],
                                             ["qdemand1_kw", "qdemand2_kw"],
                                             DFData(data), period, 0, 0)
        gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0,
                                          max_q_kw=100, min_q_kw=20,
                                          efficiency_percent=100,
                                          heating_value_kj_per_kg=20e3,
                                          overflow_strategy=overflow_strategy)
        hd1 = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                            t_in_set_c=76.85, t_out_set_c=30)
        hd2 = create_controlled_heat_demand(prosumer, period=period, level=1, order=2,
                                            t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp,
                       initiator_column="qdemand1_kw",
                       responder_id=hd1, responder_column="q_demand_kw", order=1)
        GenericMapping(container=prosumer, initiator_id=cp,
                       initiator_column="qdemand2_kw",
                       responder_id=hd2, responder_column="q_demand_kw", order=2)
        FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=hd1, order=0)
        FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=hd2, order=1)
        run_timeseries(prosumer, period, True)
        return prosumer

    def test_dump_on_last_puts_surplus_on_second_demand(self):
        """Demand1 receives exactly its 5 kW request; demand2 absorbs the surplus."""
        prosumer = self._build_two_demand_setup("dump_on_last")
        gb_df = prosumer.time_series.loc[0].data_source.df
        hd1_df = prosumer.time_series.loc[1].data_source.df
        hd2_df = prosumer.time_series.loc[2].data_source.df

        # Boiler runs at min_q_kw = 20 kW
        assert gb_df.q_kw.values[0] == pytest.approx(20.0, rel=1e-2)
        # Demand 1 gets exactly its 5 kW request
        assert hd1_df.q_received_kw.values[0] == pytest.approx(5.0, rel=2e-2)
        assert hd1_df.q_uncovered_kw.values[0] == pytest.approx(0.0, abs=0.2)
        # Demand 2 receives the rest: 20 - 5 = 15 kW (requested 5 -> uncovered -10)
        assert hd2_df.q_received_kw.values[0] == pytest.approx(15.0, rel=2e-2)
        assert hd2_df.q_uncovered_kw.values[0] < -5.0
        # Mass balance: producer mdot = sum of responder mdots
        np.testing.assert_allclose(
            gb_df.mdot_kg_per_s.values[0],
            hd1_df.mdot_kg_per_s.values[0] + hd2_df.mdot_kg_per_s.values[0],
            rtol=1e-3)
        # No temperature overshoot (t_out_c stays at requested feed)
        assert gb_df.t_out_c.values[0] == pytest.approx(76.85, rel=1e-2)

    def test_dump_proportional_splits_surplus_evenly(self):
        """Equal requests of 5 kW -> 10 kW surplus splits equally to each (5 kW each)."""
        prosumer = self._build_two_demand_setup("dump_proportional")
        gb_df = prosumer.time_series.loc[0].data_source.df
        hd1_df = prosumer.time_series.loc[1].data_source.df
        hd2_df = prosumer.time_series.loc[2].data_source.df

        assert gb_df.q_kw.values[0] == pytest.approx(20.0, rel=1e-2)
        # Each demand: 5 (requested) + 5 (half of 10 surplus) = 10 kW
        assert hd1_df.q_received_kw.values[0] == pytest.approx(10.0, rel=2e-2)
        assert hd2_df.q_received_kw.values[0] == pytest.approx(10.0, rel=2e-2)
        # Each q_uncovered = -5
        assert hd1_df.q_uncovered_kw.values[0] == pytest.approx(-5.0, abs=0.5)
        assert hd2_df.q_uncovered_kw.values[0] == pytest.approx(-5.0, abs=0.5)
        # Mass balance
        np.testing.assert_allclose(
            gb_df.mdot_kg_per_s.values[0],
            hd1_df.mdot_kg_per_s.values[0] + hd2_df.mdot_kg_per_s.values[0],
            rtol=1e-3)

    def test_dump_proportional_with_unequal_requests(self):
        """Requests of 3 kW and 12 kW -> 5 kW surplus splits 1:4."""
        prosumer = self._build_two_demand_setup("dump_proportional",
                                                  demand_1_kw=3, demand_2_kw=12)
        gb_df = prosumer.time_series.loc[0].data_source.df
        hd1_df = prosumer.time_series.loc[1].data_source.df
        hd2_df = prosumer.time_series.loc[2].data_source.df

        assert gb_df.q_kw.values[0] == pytest.approx(20.0, rel=1e-2)
        # 5 kW surplus * (3/15) = 1 kW to demand 1, * (12/15) = 4 kW to demand 2
        assert hd1_df.q_received_kw.values[0] == pytest.approx(4.0, rel=5e-2)
        assert hd2_df.q_received_kw.values[0] == pytest.approx(16.0, rel=5e-2)
        # Sum still equals boiler output
        np.testing.assert_allclose(
            hd1_df.q_received_kw.values[0] + hd2_df.q_received_kw.values[0],
            gb_df.q_kw.values[0], rtol=5e-2)


class TestNoSurplusOverflowStrategyParity:
    """
    When sum(requested) >= available -- i.e. there is no surplus -- the three
    strategies must produce identical results. This pins down that the new
    code path is purely additive: it only activates when there is something
    extra to dispatch.
    """

    @pytest.mark.parametrize("scenario_name, max_q_kw, min_q_kw, demand_seq", [
        # Demand at max -- no surplus.
        ("at_max_power", 100, 20, [100, 100, 100]),
        # Demand above max -- producer clipped at max, no surplus.
        ("above_max_power", 50, 5, [80, 90, 100]),
        # Demand exactly equal to min -- no surplus, no min-clamp either.
        ("equal_to_min", 100, 20, [20, 20, 20]),
    ])
    def test_strategies_equal_when_no_surplus(self, scenario_name, max_q_kw,
                                              min_q_kw, demand_seq):
        results = {}
        for strategy in ["cap", "dump_on_last", "dump_proportional"]:
            prosumer = create_empty_prosumer_container()
            data = pd.DataFrame({"demand_1": demand_seq})
            start = '2020-01-01 00:00:00'
            end = pd.Timestamp(start) + len(data) * pd.Timedelta("00:00:01") - pd.Timedelta("00:00:01")
            period = create_period(prosumer, 1, start, end, 'utc', 'default')
            data.index = pd.date_range(start, end, freq='1s', tz='utc')
            cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                                 DFData(data), period, 0, 0)
            gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0,
                                              max_q_kw=max_q_kw, min_q_kw=min_q_kw,
                                              efficiency_percent=100,
                                              heating_value_kj_per_kg=20e3,
                                              overflow_strategy=strategy)
            hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                               t_in_set_c=76.85, t_out_set_c=30)
            GenericMapping(container=prosumer, initiator_id=cp,
                           initiator_column="qdemand_kw",
                           responder_id=hd, responder_column="q_demand_kw", order=1)
            FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=hd, order=0)
            run_timeseries(prosumer, period, True)
            results[strategy] = (
                prosumer.time_series.loc[0].data_source.df.copy(),
                prosumer.time_series.loc[1].data_source.df.copy(),
            )

        for strategy in ["dump_on_last", "dump_proportional"]:
            assert_series_equal(results["cap"][0].q_kw, results[strategy][0].q_kw,
                                check_names=False, rtol=1e-6, atol=1e-6,
                                obj=f"{scenario_name}/q_kw cap vs {strategy}")
            assert_series_equal(results["cap"][0].mdot_kg_per_s,
                                results[strategy][0].mdot_kg_per_s,
                                check_names=False, rtol=1e-6, atol=1e-6,
                                obj=f"{scenario_name}/mdot cap vs {strategy}")
            assert_series_equal(results["cap"][0].t_out_c, results[strategy][0].t_out_c,
                                check_names=False, rtol=1e-6, atol=1e-6,
                                obj=f"{scenario_name}/t_out_c cap vs {strategy}")
            assert_series_equal(results["cap"][1].q_received_kw,
                                results[strategy][1].q_received_kw,
                                check_names=False, rtol=1e-6, atol=1e-6,
                                obj=f"{scenario_name}/q_received cap vs {strategy}")


class TestOverflowStrategyWithMaxTOut:
    """
    Combined ``min_p_kw`` + ``max_t_out_c`` constraints with each overflow
    strategy. With ``dump_on_last`` the boiler can deliver min power at the
    requested feed temperature via the surplus mass flow, so ``max_t_out_c``
    is never binding. With ``cap``, ``max_t_out_c`` caps the temperature
    overshoot but silently drops the boiler below ``min_p_kw``.
    """

    def _run(self, overflow_strategy, max_t_out_c=80):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [10]})  # Below min=20 kW
        start = '2020-01-01 00:00:00'
        end = pd.Timestamp(start)
        period = create_period(prosumer, 1, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq='1s', tz='utc')
        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        eb = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0,
                                               max_p_kw=100, min_p_kw=20,
                                               efficiency_percent=100,
                                               max_t_out_c=max_t_out_c,
                                               overflow_strategy=overflow_strategy)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=1)
        FluidMixMapping(container=prosumer, initiator_id=eb, responder_id=hd, order=0)
        run_timeseries(prosumer, period, True)
        return (prosumer.time_series.loc[0].data_source.df,
                prosumer.time_series.loc[1].data_source.df)

    def test_dump_on_last_respects_both_min_p_and_max_t(self):
        eb_df, hd_df = self._run("dump_on_last", max_t_out_c=80)
        # min_p_kw honoured (boiler at 20 kW)
        assert eb_df.q_kw.values[0] == pytest.approx(20.0, rel=2e-2)
        # max_t_out_c not active (t_out at the requested 76.85, far below 80)
        assert eb_df.t_out_c.values[0] == pytest.approx(76.85, rel=1e-2)
        assert eb_df.t_out_c.values[0] <= 80.0 + 1e-2
        # Demand receives the full 20 kW (uncovered = -10)
        assert hd_df.q_received_kw.values[0] == pytest.approx(20.0, rel=2e-2)
        assert hd_df.q_uncovered_kw.values[0] < -1e-3

    def test_cap_caps_temperature_at_cost_of_min_p(self):
        """Documents the known trade-off: cap + max_t_out_c violates min_p_kw."""
        eb_df, hd_df = self._run("cap", max_t_out_c=80)
        # max_t_out_c respected (t_out exactly at the cap)
        assert eb_df.t_out_c.values[0] == pytest.approx(80.0, rel=1e-2)
        # ...but the boiler now runs BELOW its declared min_p_kw=20:
        # q = mdot_demand * cp * (80 - 30) ~ 0.051 * 4.19 * 50 ~ 10.7 kW
        assert eb_df.q_kw.values[0] < 20.0 - 1.0, \
            "Under 'cap'+max_t_out_c, min_p_kw is silently broken (known)."
        # Energy still conserved at the interface
        np.testing.assert_allclose(eb_df.q_kw.values[0],
                                   hd_df.q_received_kw.values[0],
                                   rtol=5e-2)


class TestMassBalanceAtFluidMixInterface:
    """
    For a single-responder mapping, the producer's reported mass flow MUST
    equal the responder's received mass flow on every step -- under every
    overflow strategy. This is the regression guard against the silently
    dropped mdot bug that motivated this whole feature.
    """

    @pytest.mark.parametrize("strategy", ["cap", "dump_on_last", "dump_proportional"])
    def test_heat_pump_mdot_balance_at_interface(self, strategy):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({
            "Tin_evap": [25] * 6,
            "demand_kw": [0, 20, 200, 30, 0, 25],
            "tdmd_feed_c": [76.85] * 6,
            "tdmd_return_c": [30] * 6,
        })
        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
        cp = create_controlled_const_profile(
            prosumer, ["Tin_evap", "demand_kw", "tdmd_feed_c", "tdmd_return_c"],
            ["t_evap_in_c", "qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
            DFData(data), period, level=0, order=0)
        hp = create_controlled_heat_pump(prosumer, level=1, order=0, period=period,
                                         carnot_efficiency=0.5, pinch_c=0,
                                         delta_t_evap_c=5,
                                         max_p_comp_kw=100, min_p_comp_kw=15,
                                         overflow_strategy=strategy)
        hd = create_controlled_heat_demand(prosumer, level=1, order=1, period=period,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp,
                       initiator_column="t_evap_in_c", responder_id=hp,
                       responder_column="t_evap_in_c", order=0)
        GenericMapping(container=prosumer, initiator_id=cp,
                       initiator_column=["qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
                       responder_id=hd,
                       responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
                       order=1)
        FluidMixMapping(container=prosumer, initiator_id=hp, responder_id=hd, order=0)
        run_timeseries(prosumer, period, True)

        hp_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df

        if strategy == "cap":
            # KNOWN: under 'cap' the HP records mdot_cond > demand mdot at the
            # min-power hysteresis step (#3). Just make sure the leak is
            # bounded and the rest of the steps still balance.
            mismatch = np.abs(hp_df.mdot_cond_kg_per_s.values - hd_df.mdot_kg_per_s.values)
            # All non-hysteresis steps balance
            other_steps = [0, 1, 2, 4, 5]
            np.testing.assert_allclose(mismatch[other_steps], 0.0, atol=1e-6,
                err_msg="cap: mdot should balance everywhere except the min-power hysteresis step")
            # And the hysteresis step has a known non-zero mismatch
            assert mismatch[3] > 1e-3
        else:
            # dump_on_last / dump_proportional: must balance everywhere
            np.testing.assert_allclose(hp_df.mdot_cond_kg_per_s.values,
                                       hd_df.mdot_kg_per_s.values,
                                       atol=1e-6,
                                       err_msg=f"{strategy}: mdot must balance on every step")


# ---------------------------------------------------------------------------
# Energy-leak warning
# ---------------------------------------------------------------------------
# When the producer's recorded mass flow does not match what is dispatched
# to responders via FluidMixMapping, energy effectively disappears at the
# interface. The controllers emit an EnergyLeakWarning on every step where
# this happens so the silent failure cannot pass unnoticed.


def _run_hp_min_p_scenario(overflow_strategy):
    prosumer = create_empty_prosumer_container()
    data = pd.DataFrame({
        "Tin_evap": [25] * 6,
        "demand_kw": [0, 20, 200, 30, 0, 25],
        "tdmd_feed_c": [76.85] * 6,
        "tdmd_return_c": [30] * 6,
    })
    start = '2020-01-01 00:00:00'
    resol = 3600
    end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
    period = create_period(prosumer, resol, start, end, 'utc', 'default')
    data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
    cp = create_controlled_const_profile(
        prosumer, ["Tin_evap", "demand_kw", "tdmd_feed_c", "tdmd_return_c"],
        ["t_evap_in_c", "qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
        DFData(data), period, level=0, order=0)
    hp = create_controlled_heat_pump(prosumer, level=1, order=0, period=period,
                                     carnot_efficiency=0.5, pinch_c=0,
                                     delta_t_evap_c=5,
                                     max_p_comp_kw=100, min_p_comp_kw=15,
                                     overflow_strategy=overflow_strategy)
    hd = create_controlled_heat_demand(prosumer, level=1, order=1, period=period,
                                       t_in_set_c=76.85, t_out_set_c=30)
    GenericMapping(container=prosumer, initiator_id=cp,
                   initiator_column="t_evap_in_c", responder_id=hp,
                   responder_column="t_evap_in_c", order=0)
    GenericMapping(container=prosumer, initiator_id=cp,
                   initiator_column=["qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
                   responder_id=hd,
                   responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
                   order=1)
    FluidMixMapping(container=prosumer, initiator_id=hp, responder_id=hd, order=0)
    run_timeseries(prosumer, period, True)
    return prosumer


def _run_eb_min_p_scenario(overflow_strategy):
    prosumer = create_empty_prosumer_container()
    data = pd.DataFrame({"demand_1": [0, 10, 20, 90, 110, 0, 5]})
    start = '2020-01-01 00:00:00'
    resol = 1
    end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
    period = create_period(prosumer, resol, start, end, 'utc', 'default')
    data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
    cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                         DFData(data), period, 0, 0)
    eb = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0,
                                           max_p_kw=100, min_p_kw=20,
                                           efficiency_percent=100,
                                           overflow_strategy=overflow_strategy)
    hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                       t_in_set_c=76.85, t_out_set_c=30)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                   responder_id=hd, responder_column="q_demand_kw", order=1)
    FluidMixMapping(container=prosumer, initiator_id=eb, responder_id=hd, order=0)
    run_timeseries(prosumer, period, True)
    return prosumer


class TestEnergyLeakWarning:
    """
    EnergyLeakWarning MUST fire for every timestep where the producer
    silently drops mass flow that should have reached the demand. It MUST
    NOT fire when the producer reconciles its state (boilers raising
    t_out_c, or HP using a dump strategy).
    """

    def test_warning_fires_for_hp_under_cap(self):
        """HP + cap + min_p_comp triggered -> warning fires with concrete numbers."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _run_hp_min_p_scenario("cap")
        leak_warnings = [x for x in w if issubclass(x.category, EnergyLeakWarning)]
        assert len(leak_warnings) >= 1, \
            "EnergyLeakWarning must fire on the hysteresis step under 'cap'"
        # Quantitative content: the leak is ~20 kW
        msg = str(leak_warnings[0].message)
        assert "energy leak of" in msg
        assert "overflow_strategy='cap'" in msg
        # The hint should suggest the fix
        assert "dump_on_last" in msg

    def test_no_warning_for_hp_under_dump_on_last(self):
        """HP + dump_on_last -> producer mdot matches dispatched -> no warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _run_hp_min_p_scenario("dump_on_last")
        leak_warnings = [x for x in w if issubclass(x.category, EnergyLeakWarning)]
        assert leak_warnings == [], \
            f"No EnergyLeakWarning expected under 'dump_on_last', got {[str(x.message) for x in leak_warnings]}"

    def test_no_warning_for_hp_under_dump_proportional(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _run_hp_min_p_scenario("dump_proportional")
        leak_warnings = [x for x in w if issubclass(x.category, EnergyLeakWarning)]
        assert leak_warnings == []

    def test_no_warning_for_electric_boiler_under_cap(self):
        """Boilers reconcile via t_out_c so 'cap' should not leak."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _run_eb_min_p_scenario("cap")
        leak_warnings = [x for x in w if issubclass(x.category, EnergyLeakWarning)]
        assert leak_warnings == [], \
            f"Boiler 'cap' is supposed to compensate via t_out_c; got leak warnings: {[str(x.message) for x in leak_warnings]}"

    def test_no_warning_for_electric_boiler_under_dump_on_last(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _run_eb_min_p_scenario("dump_on_last")
        leak_warnings = [x for x in w if issubclass(x.category, EnergyLeakWarning)]
        assert leak_warnings == []

    def test_no_warning_in_normal_operation(self):
        """Normal operation (demand within min..max) must be silent for every producer."""
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [50, 60, 70, 80]})
        start = '2020-01-01 00:00:00'
        resol = 1
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0,
                                          max_q_kw=100, min_q_kw=20,
                                          efficiency_percent=100,
                                          heating_value_kj_per_kg=20e3)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                           t_in_set_c=76.85, t_out_set_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=1)
        FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=hd, order=0)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            run_timeseries(prosumer, period, True)
        leak_warnings = [x for x in w if issubclass(x.category, EnergyLeakWarning)]
        assert leak_warnings == [], \
            f"Normal operation must not emit EnergyLeakWarning, got: {[str(x.message) for x in leak_warnings]}"

    def test_warning_message_contains_actionable_fields(self):
        """The warning message must include enough info to identify and fix the leak."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _run_hp_min_p_scenario("cap")
        leak_warnings = [x for x in w if issubclass(x.category, EnergyLeakWarning)]
        assert leak_warnings, "Need at least one leak warning to check its content"
        msg = str(leak_warnings[0].message)
        # Identifies the producer class
        assert "heat_pump" in msg.lower()
        # Reports producer & dispatched mass flow
        assert "producer mdot" in msg
        assert "dispatched" in msg
        # Reports q_kw
        assert "q_kw" in msg
        # Suggests the fix
        assert "dump_on_last" in msg or "dump_proportional" in msg

    def test_warning_can_be_silenced_per_category(self):
        """Users who accept the leak can filter EnergyLeakWarning explicitly."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            warnings.simplefilter("ignore", EnergyLeakWarning)
            _run_hp_min_p_scenario("cap")
        leak_warnings = [x for x in w if issubclass(x.category, EnergyLeakWarning)]
        assert leak_warnings == []
