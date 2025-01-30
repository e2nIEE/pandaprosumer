import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping

from ..create_elements_controllers import *


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

        cp_controller_index = init_const_profile_controller(prosumer, cp_input_columns, cp_result_columns,
                                                            period, data_source, 0, 0)
        heat_pump_index = init_hp_element(prosumer, **hp_params)
        shs_index = init_shs_element(prosumer, **shs_params)
        heat_demand_index = init_hd_element(prosumer)
        hp_controller_index = init_hp_controller(prosumer, period, [heat_pump_index], 1, 0)
        shs_controller_index = init_shs_controller(prosumer, period, [shs_index], 1, 1)
        hd_controller_index = init_hd_controller(prosumer, period, [heat_demand_index], 1, 2)

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
            'q_cond_kw': [321.05, 321.05, 321.05, 3.93, 2.25, 321.05, 321.05, 321.05, 321.05, 321.05, 321.05, 321.05,
                          321.05],
            'p_comp_kw': [100., 100., 100., 1.23, 0.70, 100., 100., 100., 100., 100., 100., 100., 100.],
            'q_evap_kw': [221.05, 221.05, 221.05, 2.71, 1.55, 221.05, 221.05, 221.05, 221.05, 221.05, 221.05, 221.05,
                          221.05],
            'cop': [3.21] * 13,
            'mdot_cond_kg_per_s': [1.28, 1.28, 1.69, 2.70, 2.70, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28],
            't_cond_in_c': [20., 20., 34.73, 79.65, 79.80, 20., 20., 20., 20., 20., 20., 20., 20.],
            't_cond_out_c': [80.] * 13,
            'mdot_evap_kg_per_s': [10.57, 10.57, 10.57, 0.13, 0.07, 10.57, 10.57, 10.57, 10.57, 10.57, 10.57, 10.57,
                                   10.57],
            't_evap_in_c': [25.0] * 13,
            't_evap_out_c': [20.] * 13
        }
        hp_expected = pd.DataFrame(hp_data, index=data.index)

        shs_data = {
            'q_received_kw': [321.045455, 321.045455, 321.045455, 3.933506, 2.252247, 321.045455, 321.042094, 321.040878, 321.0458176, 321.0458176, 321.040061, 321.042381, 321.0580],
            'q_delivered_kw': [0., 0., 0., 0., 0., 499.998330, 321.042094, 321.040878, 320.994250, 320.993076, 321.040061, 321.042381, 321.0580205],
            'q_charge_kw': [321.045447, 321.045447, 321.045447, 3.933506, 2.252247, 0., 0., 0., .045818, .046875, 0., 0., 0.],
            'q_discharge_kw': [0., 0., 0., 0., 0., 178.952883, 0., 0., 0., 0., 0., 0., 0.],
            'e_stored_kwh': [156.106609, 162.889825, 217.185212, 346.137580, 346.137572, 0., 0., 0., 0., 0., 0., 0., 0.],
            'mdot_received_kg_per_s': [1.279610, 1.279610, 1.694925, 2.697625, 2.697511, 1.279610, 1.279610, 1.279610,
                                       1.279611, 1.279615, 1.279621, 1.279635, 1.279660],
            't_received_in_c': [80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80.],
            't_received_out_c': [20., 20., 34.730776, 79.652567, 79.801061, 20., 20., 20., 20., 20., 20., 20., 20.],
            'mdot_delivered_kg_per_s': [0., 0., 0., 0., 0., 1.992880, 1.279610, 1.279610,
                                        1.279429, 1.279429, 1.279621, 1.279635, 1.279660],
            't_demand_in_c': [20., 20., 20., 20., 20., 20., 20., 20., 20., 20., 20., 20., 20.],
            't_delivered_out_c': [20., 79.998727, 79.998726, 79.999075, 79.999444, 79.999801, 80.,
                                  80., 80., 80., 80., 80., 80.],
            'mdot_charge_kg_per_s': [1.279610, 1.279610, 1.694925, 2.697625, 2.697511, 0., 0., 0.,
                                     0.000183, 0.000187, 0., 0., 0.],
            't_charge_out_c': [20., 20., 34.730776, 79.652567, 79.801061, 79.805292, 20., 20.000015,
                               20.000100, 20.000391, 20.001114, 20.002567, 20.005110],
            'mdot_discharge_kg_per_s': [0., 0., 0., 0., 0., 0.71327, 0., 0., 0., 0., 0., 0., 0.],
            't_discharge_out_c': [20., 79.998727, 79.998726, 79.999075, 79.999444, 79.999444, 79.756740,
                                  79.634767, 79.479963, 79.318958, 79.153411, 78.981749, 78.809607]
        }
        shs_expected = pd.DataFrame(shs_data, index=data.index)

        dmd_data = {
            'q_received_kw': [0., 0., 0., 0., 0., 500., 321.05, 321.05, 321.00, 321.00, 321.05, 321.05, 321.06],
            'q_uncovered_kw': [0., 0., 0., 0., 0., 0., 178.95, 178.95, 0., 0., 478.95, 478.95, 478.94],
            'mdot_kg_per_s': [0., 0., 0., 0., 0., 1.99, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28],
            't_in_c': [20., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80.],
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
        assert_series_equal(hp_res_df.t_cond_out_c, shs_res_df.t_received_in_c, check_dtype=False, atol=.01, check_names=False)
        assert_series_equal(hp_res_df.t_cond_in_c, shs_res_df.t_received_out_c, check_dtype=False, atol=.01, check_names=False)
        assert_series_equal(hp_res_df.mdot_cond_kg_per_s, shs_res_df.mdot_received_kg_per_s, check_dtype=False, atol=.01, check_names=False)
        assert_series_equal(hp_res_df.q_cond_kw, shs_res_df.q_received_kw, check_dtype=False, atol=.1, check_names=False)
        assert_series_equal(shs_res_df.t_delivered_out_c, hd_res_df.t_in_c, check_dtype=False, atol=.1, check_names=False)
        non_zero_mdot = hd_res_df.mdot_kg_per_s != 0
        assert_series_equal(shs_res_df.t_demand_in_c[non_zero_mdot], hd_res_df.t_out_c[non_zero_mdot], check_dtype=False, atol=.1, check_names=False)
        assert_series_equal(shs_res_df.mdot_delivered_kg_per_s, hd_res_df.mdot_kg_per_s, check_dtype=False, atol=.1, check_names=False)
        assert_series_equal(shs_res_df.q_delivered_kw, hd_res_df.q_received_kw, check_dtype=False, atol=.1, check_names=False)

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

        cp_controller_index = init_const_profile_controller(prosumer, cp_input_columns, cp_result_columns,
                                                            period, data_source, 0)
        heat_pump_index = init_hp_element(prosumer, **hp_params)
        shs_index = init_shs_element(prosumer, **shs_params)
        heat_demand_index = init_hd_element(prosumer)
        hp_controller_index = init_hp_controller(prosumer, period, [heat_pump_index], 1, 0)
        shs_controller_index = init_shs_controller(prosumer, period, [shs_index], 1, 1)
        hd_controller_index = init_hd_controller(prosumer, period, [heat_demand_index], 1, 2)

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
            'q_cond_kw': [321.05, 321.05, 321.05, 3.93, 2.25, 321.05, 321.05, 321.05, 321.05, 321.05, 321.05, 321.05,
                          321.05],
            'p_comp_kw': [100., 100., 100., 1.23, 0.70, 100., 100., 100., 100., 100., 100., 100., 100.],
            'q_evap_kw': [221.05, 221.05, 221.05, 2.71, 1.55, 221.05, 221.05, 221.05, 221.05, 221.05, 221.05, 221.05,
                          221.05],
            'cop': [3.21] * 13,
            'mdot_cond_kg_per_s': [1.28, 1.28, 1.69, 2.70, 2.70, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28],
            't_cond_in_c': [20., 20., 34.73, 79.65, 79.80, 20., 20., 20., 20., 20., 20., 20., 20.],
            't_cond_out_c': [80.] * 13,
            'mdot_evap_kg_per_s': [10.57, 10.57, 10.57, 0.13, 0.07, 10.57, 10.57, 10.57, 10.57, 10.57, 10.57, 10.57,
                                   10.57],
            't_evap_in_c': [25.0] * 13,
            't_evap_out_c': [20.] * 13
        }
        hp_expected = pd.DataFrame(hp_data, index=data.index)

        shs_data = {
            'q_received_kw': [321.045455, 321.045455, 321.045455, 3.933506, 2.252247, 0., 0., 0., 0., 0., 0., 0., 0.],
            'q_delivered_kw': [0., 0., 0., 0., 0., 178.952883, 0., 0., 0., 0., 0., 0., 0.],
            'q_charge_kw': [321.045455, 321.045455, 321.045455, 3.933506, 2.252247, 0., 0., 0., 0., 0., 0., 0., 0.],
            'q_discharge_kw': [0., 0., 0., 0., 0., 178.952883, 0., 0., 0., 0., 0., 0., 0.],
            'e_stored_kwh': [156.106609, 162.889825, 217.185212, 346.137580, 346.137572, 0., 0., 0., 0., 0., 0., 0., 0.],
            'mdot_received_kg_per_s': [1.279610, 1.279610, 1.694925, 2.697625, 2.697511, 0., 0., 0., 0., 0., 0., 0., 0.],
            't_received_in_c': [80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80.],
            't_received_out_c': [20., 20., 34.730776, 79.652567, 79.801061, 80., 80., 80., 80., 80., 80., 80., 80.],
            'mdot_delivered_kg_per_s': [0., 0., 0., 0., 0., 0.71327, 0., 0., 0., 0., 0., 0., 0.],
            't_demand_in_c': [20., 20., 20., 20., 20., 20., 20., 20., 80., 80., 20., 20., 20.],
            't_delivered_out_c': [20., 79.998727, 79.998726, 79.999075, 79.999444, 79.999444, 79.756740, 79.634767, 79.479963, 79.316585, 79.149028, 78.979000, 78.807377],
            'mdot_charge_kg_per_s': [1.279610, 1.279610, 1.694925, 2.697625, 2.697511, 0., 0., 0., 0., 0., 0., 0., 0.],
            't_charge_out_c': [20., 20., 34.730776, 79.652567, 79.801061, 79.805292, 20., 20.000015, 20.000100, 20.000389, 20.001100, 20.002534, 20.005051],
            'mdot_discharge_kg_per_s': [0., 0., 0., 0., 0., 0.71327, 0., 0., 0., 0., 0., 0., 0.],
            't_discharge_out_c': [20., 79.998727, 79.998726, 79.999075, 79.999444, 79.999444, 79.756740, 79.634767, 79.479963, 79.316585, 79.149028, 78.979000, 78.807377]
        }
        shs_expected = pd.DataFrame(shs_data, index=data.index)

        dmd_data = {
            'q_received_kw': [0., 0., 0., 0., 0., 500., 321.05, 321.05, 321., 321.00, 321.05, 321.05, 321.06],
            'q_uncovered_kw': [0., 0., 0., 0., 0., 0., 178.95, 178.95, 0., 0., 478.95, 478.95, 478.94],
            'mdot_kg_per_s': [0., 0., 0., 0., 0., 1.99, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28, 1.28],
            't_in_c': [50., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80., 80.],  # Fixme: why 50 at t0?
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
        assert_frame_equal(hp_res_df.sort_index(axis=1), hp_expected.sort_index(axis=1), check_dtype=False, rtol=.2, atol=.01, check_names=False)
        assert_frame_equal(shs_res_df.sort_index(axis=1), shs_expected.sort_index(axis=1), check_dtype=False, atol=.01, check_names=False)
        assert_frame_equal(hd_res_df.sort_index(axis=1), hd_expected.sort_index(axis=1), check_dtype=False, rtol=.001, atol=.01, check_names=False)
        assert_series_equal(hp_res_df.t_cond_out_c, shs_res_df.t_received_in_c, check_dtype=False, atol=.01, check_names=False)
        t_mix_hp_cond_in = (shs_res_df.t_received_out_c * shs_res_df.mdot_received_kg_per_s + hd_res_df.t_out_c * hd_res_df.mdot_kg_per_s) / (shs_res_df.mdot_received_kg_per_s + hd_res_df.mdot_kg_per_s)
        assert_series_equal(hp_res_df.t_cond_in_c, t_mix_hp_cond_in, check_dtype=False, atol=.01, check_names=False)
        mdot_mix_dmd_kg_per_s = (hp_res_df.mdot_cond_kg_per_s - shs_res_df.mdot_received_kg_per_s)
        # Calculate the denominator condition
        denominator = mdot_mix_dmd_kg_per_s + shs_res_df.mdot_delivered_kg_per_s
        # Avoid division by zero by only calculating `t_mix_hd_in_c` where `denominator` is not zero
        t_mix_hd_in_c = pd.Series(index=hp_res_df.index, dtype='float64')  # Empty series for final values
        non_zero_mdot = denominator != 0
        # Only compute where denominator is non-zero
        t_mix_hd_in_c[non_zero_mdot] = ((hp_res_df.t_cond_out_c * mdot_mix_dmd_kg_per_s + shs_res_df.t_delivered_out_c * shs_res_df.mdot_delivered_kg_per_s) / denominator)[non_zero_mdot]
        assert_series_equal(t_mix_hd_in_c[non_zero_mdot], hd_res_df.t_in_c[non_zero_mdot], check_dtype=False, atol=.01, check_names=False)
        non_zero_mdot = shs_res_df.mdot_delivered_kg_per_s != 0
        assert_series_equal(shs_res_df.t_demand_in_c[non_zero_mdot], hd_res_df.t_out_c[non_zero_mdot], check_dtype=False, atol=.01, check_names=False)
        assert_series_equal(hp_res_df.mdot_cond_kg_per_s + shs_res_df.mdot_delivered_kg_per_s, shs_res_df.mdot_received_kg_per_s + hd_res_df.mdot_kg_per_s, check_dtype=False, atol=.01, check_names=False)
        assert_series_equal(hp_res_df.q_cond_kw + shs_res_df.q_delivered_kw, shs_res_df.q_received_kw + hd_res_df.q_received_kw, check_dtype=False, atol=.01, check_names=False)
