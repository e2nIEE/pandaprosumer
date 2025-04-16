import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping

from pandaprosumer import *


class Test1HeatPump1StratifiedHeatStorage1HeatDemandMapping:
    """
    In this example, a single ConstProsumer is mapped to a Heat Pump, which is mapped to a SHS and then to a Heat Demand
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"Tin_evap": [25] * 13,
                             "demand_1": [0] * 5 + [500] * 3 + [321] * 2 + [800] * 3,
                             "t_feed_demand_c": [80] * 13,
                             "t_return_demand_c": [20] * 13})

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

        cp_input_columns = ["Tin_evap", "demand_1", "t_feed_demand_c", "t_return_demand_c"]
        cp_result_columns = ["t_evap_in_c", "qdemand_kw", "t_feed_demand_c", "t_return_demand_c"]
        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}

        shs_params = {"tank_height_m": 10.,

                      "tank_internal_radius_m": .564,
                      "tank_external_radius_m": .664,
                      "insulation_thickness_m": .1,
                      "n_layers": 100,
                      "min_useful_temp_c": 80,
                      # "k_fluid_w_per_mk": 0,
                      # "k_insu_w_per_mk": 0,
                      # "k_wall_w_per_mk": 0,
                      # "h_ext_w_per_m2k": 0,
                      "t_ext_c": 20}

        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              period, data_source, 0, 0)
        hp_controller_index = create_controlled_heat_pump(prosumer, period=period, level=1, order=0, **hp_params)
        shs_controller_index = create_controlled_stratified_heat_storage(prosumer, period=period, level=1, order=1,
                                                                         **shs_params)
        hd_controller_index = create_controlled_heat_demand(prosumer, period=period, level=1, order=2, **hd_params)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
                       order=0)

        for init_col, resp_col in zip(["qdemand_kw", "t_feed_demand_c", "t_return_demand_c"],
                                      ["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"]):
            GenericMapping(container=prosumer,
                           initiator_id=cp_controller_index,
                           initiator_column=init_col,
                           responder_id=hd_controller_index,
                           responder_column=resp_col,
                           order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=shs_controller_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=shs_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        hp_data = {
            'q_cond_kw': [321.05, 321.05, 321.05, 4.64, 2.22, 321.05, 321.05, 321.05, 321.05, 321.05, 321.05, 321.05,
                          321.05],
            'p_comp_kw': [100., 100., 100., 1.44, 0.70, 100., 100., 100., 100., 100., 100., 100., 100.],
            'q_evap_kw': [221.05, 221.05, 221.05, 3.20, 1.53, 221.05, 221.05, 221.05, 221.05, 221.05, 221.05, 221.05,
                          221.05],
            'cop': [3.21] * 13,
            'mdot_cond_kg_per_s': [1.28, 1.28, 1.28, 2.70, 2.70, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28],
            't_cond_in_c': [20., 20., 20.,79.58, 79.80, 20., 20., 20., 20., 20., 20., 20., 20.],
            't_cond_out_c': [80.] * 13,
            'mdot_evap_kg_per_s': [10.57, 10.57, 10.57, 0.15, 0.07, 10.57, 10.57, 10.57, 10.57, 10.57, 10.57, 10.57,
                                   10.57],
            't_evap_in_c': [25.0] * 13,
            't_evap_out_c': [20.] * 13
        }
        hp_expected = pd.DataFrame(hp_data, index=data.index)

        shs_data = {
            'mdot_discharge_kg_per_s': [0.0, 0.0, 0.0, 0.0, 0.0, 0.71, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            't_discharge_c': [20.0] + [80]*5 + [79.75,79.63,79.48,79.31,79.15,78.98,78.81],
            'q_delivered_kw': [0., 0., 0., 0., 0., 178.95]+ [0.] * 7,
            'e_stored_kwh': [169.68, 169.68, 169.68, 352.92, 352.92]+[0.] * 8,

        }
        shs_expected = pd.DataFrame(shs_data, index=data.index)

        dmd_data = {
             'q_received_kw': [0., 0., 0., 0., 0., 500., 321.05, 321.05, 321., 321., 321.05, 321.05, 321.05],
            'q_uncovered_kw': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 178.95, 178.95, 0.0, 0.0, 478.95, 478.95, 478.95],
            'mdot_kg_per_s': 5 * [0.] + [1.99]+ 7 * [1.28],
            't_in_c': [20.0] + [80.] * 12,
            't_out_c': [20.] * 13
        }
        hd_expected = pd.DataFrame(dmd_data, index=data.index)

        hp_res_df = prosumer.time_series.loc[0].data_source.df
        shs_res_df = prosumer.time_series.loc[1].data_source.df
        hd_res_df = prosumer.time_series.loc[2].data_source.df

        assert not np.isnan(hp_res_df).any().any()
        assert not np.isnan(shs_res_df).any().any()
        assert not np.isnan(hd_res_df).any().any()
        print(hp_res_df)
        print(shs_res_df)
        print(hd_res_df)
        assert_frame_equal(hp_res_df.sort_index(axis=1), hp_expected.sort_index(axis=1), check_dtype=False, atol=.01)
        assert_frame_equal(shs_res_df.sort_index(axis=1), shs_expected.sort_index(axis=1), check_dtype=False, atol=.01)
        assert_frame_equal(hd_res_df.sort_index(axis=1), hd_expected.sort_index(axis=1), check_dtype=False, atol=.01)


    def test_mapping_bypass(self):
        """
        Same test with Heat Pump, Stratified heat Storage and Heat Demand, but with the Heat Pump bypassing the SHS
        (low order direct mapping from the HeatPump directly to the heat Demand
        Should be equivalent to the previous test
        """
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"Tin_evap": [25] * 13,
                             "demand_1": [0] * 5 + [500] * 3 + [321] * 2 + [800] * 3,
                             "t_feed_demand_c": [80] * 13,
                             "t_return_demand_c": [20] * 13})

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

        cp_input_columns = ["Tin_evap", "demand_1", "t_feed_demand_c", "t_return_demand_c"]
        cp_result_columns = ["t_evap_in_c", "qdemand_kw", "t_feed_demand_c", "t_return_demand_c"]
        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}

        shs_params = {"tank_height_m": 10.,
                      "tank_internal_radius_m": .564,
                      "tank_external_radius_m": .664,
                      "insulation_thickness_m": .1,
                      "n_layers": 100,
                      "min_useful_temp_c": 80,
                      # "k_fluid_w_per_mk": 0,
                      # "k_insu_w_per_mk": 0,
                      # "k_wall_w_per_mk": 0,
                      # "h_ext_w_per_m2k": 0,
                      "t_ext_c": 20}

        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              period, data_source, 0, 0)
        hp_controller_index = create_controlled_heat_pump(prosumer, period=period, level=1, order=0, **hp_params)
        shs_controller_index = create_controlled_stratified_heat_storage(prosumer, period=period, level=1, order=1,
                                                                         **shs_params)
        hd_controller_index = create_controlled_heat_demand(prosumer, period=period, level=1, order=2, **hd_params)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
                       order=0)

        for init_col, resp_col in zip(["qdemand_kw", "t_feed_demand_c", "t_return_demand_c"],
                                      ["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"]):
            GenericMapping(container=prosumer,
                           initiator_id=cp_controller_index,
                           initiator_column=init_col,
                           responder_id=hd_controller_index,
                           responder_column=resp_col,
                           order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=shs_controller_index,
                        order=1)

        FluidMixMapping(container=prosumer,
                        initiator_id=shs_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        hp_data = {
            'q_cond_kw': [321.05, 321.05, 321.05, 4.64, 2.22, 321.05, 321.05, 321.05, 321.05, 321.05, 321.05, 321.05,
                          321.05],
            'p_comp_kw': [100., 100., 100., 1.44, 0.70, 100., 100., 100., 100., 100., 100., 100., 100.],
            'q_evap_kw': [221.05, 221.05, 221.05, 3.20, 1.53, 221.05, 221.05, 221.05, 221.05, 221.05, 221.05, 221.05,
                          221.05],
            'cop': [3.21] * 13,
            'mdot_cond_kg_per_s': [1.28, 1.28, 1.28, 2.70, 2.70, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28],
            't_cond_in_c': [20., 20., 20., 79.58, 79.80, 20., 20., 20., 20., 20., 20., 20., 20.],
            't_cond_out_c': [80.] * 13,
            'mdot_evap_kg_per_s': [10.57, 10.57, 10.57, 0.15, 0.07, 10.57, 10.57, 10.57, 10.57, 10.57, 10.57, 10.57,
                                   10.57],
            't_evap_in_c': [25.0] * 13,
            't_evap_out_c': [20.] * 13
        }
        hp_expected = pd.DataFrame(hp_data, index=data.index)

        shs_data = {
            'mdot_discharge_kg_per_s': [0.0, 0.0, 0.0, 0.0, 0.0, 0.71, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            't_discharge_c': [20.0] + [80] * 5 + [79.75, 79.63, 79.48, 79.31, 79.15, 78.98, 78.81],
            'q_delivered_kw': [0., 0., 0., 0., 0., 178.95] + [0.] * 7,
            'e_stored_kwh': [169.68, 169.68, 169.68, 352.92, 352.92] + [0.] * 8,

        }
        shs_expected = pd.DataFrame(shs_data, index=data.index)

        dmd_data = {
            'q_received_kw': [0., 0., 0., 0., 0., 500., 321.05, 321.05, 321., 321., 321.05, 321.05, 321.05],
            'q_uncovered_kw': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 178.95, 178.95, 0.0, 0.0, 478.95, 478.95, 478.95],
            'mdot_kg_per_s': 5 * [0.] + [1.99] + 7 * [1.28],
            't_in_c': [50.0] + [80.] * 12,
            't_out_c': [20.] * 13
        }
        hd_expected = pd.DataFrame(dmd_data, index=data.index)

        hp_res_df = prosumer.time_series.loc[0].data_source.df
        shs_res_df = prosumer.time_series.loc[1].data_source.df
        hd_res_df = prosumer.time_series.loc[2].data_source.df

        assert not np.isnan(hp_res_df).any().any()
        assert not np.isnan(shs_res_df).any().any()
        assert not np.isnan(hd_res_df).any().any()
        print(hp_res_df)
        print(shs_res_df)
        print(hd_res_df)
        assert_frame_equal(hp_res_df.sort_index(axis=1), hp_expected.sort_index(axis=1), check_dtype=False, rtol=.2,atol=.01, check_names=False)
        assert_frame_equal(shs_res_df.sort_index(axis=1), shs_expected.sort_index(axis=1), check_dtype=False, atol=.01,check_names=False)
        assert_frame_equal(hd_res_df.sort_index(axis=1), hd_expected.sort_index(axis=1), check_dtype=False, rtol=.001,atol=.01, check_names=False)
