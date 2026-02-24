import pytest
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping

from pandaprosumer import create_period, DFData, create_empty_prosumer_container, \
    create_controlled_const_profile, create_controlled_gas_boiler, create_controlled_heat_demand


class Test1GasBoiler1HeatDemandMapping:
    """
    In this example, a single Gas Boiler is mapped to a Heat Demand, testing the max_q_kw, min_q_kw, max_ramp_up_kw_per_s and max_ramp_down_kw_per_s constraints
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [0, 10, 20, 90, 110, 0, 120, 30, 5, 0]})

        start = '2020-01-01 00:00:00'
        resol = 1
        end = pd.Timestamp(start) + len(data["demand_1"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer,
                               resol,
                               start,
                               end,
                               'utc',
                               'default')

        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["demand_1"]
        cp_result_columns = ["qdemand_kw"]

        max_power_kw = 100
        min_power_kw = 20
        max_ramp_up_kw_per_s = 50
        max_ramp_down_kw_per_s = 60
        lhv = 20e3
        gb_params = {
             'max_q_kw': max_power_kw,
             'min_q_kw': min_power_kw,
             'max_ramp_up_kw_per_s': max_ramp_up_kw_per_s,
             'max_ramp_down_kw_per_s': max_ramp_down_kw_per_s,
             'heating_value_kj_per_kg': lhv
            }

        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              data_source, period, 0, 0)

        gb_controller_index = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0, **gb_params)

        hd_controller_index = create_controlled_heat_demand(prosumer, period=period, level=1, order=1, **hd_params)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand_kw",
                       responder_id=hd_controller_index,
                       responder_column="q_demand_kw",
                       order=1)

        FluidMixMapping(container=prosumer,
                        initiator_id=gb_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        gb_data = {
            'q_kw': [0.0, 20.0, 20.0, 70.0, 100.0, 40.0, 90.0, 30.0, 20.0, 0.0],
            'mdot_kg_per_s': [0., 0.051030, 0.10206, 0.357209, 0.510299, 0.2041195708, 0.459269, 0.153090, 0.025515, 0.],
            't_in_c': [30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0],
            't_out_c': [30., 123.7, 76.85, 76.85, 76.85, 76.85, 76.85, 76.85, 217.4, 30.],
            'mdot_gas_kg_per_s': [0.0000, 0.0010, 0.0010, 0.0035, 0.0050, 0.0020, 0.0045, 0.0015, 0.0010, 0.0000]
        }
        gb_expected = pd.DataFrame(gb_data, index=data.index)

        dmd_data = {
            'q_received_kw': [0., 20.05787, 20., 70., 100., 40., 90., 30., 20.24360, 0.],
            'q_uncovered_kw': [0., -10.05787, 0.0, 20.0, 10., -40., 30., 0.0, -15.243603, 0.],
            'mdot_kg_per_s': [0., 0.051030, 0.10206, 0.357209, 0.510299, 0.20411957, 0.459269, 0.153090, 0.025515, 0.],
            't_in_c': [30., 123.7, 76.85, 76.85, 76.85, 76.85, 76.85, 76.85, 217.4, 30.],
            't_out_c': [30.] * 10
        }
        hd_expected = pd.DataFrame(dmd_data, index=data.index)

        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, gb_expected, atol=0.0001, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, hd_expected, atol=0.0001, check_dtype=False)
        
        gb_mdot_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_kg_per_s
        dmd_mdot_kg_per_s = prosumer.time_series.loc[1].data_source.df.mdot_kg_per_s
        gb_power_kw = prosumer.time_series.loc[0].data_source.df.q_kw
        dmd_power_kw = prosumer.time_series.loc[1].data_source.df.q_received_kw
        gb_out_temp_c = prosumer.time_series.loc[0].data_source.df.t_out_c
        gb_in_temp_c = prosumer.time_series.loc[0].data_source.df.t_in_c
        dmd_in_temp_c = prosumer.time_series.loc[1].data_source.df.t_in_c
        dmd_out_temp_c = prosumer.time_series.loc[1].data_source.df.t_out_c
        
        assert_series_equal(gb_mdot_kg_per_s, dmd_mdot_kg_per_s, check_names=False, rtol=.01)
        # FixMe: need higher tolerance for the power, may be due to the fact that the "cp" value of water depends on the temperature
        assert_series_equal(gb_power_kw, dmd_power_kw, check_names=False, rtol=.05)
        assert_series_equal(gb_out_temp_c, dmd_in_temp_c, check_names=False, rtol=.01)
        assert_series_equal(dmd_out_temp_c, gb_in_temp_c, check_names=False, rtol=.01)