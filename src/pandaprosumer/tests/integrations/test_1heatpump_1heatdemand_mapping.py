import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping

from pandaprosumer import *

class Test1HeatPump1HeatDemandMapping:
    """
    In this example, a single ConstProsumer is mapped to a Heat Pump and then to a Heat Demand
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        # ToDo: add case where demand = 0w in tests
        # ToDo: test equivalence different inputs for demand
        data = pd.DataFrame({"Tin_evap": [25, 25, 25, 25],
                             "demand_1_kw": [50, 200, 337.512+30, 0],
                             "tdmd_feed1_c": [76.85, 76.85, 76.85, 76.85],
                             "tdmd_return1_c": [30, 30, 30, 30]})

        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data["Tin_evap"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["Tin_evap", "demand_1_kw", "tdmd_feed1_c", "tdmd_return1_c"]
        cp_result_columns = ["t_evap_in_c", "qdemand_kw", "tdmd_feed_c", "tdmd_return_c"]
        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}
        hd_params = {'t_in_set_c':76.85, 't_out_set_c':30}


        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                            period, data_source, level=0, order=0)
        hp_controller_index = create_controlled_heat_pump(prosumer, level = 1,order = 0,period=period,**hp_params)
        hd_controller_index = create_controlled_heat_demand(prosumer, level = 1,order = 1,period = period, **hd_params)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
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
            'q_cond_kw': [50., 200., 337.512, 0.],
            'p_comp_kw': [14.814286, 59.257143, 100., 0.],
            'q_evap_kw': [35.185714, 140.742857, 237.512, 0.],
            'cop': [3.375121, 3.375121, 3.375121, 0.],
            'mdot_cond_kg_per_s': [.255149, 1.020598, 1.72232039, 0.],
            't_cond_in_c': [30., 30., 30., 30.],
            't_cond_out_c': [76.85, 76.85, 76.85, 30.],
            'mdot_evap_kg_per_s': [1.682353, 6.729414, 11.35629, 0.],
            't_evap_in_c': [25., 25., 25., 25.],
            't_evap_out_c': [20., 20., 20., 25.]
        }
        hp_expected = pd.DataFrame(hp_data_res, index=data.index)

        dmd_data_res = {
            'q_received_kw': [50., 200., 337.512, 0.],
            'q_uncovered_kw': [0., 0., 30., 0.],
            'mdot_kg_per_s': [0.255149, 1.020598, 1.72232039, 0.],
            't_in_c': [76.85, 76.85, 76.85, 30.],
            't_out_c': [30., 30., 30., 30.]
        }
        hd_expected = pd.DataFrame(dmd_data_res, index=data.index)

        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, hp_expected, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, hd_expected, check_dtype=False)

        hp_p_kw = prosumer.time_series.loc[0].data_source.df.p_comp_kw
        hp_qcond_kw = prosumer.time_series.loc[0].data_source.df.q_cond_kw
        dmd_q_uncovered_kw = prosumer.time_series.loc[1].data_source.df.q_uncovered_kw
        hp_mdot_cond_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_cond_kg_per_s
        hp_t_cond_out_c = prosumer.time_series.loc[0].data_source.df.t_cond_out_c
        hp_t_cond_in_c = prosumer.time_series.loc[0].data_source.df.t_cond_in_c
        assert (hp_p_kw <= hp_params['max_p_comp_kw']).all()
        assert_series_equal(hp_qcond_kw, data.demand_1_kw - dmd_q_uncovered_kw, rtol=.0001, check_names=False)
        mdot_demand_kg_per_s = (data.demand_1_kw - dmd_q_uncovered_kw) / ((76.85 - 30) * 4.19)
        assert_series_equal(hp_mdot_cond_kg_per_s, mdot_demand_kg_per_s, rtol=.01, check_names=False)
        assert hp_t_cond_out_c.values == pytest.approx([76.85, 76.85, 76.85, 30.], .01)
        assert hp_t_cond_in_c.values == pytest.approx([30]*len(hp_t_cond_in_c), .01)
