import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from pandaprosumer2.run_time_series import run_timeseries
from pandaprosumer2.mapping import GenericMapping

from ..create_elements_controllers import *


class Test1HeatExchanger1HeatDemandMapping:
    """
    In this example, a single ConstProsumer is mapped to a HX, then to a Heat Demand
    """

    def test_mapping(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"Tin_1": [80, 95, 95, 95],
                             "demand_1": [50, 200, 1000, 0]})

        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data["Tin_1"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer,
                               resol,
                               start,
                               end,
                               'utc',
                               'default')

        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["Tin_1", "demand_1"]
        cp_result_columns = ["t_1_in_c", "qdemand_kw"]

        hx_params = {'t_1_in_nom_c': 72,
                     't_1_out_nom_c': 47,
                     't_2_in_nom_c': 32,
                     't_2_out_nom_c': 63,
                     'mdot_2_nom_kg_per_s': 2}

        cp_controller_index = init_const_profile_controller(prosumer, cp_input_columns, cp_result_columns,
                                                            period, data_source, 0)
        hx_index = init_hx_element(prosumer, **hx_params)
        heat_demand_index = init_hd_element(prosumer)
        hx_controller_index = init_hx_controller(prosumer, period, [hx_index], 1)
        hd_controller_index = init_hd_controller(prosumer, period, [heat_demand_index], 2)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand_kw",
                       responder_id=hd_controller_index,
                       responder_column="q_demand_kw",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_1_in_c",
                       responder_id=hx_controller_index,
                       responder_column="t_feed_in_c",
                       order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=hx_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        run_timeseries(prosumer, period, True)

        hx_data = {
            'mdot_1_kg_per_s': [.245960, .774713, 36.718481, 0.],
            't_1_in_c': [80., 95., 95., 95.],
            't_1_out_c': [31.56451, 33.67385, 90., 95.],
            'mdot_2_kg_per_s': [.255149, 1.020598, 3.941905, 0.],
            't_2_in_c': [30., 30., 30., 30.],
            't_2_out_c': [76.85, 76.85, 76.85, 30.]
        }

        hx_expected = pd.DataFrame(hx_data, index=data.index)

        dmd_data = {
            'q_received_kw': [50., 200., 772.4698, 0.],
            'q_uncovered_kw': [0., 0., 227.53, 0.],
            'mdot_kg_per_s': [.255149, 1.020598, 3.941905, 0.],
            't_in_c': [76.85, 76.85, 76.85, 30.],
            't_out_c': [30., 30., 30., 30.]
        }
        hd_expected = pd.DataFrame(dmd_data, index=data.index)

        assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any()
        assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any()
        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, hx_expected, check_dtype=False)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, hd_expected, check_dtype=False)

        dmd_q_uncovered_kw = prosumer.time_series.loc[1].data_source.df.q_uncovered_kw
        hp_mdot_2_kg_per_s = prosumer.time_series.loc[0].data_source.df.mdot_2_kg_per_s
        hp_t_2_out_c = prosumer.time_series.loc[0].data_source.df.t_2_out_c
        hp_t_2_in_c = prosumer.time_series.loc[0].data_source.df.t_2_in_c
        hx_q2_kw = hp_mdot_2_kg_per_s * 4.19 * (hp_t_2_out_c - hp_t_2_in_c)
        assert_series_equal(hx_q2_kw, data.demand_1 - dmd_q_uncovered_kw, rtol=.01, check_names=False)
        mdot_demand_kg_per_s = dmd_data['mdot_kg_per_s']
        assert hp_mdot_2_kg_per_s.values == pytest.approx(mdot_demand_kg_per_s, .001)
        # assert hp_t_2_out_c == pytest.approx([76.85]*len(hp_t_2_out_c))
        # assert hp_t_2_in_c == pytest.approx([30]*len(hp_t_2_in_c))

        prosumer.controller.loc[hd_controller_index].object.t_m_to_receive = lambda p: (76.85, 30, 1.530896781)
        assert (prosumer.controller.loc[hx_controller_index].object.t_m_to_receive_for_t(prosumer, 69.9) ==
                pytest.approx((69.9, 64.13644444505121, 12.426411451969358), .001))
