import pytest
import numpy as np
import pandas as pd
from pandas.testing import assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer import (create_period, DFData, create_empty_prosumer_container,
                           create_controlled_const_profile, create_controlled_heat_pump,
                           create_controlled_heat_demand)


class Test1HeatPump1HeatDemandMinPCompMapping:
    """
    Single Heat Pump mapped to a Heat Demand via FluidMixMapping.

    Focus: behaviour when the required compressor electrical power is BELOW
    ``min_p_comp_kw``. ``min_p_comp_kw`` is an *electrical* (compressor)
    constraint that is decoupled from the condenser thermal power
    (``q_cond_kw = p_comp_kw * COP``), so a 15 kW compressor floor can
    correspond to a ~50 kW thermal floor when COP ~= 3.4.

    The controller implements a hysteresis (see heat_pump.py:266-284):

      - HP OFF previously + required p_comp < min  ->  stays OFF
        (nothing delivered, demand fully uncovered).
      - HP ON previously  + required p_comp < min  ->  stays ON at
        ``p_comp = min_p_comp_kw``. NOTE the asymmetry with the gas/electric
        boiler: the HP records an internal ``q_cond = min * COP`` and a
        condenser ``mdot_cond`` larger than the demand's required mdot,
        but at the FluidMix interface the demand still only receives the
        thermal power and mass flow it requested (no overshoot reaches the
        demand). Internal HP ``mdot_cond`` and ``q_cond_kw`` therefore
        diverge from what is dispatched -- see assertions below.
    """

    def test_min_p_comp_above_demand_with_hysteresis(self):
        prosumer = create_empty_prosumer_container()

        # With carnot_efficiency=0.5, pinch=0, t_feed=76.85, t_return=30,
        # t_evap=25 -> COP = 0.5 * (76.85+273)/(76.85-25) = 3.375.
        # min_p_comp_kw=15 -> thermal floor ~ 50.6 kW.
        #
        # step | demand_kw | prev p_comp | target p_comp | expected
        # -----+-----------+-------------+---------------+----------------------
        #   0  |     0     |    NaN      |       0       | off (no-demand)
        #   1  |    20     |     0       |      ~5.9     | stays OFF (was off)
        #   2  |   200     |     0       |     ~59.3     | runs normally
        #   3  |    30     |   ~59.3     |      ~8.9     | stays ON at min
        #   4  |     0     |     15      |       0       | off
        #   5  |    25     |     0       |      ~7.4     | stays OFF
        data = pd.DataFrame({
            "Tin_evap": [25, 25, 25, 25, 25, 25],
            "demand_kw": [0, 20, 200, 30, 0, 25],
            "tdmd_feed_c": [76.85] * 6,
            "tdmd_return_c": [30] * 6,
        })
        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq=f'{resol}s', tz='utc')
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["Tin_evap", "demand_kw", "tdmd_feed_c", "tdmd_return_c"]
        cp_result_columns = ["t_evap_in_c", "qdemand_kw", "tdmd_feed_c", "tdmd_return_c"]

        min_p_comp_kw = 15.0
        max_p_comp_kw = 100.0
        expected_cop = 3.375  # 0.5 * (76.85+273) / (76.85-25)
        hp_params = {
            'carnot_efficiency': 0.5,
            'pinch_c': 0,
            'delta_t_evap_c': 5,
            'max_p_comp_kw': max_p_comp_kw,
            'min_p_comp_kw': min_p_comp_kw,
            # Pinned to legacy 'cap' behaviour, which documents the
            # known energy leak between hp_df.q_cond_kw and
            # hd_df.q_received_kw at the min-p hysteresis step.
            'overflow_strategy': 'cap',
        }
        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        cp_idx = create_controlled_const_profile(
            prosumer, cp_input_columns, cp_result_columns, data_source, period, level=0, order=0)
        hp_idx = create_controlled_heat_pump(prosumer, level=1, order=0, period=period, **hp_params)
        hd_idx = create_controlled_heat_demand(prosumer, level=1, order=1, period=period, **hd_params)

        GenericMapping(container=prosumer,
                       initiator_id=cp_idx, initiator_column="t_evap_in_c",
                       responder_id=hp_idx, responder_column="t_evap_in_c", order=0)
        GenericMapping(container=prosumer,
                       initiator_id=cp_idx,
                       initiator_column=["qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
                       responder_id=hd_idx,
                       responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
                       order=1)
        FluidMixMapping(container=prosumer, initiator_id=hp_idx, responder_id=hd_idx, order=0)

        run_timeseries(prosumer, period, True)

        hp_df = prosumer.time_series.loc[0].data_source.df
        hd_df = prosumer.time_series.loc[1].data_source.df

        p_comp = hp_df.p_comp_kw.values
        q_cond = hp_df.q_cond_kw.values

        # Step 0: zero demand -> HP off
        assert p_comp[0] == pytest.approx(0.0, abs=1e-6)
        assert q_cond[0] == pytest.approx(0.0, abs=1e-6)

        # Step 1: demand=20 kW (target p_comp ~5.9 kW < min=15), HP was off
        #         -> stays off (hysteresis)
        assert p_comp[1] == pytest.approx(0.0, abs=1e-6), \
            "HP was off and target p_comp < min_p_comp_kw -> must stay off"
        assert q_cond[1] == pytest.approx(0.0, abs=1e-6)
        # Demand gets nothing, full 20 kW is uncovered
        assert hd_df.q_received_kw.values[1] == pytest.approx(0.0, abs=1e-6)
        assert hd_df.q_uncovered_kw.values[1] == pytest.approx(20.0, abs=1e-3)
        # No mass flow reaches the demand
        assert hd_df.mdot_kg_per_s.values[1] == pytest.approx(0.0, abs=1e-6)

        # Step 2: demand=200 kW, normal operation
        assert min_p_comp_kw <= p_comp[2] <= max_p_comp_kw + 1e-6
        assert q_cond[2] == pytest.approx(200.0, rel=1e-3)
        assert (q_cond[2] / p_comp[2]) == pytest.approx(expected_cop, rel=1e-2)
        # Demand fully met at the requested feed temperature
        assert hd_df.q_received_kw.values[2] == pytest.approx(200.0, rel=1e-3)
        assert hd_df.t_in_c.values[2] == pytest.approx(76.85, rel=1e-3)

        # Step 3: demand=30 kW (target p_comp ~8.9 kW < min=15), HP was on
        #         -> stays ON at min_p_comp_kw. The condenser internally
        #         records q_cond = min*COP ~= 50.6 kW (above the 30 kW
        #         demand), with a higher mdot_cond than the demand asked.
        #         At the FluidMix interface, however, the demand still only
        #         receives its 30 kW request.
        assert p_comp[3] == pytest.approx(min_p_comp_kw, rel=1e-3), \
            "HP was on and target p_comp < min_p_comp_kw -> must run at min"
        # Internal HP overshoots the demand thermally
        assert q_cond[3] == pytest.approx(min_p_comp_kw * expected_cop, rel=1e-2)
        assert q_cond[3] > 30.0
        # COP unchanged (still ~3.375)
        assert (q_cond[3] / p_comp[3]) == pytest.approx(expected_cop, rel=1e-2)
        # Output temperature stays at the requested feed temp (NOT elevated
        # like the gas/electric boiler does when clipped to min_q).
        assert hp_df.t_cond_out_c.values[3] == pytest.approx(76.85, rel=1e-3)
        # The heat demand sees exactly its 30 kW request -- the overshoot
        # is NOT delivered through the FluidMix mapping.
        assert hd_df.q_received_kw.values[3] == pytest.approx(30.0, rel=1e-3)
        assert hd_df.q_uncovered_kw.values[3] == pytest.approx(0.0, abs=1e-3)
        assert hd_df.t_in_c.values[3] == pytest.approx(76.85, rel=1e-3)
        # And the mass flow delivered to the demand matches the demand,
        # NOT the larger mdot_cond reported on the HP side.
        mdot_demand_expected = 30.0 / (4.19 * (76.85 - 30))
        assert hd_df.mdot_kg_per_s.values[3] == pytest.approx(mdot_demand_expected, rel=2e-2)
        # Document the divergence: HP internal mdot_cond > demand mdot.
        assert hp_df.mdot_cond_kg_per_s.values[3] > hd_df.mdot_kg_per_s.values[3] + 1e-3, \
            ("Known asymmetry: HP records an internal mdot_cond that exceeds "
             "the mdot dispatched to the demand when held at min_p_comp_kw.")

        # Step 4: demand=0 -> off again
        assert p_comp[4] == pytest.approx(0.0, abs=1e-6)
        assert q_cond[4] == pytest.approx(0.0, abs=1e-6)

        # Step 5: demand=25 kW (target p_comp ~7.4 kW < min), HP was off
        #         -> stays off (hysteresis reset by the t=4 off step)
        assert p_comp[5] == pytest.approx(0.0, abs=1e-6), \
            "After an off step, low demand must keep the HP off."
        assert q_cond[5] == pytest.approx(0.0, abs=1e-6)
        assert hd_df.q_uncovered_kw.values[5] == pytest.approx(25.0, abs=1e-3)

        # Global invariants ---------------------------------------------------
        running = p_comp > 1e-6
        assert (p_comp[running] >= min_p_comp_kw - 1e-3).all(), \
            "When running, p_comp must respect min_p_comp_kw."
        assert (p_comp <= max_p_comp_kw + 1e-6).all()
        # Internal energy balance always holds: Q_cond = P_comp + Q_evap
        assert np.allclose(q_cond, hp_df.p_comp_kw.values + hp_df.q_evap_kw.values,
                           atol=1e-6)
        # Demand never sees negative power received or uncovered above its request
        assert (hd_df.q_received_kw.values >= -1e-6).all()
        # Demand t_in_c equals t_cond_out_c whenever there is flow
        flowing = hd_df.mdot_kg_per_s.values > 1e-6
        assert np.allclose(hp_df.t_cond_out_c.values[flowing],
                           hd_df.t_in_c.values[flowing], rtol=1e-2)
