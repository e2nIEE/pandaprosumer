import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer2.run_time_series import run_timeseries
from pandaprosumer2.mapping import GenericMapping, FluidMixMapping

from ..create_elements_controllers import *


class Test1HeatPump1DryCoolerMapping:
    """
    In this example, a single ConstProsumer is mapped to a Heat Pump and then to an Adiabatic Dry Cooler
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"t_ext_c": [25, 25, 25, 40],
                             "mdot_fluid_kg_per_s": [.5, 1, 2, 40],
                             "t_in_c": [76.85, 76.85, 76.85, 76.85],
                             "t_out_c": [30, 30, 30, 30],
                             "phi_air_in_percent": [30, 30, 30, 30]})

        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data["t_ext_c"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["t_ext_c", "mdot_fluid_kg_per_s", "t_in_c", "t_out_c", "t_ext_c", "phi_air_in_percent"]
        cp_result_columns = ["t_evap_in_c", "mdot_fluid_kg_per_s", "t_in_c", "t_out_c", "t_air_in_c", "phi_air_in_percent"]
        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}

        dc_params = {'fans_number': 8,
                     'n_nom_rpm': 300,
                     'p_fan_nom_kw': 15,
                     'qair_nom_m3_per_h': 50000,
                     't_air_in_nom_c': 25,
                     't_air_out_nom_c': 45,
                     't_fluid_in_nom_c': 76,
                     't_fluid_out_nom_c': 30,
                     'adiabatic_mode': True,
                     'min_delta_t_air_c': 5}

        cp_controller_index = init_const_profile_controller(prosumer, cp_input_columns, cp_result_columns,
                                                            period, data_source, level=0, order=0)
        heat_pump_index = create_heat_pump(prosumer, **hp_params)
        hp_controller_index = init_hp_controller(prosumer, period, [heat_pump_index], level=1, order=0)
        dry_cooler_index = create_dry_cooler(prosumer, **dc_params)
        dc_controller_index = init_dc_controller(prosumer, period, [dry_cooler_index], level=1, order=1)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column=["mdot_fluid_kg_per_s", "t_in_c", "t_out_c", "t_air_in_c", "phi_air_in_percent"],
                       responder_id=dc_controller_index,
                       responder_column=["mdot_fluid_kg_per_s", "t_in_c", "t_out_c", "t_air_in_c", "phi_air_in_percent"],
                       order=1)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=dc_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        hp_data_res = {
            'q_cond_kw': [97.981785, 195.963571, 337.512054, 380.597447],
            'p_comp_kw': [29.030603, 58.061207, 100., 80.142948],
            'q_evap_kw': [68.951182, 137.902364, 237.512054, 300.454498],
            'cop': [3.375121, 3.375121, 3.375121, 4.748982],
            'mdot_cond_kg_per_s': [.5, 1., 1.72232, 2.423401],
            't_cond_in_c': [30., 30., 30., 39.318079],
            't_cond_out_c': [76.85, 76.85, 76.85, 76.85],
            'mdot_evap_kg_per_s': [3.296800, 6.593600, 11.356291, 14.376785],
            't_evap_in_c': [25., 25., 25., 40.],
            't_evap_out_c': [20., 20., 20., 35.]
        }

        hp_expected = pd.DataFrame(hp_data_res, index=data.index)

        dc_data_res = {
            'q_exchanged_kw': [97.981785, 195.963571, 337.512054, 380.444892],
            'p_fans_kw': [0.135364602, 1.2995130737, 11.65810625, 12564.77173],
            'n_rpm': [31.229321, 66.37243, 137.9124612, 1413.987946],
            'mdot_air_m3_per_h': [5204.886848, 11062.0718, 22985.4102, 235664.657613],
            'mdot_air_kg_per_s': [1.580274, 3.379091, 7.138724, 75.56],
            't_air_in_c': [14.73297, 14.73297, 14.73297, 26.0035],
            't_air_out_c': [76.304987, 72.322820, 61.683360, 31.0035],
            'mdot_fluid_kg_per_s': [.5, 1., 1.72232, 2.4234],
            't_fluid_in_c': [76.85, 76.85, 76.85, 76.85],
            't_fluid_out_c': [30., 30., 30., 39.318079]
        }
        dc_expected = pd.DataFrame(dc_data_res, index=data.index)

        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, hp_expected, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, dc_expected, check_dtype=False)

        hp_p_kw = prosumer.time_series.loc[0].data_source.df.p_comp_kw
        hp_qcond_kw = prosumer.time_series.loc[0].data_source.df.q_cond_kw
        dc_q_evacuated_kw = prosumer.time_series.loc[1].data_source.df.q_exchanged_kw
        dc_t_fluid_out_c = prosumer.time_series.loc[1].data_source.df.t_fluid_out_c
        dc_t_fluid_in_c = prosumer.time_series.loc[1].data_source.df.t_fluid_in_c
        dc_mdot_fluid_kg_per_s = prosumer.time_series.loc[1].data_source.df.mdot_fluid_kg_per_s
        hp_mdot_cond_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_cond_kg_per_s
        hp_t_cond_out_c = prosumer.time_series.loc[0].data_source.df.t_cond_out_c
        hp_t_cond_in_c = prosumer.time_series.loc[0].data_source.df.t_cond_in_c
        assert (hp_p_kw <= hp_params['max_p_comp_kw']).all()
        assert_series_equal(hp_qcond_kw, dc_q_evacuated_kw, rtol=.01, check_names=False)
        # mdot_demand_kg_per_s = min(data.mdot_fluid_kg_per_s, dc_q_evacuated_kw / ((data.t_in_c - data.t_out_c) * 4.19))
        # assert_series_equal(hp_mdot_cond_kg_per_s, mdot_demand_kg_per_s, rtol=.01, check_names=False)
        assert hp_t_cond_out_c.values == pytest.approx(data.t_in_c, .01)
        assert_series_equal(hp_t_cond_out_c, dc_t_fluid_in_c, rtol=.01, check_names=False)
        assert_series_equal(hp_t_cond_in_c, dc_t_fluid_out_c, rtol=.01, check_names=False)
        assert_series_equal(hp_mdot_cond_kg_per_s, dc_mdot_fluid_kg_per_s, rtol=.01, check_names=False)
