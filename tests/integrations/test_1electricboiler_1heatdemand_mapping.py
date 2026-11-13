import warnings

import pytest
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.controller.mapped import EnergyLeakWarning

from pandaprosumer import (create_period, DFData, create_empty_prosumer_container,
                           create_controlled_const_profile, create_controlled_electric_boiler,
                           create_controlled_heat_demand)

from tests.integrations.test_overflow_strategy_consistency import _assert_interface_consistent


class Test1ElectricBoiler1HeatDemandMapping:
    """
    A single Electric Boiler is mapped to a Heat Demand via a FluidMixMapping.

    Focus: behaviour when the demanded thermal power is BELOW the boiler's
    ``min_p_kw`` constraint. Mirrors the existing gas-boiler integration test
    so the comparison between fuel- and electrically-driven heaters is direct.
    """

    def test_min_power_above_demand(self):
        prosumer = create_empty_prosumer_container()
        # Sequence covers: zero demand, demand below min, demand at min,
        # demand above min (max-power clipping), zero again, demand below min again.
        data = pd.DataFrame({"demand_1": [0, 10, 20, 90, 110, 0, 5]})

        start = '2020-01-01 00:00:00'
        resol = 1
        end = pd.Timestamp(start) + len(data["demand_1"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer, resol, start, end, 'utc', 'default')

        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["demand_1"]
        cp_result_columns = ["qdemand_kw"]

        max_p_kw = 100
        min_p_kw = 20
        eb_params = {
            'max_p_kw': max_p_kw,
            'min_p_kw': min_p_kw,
            'efficiency_percent': 100,
            # This test pins the legacy 'cap' behaviour: when demand < min,
            # the boiler holds its thermal output by raising t_out_c.
            'overflow_strategy': 'cap',
        }

        hd_params = {'t_feed_demand_c': 76.85, 't_return_demand_c': 30}

        cp_controller_index = create_controlled_const_profile(
            prosumer, cp_input_columns, cp_result_columns, data_source, period, 0, 0)

        eb_controller_index = create_controlled_electric_boiler(
            prosumer, period=period, level=1, order=0, **eb_params)

        hd_controller_index = create_controlled_heat_demand(
            prosumer, period=period, level=1, order=1, **hd_params)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand_kw",
                       responder_id=hd_controller_index,
                       responder_column="q_demand_kw",
                       order=1)

        FluidMixMapping(container=prosumer,
                        initiator_id=eb_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        eb_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df

        # --- Per-step behaviour assertions -----------------------------------
        # demand = 0 kW  -> boiler off (q, mdot, p all 0; t_out = t_in)
        # demand = 10 kW (< min)  -> boiler clamped to 20 kW, mdot follows
        #                             demand, t_out_c shoots above t_feed_set.
        # demand = 20 kW (= min)  -> exact match.
        # demand = 90 kW  -> normal operation.
        # demand = 110 kW (> max) -> capped to max_p_kw=100 kW.
        # demand = 0 kW   -> off.
        # demand =  5 kW (< min)  -> same overshoot pattern as 10 kW.

        # boiler is running iff demand > 0
        running = data["demand_1"].values > 0
        assert np.allclose(eb_df.q_kw.values[~running], 0.0, atol=1e-6)
        assert np.allclose(eb_df.p_kw.values[~running], 0.0, atol=1e-6)
        assert np.allclose(eb_df.mdot_kg_per_s.values[~running], 0.0, atol=1e-6)

        # min-power floor enforced whenever the boiler runs
        assert (eb_df.p_kw.values[running] >= min_p_kw - 1e-6).all(), \
            "When running, electrical power must respect min_p_kw."
        # max-power ceiling
        assert (eb_df.p_kw.values <= max_p_kw + 1e-6).all()

        # With efficiency=100%, thermal = electrical
        assert np.allclose(eb_df.q_kw.values, eb_df.p_kw.values, rtol=1e-6, atol=1e-6)

        # Steps where demand < min_p_kw and > 0: boiler overshoots
        below_min_running = (data["demand_1"].values > 0) & (data["demand_1"].values < min_p_kw)
        # delivered > demanded
        assert (eb_df.q_kw.values[below_min_running] > data["demand_1"].values[below_min_running]).all()
        # the EB raises t_out_c above the demand's t_feed_demand_c (76.85) to dump
        # the extra power into the demanded mass flow
        assert (eb_df.t_out_c.values[below_min_running] > hd_params['t_feed_demand_c']).all(), \
            "Below-min-power overshoot must manifest as elevated t_out_c."

        # --- Energy / mass balance at the boiler-demand interface ------------
        # The mass flow leaving the boiler must equal the mass flow seen by the
        # heat demand. Same for t_out_c (boiler) == t_in_c (demand) and the
        # delivered thermal power.
        assert_series_equal(eb_df.mdot_kg_per_s, hd_df.mdot_kg_per_s,
                            check_names=False, rtol=.01)
        assert_series_equal(eb_df.t_out_c, hd_df.t_in_c,
                            check_names=False, rtol=.01)
        assert_series_equal(hd_df.t_out_c, eb_df.t_in_c,
                            check_names=False, rtol=.01)
        # Heat demand receives the boiler's thermal output
        assert_series_equal(eb_df.q_kw, hd_df.q_received_kw,
                            check_names=False, rtol=.05)

        # q_uncovered_kw < 0 means demand received MORE than requested
        # (an "overshoot"); should match the below_min_running mask plus the
        # max-power-clipped step (demand=110 -> uncovered=+10, NOT negative).
        overshoot = hd_df.q_uncovered_kw.values < -1e-6
        # All below_min running steps must be overshoot steps
        assert (overshoot[below_min_running]).all(), \
            "Boiler at min_p_kw on a small demand must overshoot the demand."
        # No overshoot when demand is 0 or above min
        assert not overshoot[~running].any()


class Test1ElectricBoiler1HeatDemandMinOnOffTime:
    """
    An Electric Boiler with min_on_time_s and min_off_time_s mapped to a Heat Demand that switches on and off every hour
    """

    def _build(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [0, 50, 0, 50, 0, 50, 0, 50, 0, 50]})
        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(seconds=resol) - pd.Timedelta(seconds=1)
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        eb = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0,
                                               max_p_kw=100, min_p_kw=20,
                                               min_on_time_s=2 * 3600, min_off_time_s=2 * 3600)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1,
                                           t_feed_demand_c=76.85, t_return_demand_c=30)
        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=1)
        FluidMixMapping(container=prosumer, initiator_id=eb, responder_id=hd, order=0)
        return prosumer, period

    def test_min_on_off_time(self):
        prosumer, period = self._build()
        with warnings.catch_warnings():
            warnings.simplefilter("error", EnergyLeakWarning)
            run_timeseries(prosumer, period, True)

        eb_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df

        # Started at 01:00 (held at min_p_kw at 02:00), stopped at 04:00 (held off at 05:00 despite the demand),
        # restarted at 07:00 (held at min_p_kw at 08:00)
        assert eb_df.q_kw.values == pytest.approx([0, 50, 20, 50, 0, 0, 0, 50, 20, 50], abs=.1)
        assert eb_df.p_kw.values == pytest.approx(eb_df.q_kw.values, abs=.1)
        assert hd_df.q_uncovered_kw.values == pytest.approx([0, 0, -20, 0, 0, 50, 0, 0, -20, 0], abs=.1)
        _assert_interface_consistent(eb_df, hd_df, 't_out_c', 't_in_c', 'mdot_kg_per_s', 'q_kw', rtol_q=.01)

    def test_min_on_off_time_rerun(self):
        """
        The on/off history is reset at the start of each run, so a second run gives the same results
        """
        prosumer, period = self._build()
        run_timeseries(prosumer, period, True)
        first_run_df = prosumer.time_series.loc[0].data_source.df.copy()
        run_timeseries(prosumer, period, True)
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, first_run_df)
