import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping

from pandaprosumer import *

class Test1HeatPump2HeatDemandsMapping:
    """
    In this example, a single ConstProsumer is mapped to 1 Heat Pumps and which is mapped to 2 different Heat Demands
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        max_hp_qcond = 337.512054
        data = pd.DataFrame({"Tin_evap": [25., 25., 25.],
                             "demand_1": [50., 200., max_hp_qcond+30.],
                             "demand_2": [100., max_hp_qcond-200+40., 70.]})

        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data["Tin_evap"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer,
                               resol,
                               start,
                               end,
                               'utc',
                               'default')

        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["Tin_evap", "demand_1", "demand_2"]
        cp_result_columns = ["t_evap_in_c", "qdemand1_kw", "qdemand2_kw"]
        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}

        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              period, data_source, 0, 0)
        hp_controller_index = create_controlled_heat_pump(prosumer, period=period, level=1, order=0, **hp_params)

        hd_controller_index_1 = create_controlled_heat_demand(prosumer, period=period, level=1, order=1, **hd_params)
        hd_controller_index_2 = create_controlled_heat_demand(prosumer, period=period, level=1, order=2, **hd_params)



        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand1_kw",
                       responder_id=hd_controller_index_1,
                       responder_column="q_demand_kw",
                       order=1)
        
        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand2_kw",
                       responder_id=hd_controller_index_2,
                       responder_column="q_demand_kw",
                       order=2)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index_1,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index_2,
                        order=1)

        run_timeseries(prosumer, period, True)

        hp_data = {
            'q_cond_kw': [150., max_hp_qcond, max_hp_qcond],
            'p_comp_kw': [44.442857, 100., 100.],
            'q_evap_kw': [105.557143, 237.512054, 237.512054],
            'cop': [3.375121, 3.375121, 3.375121],
            'mdot_cond_kg_per_s': [0.765448, 1.72232, 1.72232],
            't_cond_in_c': [30.0, 30.0, 30.0],
            't_cond_out_c': [76.85, 76.85, 76.85],
            'mdot_evap_kg_per_s': [5.047060, 11.356291, 11.356291],
            't_evap_in_c': [25., 25., 25.],
            't_evap_out_c': [20., 20., 20.]
        }

        hp_expected = pd.DataFrame(hp_data, index=data.index)

        dmd_data_1 = {
            'q_received_kw': [50., 200., 337.512],
            'q_uncovered_kw': [0., 0., 30.],
            'mdot_kg_per_s': [0.255149, 1.020598, 1.72232039],
            't_in_c': [76.85, 76.85, 76.85],
            't_out_c': [30., 30., 30.]
        }
        hd_expected_1 = pd.DataFrame(dmd_data_1, index=data.index)

        dmd_data_2 = {
            'q_received_kw': [100., 137.5120, 0.],
            'q_uncovered_kw': [0., 40., 70.],
            'mdot_kg_per_s': [.510298927, .701722536159, 0.],
            't_in_c': [76.85, 76.85, 76.85],
            't_out_c': [30., 30., 30.]
        }
        hd_expected_2 = pd.DataFrame(dmd_data_2, index=data.index)

        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[2, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, hp_expected, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, hd_expected_1, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[2].data_source.df, hd_expected_2, check_dtype=False)

        hp_p_kw = prosumer.time_series.loc[0].data_source.df.p_comp_kw
        hp_qcond_kw = prosumer.time_series.loc[0].data_source.df.q_cond_kw
        dmd1_q_uncovered_kw = prosumer.time_series.loc[1].data_source.df.q_uncovered_kw
        dmd2_q_uncovered_kw = prosumer.time_series.loc[2].data_source.df.q_uncovered_kw
        hp_mdot_cond_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_cond_kg_per_s
        hp_t_cond_out_c = prosumer.time_series.loc[0].data_source.df.t_cond_out_c
        assert (hp_p_kw <= hp_params['max_p_comp_kw']).all()
        assert (hp_qcond_kw == data.demand_1 - dmd1_q_uncovered_kw + data.demand_2 - dmd2_q_uncovered_kw).all()
        mdot_demand1_kg_per_s = (data.demand_1 - dmd1_q_uncovered_kw) / ((76.85 - 30) * 4.19)
        mdot_demand2_kg_per_s = (data.demand_2 - dmd2_q_uncovered_kw) / ((76.85 - 30) * 4.19)
        mdot_demand_kg_per_s = mdot_demand1_kg_per_s + mdot_demand2_kg_per_s
        assert_series_equal(hp_mdot_cond_kg_per_s, mdot_demand_kg_per_s, rtol=.01, check_names=False)

    def test_mapping_temp_level(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"Tin_evap": [25.] * 5,
                             "demand_1": [100.] * 5,
                             "demand_1_t_in_c": [70.] * 5,
                             "demand_1_t_out_c": [20.] * 5,
                             "demand_2": [100.] * 5,
                             "demand_2_t_in_c": [70., 90., 60., 70., 70.],
                             "demand_2_t_out_c": [20., 20., 20., 30., 10.]})

        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data["Tin_evap"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer,
                               resol,
                               start,
                               end,
                               'utc',
                               'default')

        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["Tin_evap", "demand_1", "demand_2", "demand_1_t_in_c", "demand_1_t_out_c", "demand_2_t_in_c", "demand_2_t_out_c"]
        cp_result_columns = ["t_evap_in_c", "qdemand1_kw", "qdemand2_kw", "t_feed_demand1_c", "t_return_demand1_c", "t_feed_demand2_c", "t_return_demand2_c"]
        hp_params = {'carnot_efficiency': .5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}

        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              period, data_source, 0, 0)
        hp_controller_index = create_controlled_heat_pump(prosumer, period=period, level=1, order=0, **hp_params)

        hd_controller_index_1 = create_controlled_heat_demand(prosumer, period=period, level=1, order=1, **hd_params)
        hd_controller_index_2 = create_controlled_heat_demand(prosumer, period=period, level=1, order=2, **hd_params)


        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
                       order=0)

        for order, init_col, resp_col in zip([1, 2, 3], ["qdemand1_kw", "t_feed_demand1_c", "t_return_demand1_c"], ["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"]):
            GenericMapping(container=prosumer,
                        initiator_id=cp_controller_index,
                        initiator_column=init_col,
                        responder_id=hd_controller_index_1,
                        responder_column=resp_col,
                        order=order)
        
        for order, init_col, resp_col in zip([4, 5, 6], ["qdemand2_kw", "t_feed_demand2_c", "t_return_demand2_c"], ["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"]):
            GenericMapping(container=prosumer,
                        initiator_id=cp_controller_index,
                        initiator_column=init_col,
                        responder_id=hd_controller_index_2,
                        responder_column=resp_col,
                        order=order)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index_1,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index_2,
                        order=1)

        run_timeseries(prosumer, period, True)

        hp_data = {
            'q_cond_kw': [200., 200.066390, 200.022729, 200.001915, 200.002066],
            'p_comp_kw': [52.455195, 71.619526, 52.461156, 52.455697, 52.455736],
            'q_evap_kw': [147.544805, 128.446865, 147.561573, 147.546218, 147.546330],
            'cop': [3.812778, 2.793462, 3.812778, 3.812778, 3.812778],
            'mdot_cond_kg_per_s': [0.956805, 0.683206, 0.956914, 1.076267, 0.877162],
            't_cond_in_c': [20., 20., 20., 25.554979, 15.453982],
            't_cond_out_c': [70., 90., 70., 70., 70.],
            'mdot_evap_kg_per_s': [7.054639, 6.141499, 7.055440, 7.054706, 7.054712],
            't_evap_in_c': [25., 25., 25., 25., 25.],
            't_evap_out_c': [20., 20., 20., 20., 20.]
        }

        hp_expected = pd.DataFrame(hp_data, index=data.index)

        dmd_data_1 = {
            'q_received_kw': [100., 100., 100., 100., 100.],
            'q_uncovered_kw': [0., 0., 0., 0., 0.],
            'mdot_kg_per_s': [.47840268996264, .341716207116, .4784026899, .4784026899, .47840268996],
            't_in_c': [70.0, 90.0, 70.0, 70.0, 70.0],
            't_out_c': [20., 20., 20., 20., 20.]
        }
        hd_expected_1 = pd.DataFrame(dmd_data_1, index=data.index)

        dmd_data_2 = {
            'q_received_kw': [100., 100., 100., 100., 100.],
            'q_uncovered_kw': [0., 0., 0., 0., 0.],
            'mdot_kg_per_s': [.478403, .341489, .478511, .597864, .398760],
            't_in_c': [70.0, 90.0, 70.0, 70.0, 70.0],
            't_out_c': [20., 20., 20., 30., 10.]
        }
        hd_expected_2 = pd.DataFrame(dmd_data_2, index=data.index)

        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[2, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, hp_expected, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, hd_expected_1, atol=.1, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[2].data_source.df, hd_expected_2, atol=.1, check_dtype=False)

        hp_p_kw = prosumer.time_series.loc[0].data_source.df.p_comp_kw
        hp_qcond_kw = prosumer.time_series.loc[0].data_source.df.q_cond_kw
        dmd1_q_uncovered_kw = prosumer.time_series.loc[1].data_source.df.q_uncovered_kw
        dmd2_q_uncovered_kw = prosumer.time_series.loc[2].data_source.df.q_uncovered_kw
        hp_mdot_cond_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_cond_kg_per_s
        hp_t_cond_out_c = prosumer.time_series.loc[0].data_source.df.t_cond_out_c
        hp_t_cond_in_c = prosumer.time_series.loc[0].data_source.df.t_cond_in_c
        assert (hp_p_kw <= hp_params['max_p_comp_kw']).all()
        q_dmd_kw = data.demand_1 - dmd1_q_uncovered_kw + data.demand_2 - dmd2_q_uncovered_kw
        assert_series_equal(hp_qcond_kw, q_dmd_kw, rtol=.01, check_names=False)
        t_feed_c = np.maximum(data.demand_1_t_in_c, data.demand_2_t_in_c)
        assert_series_equal(hp_t_cond_out_c, t_feed_c, rtol=.0001, check_names=False, check_dtype=False)
        mdot_demand1_kg_per_s = (data.demand_1 - dmd1_q_uncovered_kw) / ((t_feed_c - data.demand_1_t_out_c) * 4.19)
        mdot_demand2_kg_per_s = (data.demand_2 - dmd2_q_uncovered_kw) / ((t_feed_c - data.demand_2_t_out_c) * 4.19)
        mdot_demand_kg_per_s = mdot_demand1_kg_per_s + mdot_demand2_kg_per_s
        assert_series_equal(hp_mdot_cond_kg_per_s, mdot_demand_kg_per_s, rtol=.01, check_names=False, check_dtype=False)
        t_return_c = (mdot_demand1_kg_per_s * data.demand_1_t_out_c + mdot_demand2_kg_per_s * data.demand_2_t_out_c) / mdot_demand_kg_per_s
        assert_series_equal(hp_t_cond_in_c, t_return_c, rtol=.0001, check_names=False, check_dtype=False)
