import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping

from ..create_elements_controllers import *


class Test2HeatPumps1HeatDemandMapping:
    """
    In this example, a single ConstProsumer is mapped to 2 Heat Pumps and which are mapped to the same Heat Demand
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"Tin_evap": [25., 25., 25.],
                             "demand_1": [50., 200., 500.]})

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

        cp_input_columns = ["Tin_evap", "demand_1"]
        cp_result_columns = ["t_evap_in_c", "qdemand_kw"]
        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}

        cp_controller_index = init_const_profile_controller(prosumer, cp_input_columns, cp_result_columns,
                                                            period, data_source, 0)
        heat_pump_index_1 = init_hp_element(prosumer, **hp_params)
        hp_controller_index_1 = init_hp_controller(prosumer, period, [heat_pump_index_1], 1)
        heat_pump_index_2 = init_hp_element(prosumer, **hp_params)
        hp_controller_index_2 = init_hp_controller(prosumer, period, [heat_pump_index_2], 2)
        heat_demand_index = init_hd_element(prosumer)
        hd_controller_index = init_hd_controller(prosumer, period, [heat_demand_index], 3)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index_1,
                       responder_column="t_evap_in_c",
                       order=0)
        
        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index_2,
                       responder_column="t_evap_in_c",
                       order=1)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand_kw",
                       responder_id=hd_controller_index,
                       responder_column="q_demand_kw",
                       order=2)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index_1,
                        responder_id=hd_controller_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index_2,
                        responder_id=hd_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        hp_data_1 = {
            'q_cond_kw': [50., 200., 337.512054],
            'p_comp_kw': [14.814286, 59.257143, 100.],
            'q_evap_kw': [35.185714, 140.742857, 237.512054],
            'cop': [3.375121, 3.375121, 3.375121],
            'mdot_cond_kg_per_s': [0.255149, 1.020598, 1.722320],
            't_cond_in_c': [30., 30., 30.],
            't_cond_out_c': [76.85, 76.85, 76.85],
            'mdot_evap_kg_per_s': [1.682353, 6.729414, 11.356291],
            't_evap_in_c': [25., 25., 25.],
            't_evap_out_c': [20., 20., 20.]
        }

        hp_expected_1 = pd.DataFrame(hp_data_1, index=data.index)

        hp_data_2 = {
            'q_cond_kw': [0., 0., 162.487946],
            'p_comp_kw': [0., 0., 48.142857],
            'q_evap_kw': [0., 0., 114.345089],
            'cop': [0., 0., 3.375121],
            'mdot_cond_kg_per_s': [0., 0., 0.829174],
            't_cond_in_c': [76.85, 76.85, 30.],
            't_cond_out_c': [76.85, 76.85, 76.85],
            'mdot_evap_kg_per_s': [0., 0., 5.467243],
            't_evap_in_c': [25., 25., 25.],
            't_evap_out_c': [25., 25., 20.]
        }

        hp_expected_2 = pd.DataFrame(hp_data_2, index=data.index)

        dmd_data = {
            'q_received_kw': [50., 200., 500.],
            'q_uncovered_kw': [0., 0., 0.],
            'mdot_kg_per_s': [0.255149, 1.020598, 2.5514946353],
            't_in_c': [76.85, 76.85, 76.85],
            't_out_c': [30., 30., 30.]
        }
        hd_expected = pd.DataFrame(dmd_data, index=data.index)

        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[2, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, hp_expected_1, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, hp_expected_2, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[2].data_source.df, hd_expected, check_dtype=False)

        hp1_p_kw = prosumer.time_series.loc[0].data_source.df.p_comp_kw
        hp2_p_kw = prosumer.time_series.loc[1].data_source.df.p_comp_kw
        hp1_qcond_kw = prosumer.time_series.loc[0].data_source.df.q_cond_kw
        hp2_qcond_kw = prosumer.time_series.loc[1].data_source.df.q_cond_kw
        dmd_q_uncovered_kw = prosumer.time_series.loc[2].data_source.df.q_uncovered_kw
        hp1_mdot_cond_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_cond_kg_per_s
        hp2_mdot_cond_kg_per_s = prosumer.time_series.loc[1].data_source.df.mdot_cond_kg_per_s
        hp1_t_cond_out_c = prosumer.time_series.loc[0].data_source.df.t_cond_out_c
        hp2_t_out_c = prosumer.time_series.loc[1].data_source.df.t_cond_out_c
        assert (hp1_p_kw <= hp_params['max_p_comp_kw']).all()
        assert (hp2_p_kw <= hp_params['max_p_comp_kw']).all()
        assert_series_equal(hp1_qcond_kw + hp2_qcond_kw, data.demand_1 - dmd_q_uncovered_kw, rtol=.0001, check_names=False)
        mdot_demand_kg_per_s = data.demand_1 / ((76.85 - 30) * 4.19)
        mdot_hp_kg_per_s = hp1_mdot_cond_kg_per_s + hp2_mdot_cond_kg_per_s
        assert_series_equal(mdot_hp_kg_per_s, mdot_demand_kg_per_s, rtol=.01, check_names=False)
        t_mix_c = (hp1_mdot_cond_kg_per_s * hp1_t_cond_out_c + hp2_mdot_cond_kg_per_s * hp2_t_out_c) / mdot_hp_kg_per_s
        assert t_mix_c.values == pytest.approx([76.85]*len(t_mix_c))
