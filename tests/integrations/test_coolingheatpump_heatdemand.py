import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping

from pandaprosumer import *

class Test1CoolingHeatPump1HeatDemandMapping:
    """
    In this example, a single ConstProsumer is mapped to a Heat Pump and then to a Heat Demand
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        # ToDo: add case where demand = 0w in tests
        # ToDo: test equivalence different inputs for demand
        data = pd.DataFrame({"Tin_cond": [55, 55, 55, 55],
                             "demand_1_kw": [50, 200, 337.512+30, 0],
                             "tdmd_return1_c": [35, 35, 35, 35],
                             "tdmd_feed1_c": [20, 20, 20, 20]})

        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data["Tin_cond"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["Tin_cond", "demand_1_kw", "tdmd_feed1_c", "tdmd_return1_c"]
        cp_result_columns = ["t_load_in_c", "qdemand_kw", "tdmd_feed_c", "tdmd_return_c"]
        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}
        # hd_params = {'t_in_set_c':76.85, 't_out_set_c':30}


        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                            data_source, period, level=0, order=0)
        hp_controller_index = create_controlled_heat_pump(prosumer, level = 1,order = 0,period=period,heating = False,**hp_params)
        hd_controller_index = create_controlled_heat_demand(prosumer, level = 1,order = 1,period = period, heating = False)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_load_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_load_in_c",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column=["qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
                       responder_id=hd_controller_index,
                       responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
                       order=1)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        hp_data_res = {
            'q_cond_kw': [65.68, 262.7, 418.78, 0.0],
            'p_comp_kw': [15.68, 62.7, 100., 0.0],
            'q_evap_kw': [50., 200., 318.78, 0.0],
            'cop': [4.18, 4.18, 4.18, 4.18],
            'mdot_cond_kg_per_s': [3.13, 12.55, 20.02, 0.0],
            't_cond_in_c': [55., 55., 55., 55.],
            't_cond_out_c': [60., 60., 60., 60.],
            'mdot_evap_kg_per_s': [0.79729, 3.19, 5.08, 0.],
            't_evap_in_c': [35., 35., 35., 20.],
            't_evap_out_c': [20., 20., 20., 20.]
        }
        hp_expected = pd.DataFrame(hp_data_res, index=data.index)

        dmd_data_res = {
            'q_received_kw': [50., 200., 318.78, 0.0],
            'q_uncovered_kw': [0., 0., 48.73, 0.],
            'mdot_kg_per_s': [0.80, 3.19, 5.08, 0.],
            't_in_c': [20., 20., 20., 20.],
            't_out_c': [35., 35., 35., 35.]
        }
        hd_expected = pd.DataFrame(dmd_data_res, index=data.index)
        print(prosumer.time_series.loc[0].data_source.df)
        print(prosumer.time_series.loc[1].data_source.df)
        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, hp_expected, check_dtype=False,check_exact=False, rtol=1e-1, atol=1e-1)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, hd_expected, check_dtype=False, check_exact=False, rtol = 1e-1, atol=1e-1)

        hp_p_kw = prosumer.time_series.loc[0].data_source.df.p_comp_kw
        hp_qevap_kw = prosumer.time_series.loc[0].data_source.df.q_evap_kw
        dmd_q_uncovered_kw = prosumer.time_series.loc[1].data_source.df.q_uncovered_kw
        hp_mdot_evap_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_evap_kg_per_s
        hp_t_evap_out_c = prosumer.time_series.loc[0].data_source.df.t_evap_out_c
        hp_t_evap_in_c = prosumer.time_series.loc[0].data_source.df.t_evap_in_c
        assert (hp_p_kw <= hp_params['max_p_comp_kw']).all()
        assert_series_equal(hp_qevap_kw, data.demand_1_kw - dmd_q_uncovered_kw, rtol=.0001, check_names=False)
        mdot_demand_kg_per_s = (data.demand_1_kw - dmd_q_uncovered_kw) / ((35. - 20) * 4.19)
        assert_series_equal(hp_mdot_evap_kg_per_s, mdot_demand_kg_per_s, rtol=.01, check_names=False)
        assert hp_t_evap_out_c.values == pytest.approx([20., 20., 20., 20.], .01)
        assert hp_t_evap_in_c.values == pytest.approx([35., 35., 35., 20.], .01)
