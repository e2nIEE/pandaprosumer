import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping

from pandaprosumer import *



class Test1HeatPump1ElectricBoiler1HeatDemandMapping:
    """
    In this example, a single ConstProsumer is mapped to a Heat Pump with an Electric Boiler and then to a Heat Demand
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"Tin_evap": [25, 25, 25, 25],
                             "demand_1": [50, 200, 500, 0]})

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

        elb_params = {'max_p_kw': 500}

        hd_params = {'t_in_set_c':76.85, 't_out_set_c':30}


        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                            data_source, period, 0, 0)

        hp_controller_index = create_controlled_heat_pump(prosumer,period=period,level=1,order = 0,**hp_params)

        elb_controller_index = create_controlled_electric_boiler(prosumer,period=period,level = 1,order = 1,**elb_params)

        hd_controller_index = create_controlled_heat_demand(prosumer,period=period,level=1, order=2,**hd_params)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand_kw",
                       responder_id=hd_controller_index,
                       responder_column="q_demand_kw",
                       order=1)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=elb_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        hp_data = {
            'q_cond_kw': [50., 200., 337.512054, 0.],
            'p_comp_kw': [14.814286, 59.257143, 100., 0.],
            'q_evap_kw': [35.185714, 140.742857, 237.512054, 0.],
            'cop': [3.375121, 3.375121, 3.375121, 0.],
            'mdot_cond_kg_per_s': [0.255149, 1.020598, 1.722320, 0.],
            't_cond_in_c': [30., 30., 30., 30.],
            't_cond_out_c': [76.85, 76.85, 76.85, 30.],
            'mdot_evap_kg_per_s': [1.682353, 6.729414, 11.356291, 0.],
            't_evap_in_c': [25., 25., 25., 25.],
            't_evap_out_c': [20., 20., 20., 25.]
        }

        hp_expected = pd.DataFrame(hp_data, index=data.index)

        elb_data = {
            'q_kw': [0., 0., 162.487946, 0.],
            'mdot_kg_per_s': [0., 0., 0.829174, 0.],
            't_in_c': [76.85, 76.85, 30., 30.],
            't_out_c': [76.85, 76.85, 76.85, 30.],
            'p_kw': [0., 0., 162.487946, 0.]
        }
        elb_expected = pd.DataFrame(elb_data, index=data.index)

        dmd_data = {
            'q_received_kw': [50., 200., 500., 0.],
            'q_uncovered_kw': [0., 0., 0., 0.],
            'mdot_kg_per_s': [.25514946353349255, 1.0205978541339702, 2.5514946353349255, 0.],
            't_in_c': [76.85, 76.85, 76.85, 30.],
            't_out_c': [30., 30., 30., 30.]
        }
        hd_expected = pd.DataFrame(dmd_data, index=data.index)

        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[2, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, hp_expected, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, elb_expected, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[2].data_source.df, hd_expected, check_dtype=False)

        hp_p_kw = prosumer.time_series.loc[0].data_source.df.p_comp_kw
        hp_qcond_kw = prosumer.time_series.loc[0].data_source.df.q_cond_kw
        elb_p_kw = prosumer.time_series.loc[1].data_source.df.p_kw
        dmd_q_uncovered_kw = prosumer.time_series.loc[2].data_source.df.q_uncovered_kw
        hp_mdot_cond_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_cond_kg_per_s
        elb_mdot_kg_per_s = prosumer.time_series.loc[1].data_source.df.mdot_kg_per_s
        hp_t_cond_out_c = prosumer.time_series.loc[0].data_source.df.t_cond_out_c
        elb_t_out_c = prosumer.time_series.loc[1].data_source.df.t_out_c
        assert (hp_p_kw <= hp_params['max_p_comp_kw']).all()
        assert (elb_p_kw <= elb_params['max_p_kw']).all()
        assert_series_equal(hp_qcond_kw + elb_p_kw, data.demand_1 + dmd_q_uncovered_kw, rtol=.0001, check_names=False)
        mdot_prod_kg_per_s = hp_mdot_cond_kg_per_s + elb_mdot_kg_per_s
        mdot_dmd_kg_per_s = data.demand_1 / ((76.85 - 30) * 4.19)
        assert_series_equal(mdot_prod_kg_per_s, mdot_dmd_kg_per_s, rtol=.01, check_names=False)
        t_mix_c = (hp_mdot_cond_kg_per_s * hp_t_cond_out_c + elb_mdot_kg_per_s * elb_t_out_c) / mdot_prod_kg_per_s
        assert t_mix_c.values == pytest.approx([76.85, 76.85, 76.85, np.nan], .01, nan_ok=True)
