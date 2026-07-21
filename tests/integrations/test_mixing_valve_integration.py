"""
Integration test for the mixing valve (3-way valve) between a producer and a demand.

Chain: ConstProfile --(q_demand)--> HeatDemand
       GasBoiler --FluidMix--> MixingValve --FluidMix--> HeatDemand

The boiler produces at the valve's t_in_nom_c (95 C); the demand wishes 80 C
feed / 70 C return. The valve recirculates return fluid so that:

  mdot_boiler / mdot_demand == (80 - 70) / (95 - 70) == 0.4

and energy is conserved across the valve (q_boiler == q_demand_received).
"""
import numpy as np
import pandas as pd
import pytest

from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer import (create_empty_prosumer_container, create_period,
                           create_controlled_const_profile,
                           create_controlled_gas_boiler,
                           create_controlled_mixing_valve,
                           create_controlled_heat_demand)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries

from tests.integrations.test_overflow_strategy_consistency import _assert_interface_consistent


class TestMixingValveGasBoilerHeatDemand:

    def _build(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [50., 200., 0., 100.]})
        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"{resol}s") - pd.Timedelta("1s")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')

        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0,
                                          max_q_kw=500, efficiency_percent=100,
                                          heating_value_kj_per_kg=20e3)
        mv = create_controlled_mixing_valve(prosumer, period=period, level=1, order=1,
                                            t_in_nom_c=95.)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=2,
                                           t_feed_demand_c=80., t_return_demand_c=70.)

        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=0)
        FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=mv, order=0)
        FluidMixMapping(container=prosumer, initiator_id=mv, responder_id=hd, order=0)

        run_timeseries(prosumer, period, True)

        gb_df = prosumer.time_series.loc[0].data_source.df
        mv_df = prosumer.time_series.loc[1].data_source.df
        hd_df = prosumer.time_series.loc[2].data_source.df
        return data, gb_df, mv_df, hd_df

    def test_valve_demand_interface_invariants(self):
        """Valve <-> demand: the four FluidMix interface invariants hold."""
        data, gb_df, mv_df, hd_df = self._build()
        _assert_interface_consistent(mv_df, hd_df,
                                     producer_t_out_col='t_out_c',
                                     producer_t_in_col='t_return_c',
                                     producer_mdot_col='mdot_out_kg_per_s',
                                     producer_q_col='q_delivered_kw')

    def test_boiler_valve_interface_invariants(self):
        """Boiler <-> valve: feed at 95, return at 70, hot-leg mdot, same q."""
        data, gb_df, mv_df, hd_df = self._build()
        running = data["demand_1"].values > 0
        np.testing.assert_allclose(gb_df.t_out_c.values[running], 95., atol=1e-2)
        np.testing.assert_allclose(gb_df.t_out_c.values, mv_df.t_in_c.values, rtol=1e-3)
        np.testing.assert_allclose(gb_df.t_in_c.values[running],
                                   mv_df.t_return_c.values[running], rtol=1e-3)
        np.testing.assert_allclose(gb_df.mdot_kg_per_s.values,
                                   mv_df.mdot_in_kg_per_s.values, rtol=1e-3, atol=1e-6)
        np.testing.assert_allclose(gb_df.q_kw.values, mv_df.q_delivered_kw.values,
                                   rtol=5e-3, atol=1e-3)

    def test_energy_conserved_across_valve(self):
        """q_boiler == q_demand_received: the valve neither creates nor destroys energy."""
        data, gb_df, mv_df, hd_df = self._build()
        np.testing.assert_allclose(gb_df.q_kw.values, hd_df.q_received_kw.values,
                                   rtol=5e-3, atol=1e-3)
        # And the demand is fully covered
        np.testing.assert_allclose(hd_df.q_received_kw.values, data["demand_1"].values,
                                   rtol=5e-3, atol=1e-3)

    def test_recirculation_ratio(self):
        """mdot_boiler / mdot_demand == (80-70)/(95-70) == 0.4 on running steps."""
        data, gb_df, mv_df, hd_df = self._build()
        running = data["demand_1"].values > 0
        ratio = gb_df.mdot_kg_per_s.values[running] / hd_df.mdot_kg_per_s.values[running]
        np.testing.assert_allclose(ratio, 0.4, rtol=1e-3)
        # Mass balance inside the valve
        np.testing.assert_allclose(mv_df.mdot_in_kg_per_s.values + mv_df.mdot_recirc_kg_per_s.values,
                                   mv_df.mdot_out_kg_per_s.values, rtol=1e-6, atol=1e-9)

    def test_no_energy_leak_warning(self):
        """The whole run must not emit EnergyLeakWarning."""
        import warnings
        from pandaprosumer.controller.mapped import EnergyLeakWarning
        with warnings.catch_warnings():
            warnings.simplefilter("error", EnergyLeakWarning)
            self._build()

    def test_no_nan_in_results(self):
        data, gb_df, mv_df, hd_df = self._build()
        assert not np.isnan(mv_df.values).any()
        assert not np.isnan(hd_df.values).any()
