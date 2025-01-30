import numpy as np
import pytest
from pandaprosumer2.create import create_empty_prosumer_container, define_senergy_nets_chiller, define_period
from pandaprosumer2.controller.models.chiller import SenergyNetsChillerController
from pandaprosumer2.controller.data_model.chiller import SenergyNetsChillerControllerData
from pandaprosumer2.run_time_series import run_timeseries
from ..create_elements_controllers import *


def _create_chiller_controller(prosumer, **kwargs):
    period = define_period(prosumer, 1,
                           name="sn_chiller",
                           start="2020-01-01 00:00:00",
                           end="2020-01-01 00:00:09",
                           timezone="utc")

    chiller_index = init_chiller_element(prosumer, **kwargs)
    init_chiller_controller(prosumer, period, [chiller_index])
    chiller_controller = prosumer.controller.iloc[0].object
    return chiller_controller



class TestSenergyNetsChillerController:
    """
    Tests the basic functionalities of the SenergyNetsChillerController.
    """

    def test_define_chiller_element(self):
        """
        Test the creation of a Chiller element with default parameter values.
        """
        prosumer = create_empty_prosumer_container()
        define_period(prosumer, 1)
        chiller_index = init_chiller_element(prosumer)


        assert hasattr(prosumer, "sn_chiller")
        assert len(prosumer.sn_chiller) == 1

        expected_columns = [
            "name",
            "in_service",
            "cp_water",
            "t_sh",
            "t_sc",
            "pp_cond",
            "pp_evap",
            "w_cond_pump",
            "w_evap_pump",
            "plf_cc",
            "eng_eff",
            "n_ref"
        ]

        expected_values = [None, True, 4.18, 5.0, 2.0, 5.0, 5.0, 200.0, 200.0, 0.9, 1.0, 'R410A']

        assert sorted(prosumer.sn_chiller.columns) == sorted(expected_columns)
        actual_values = prosumer.sn_chiller.iloc[0].values
        assert all(a == b for a, b in zip(actual_values, expected_values))

    def test_define_chiller_element_with_parameters(self):
        """
        Test the creation of a Chiller element with custom parameter values.
        """
        prosumer = create_empty_prosumer_container()
        define_period(prosumer, 1)

        params = {
            'cp_water': 4.18,
            't_sh': 5.0,
            't_sc': 2.0,
            'pp_cond': 5.0,
            'pp_evap': 5.0,
            'plf_cc': 0.9,
            'w_evap_pump': 200.0,
            'w_cond_pump': 200.0,
            'eng_eff': 1.0,
            'n_ref': 'R410A' # Refrigerant code
        }

        chiller_index = init_chiller_element(prosumer, **params)

        assert hasattr(prosumer, "sn_chiller")
        assert len(prosumer.sn_chiller) == 1
        assert chiller_index == 0

        expected_columns = [
            "name",
            "in_service",
            "cp_water",
            "t_sh",
            "t_sc",
            "pp_cond",
            "pp_evap",
            "plf_cc",
            "w_evap_pump",
            "w_cond_pump",
            "eng_eff",
            "n_ref"
        ]

        expected_values = [None, True, 4.18, 5.0, 2.0, 5.0, 5.0, 200.0, 200.0, 0.9, 1.0, 'R410A']

        assert sorted(prosumer.sn_chiller.columns) == sorted(expected_columns)
        # handling floats issue
        actual_values = prosumer.sn_chiller.iloc[0].values
        for actual, expected in zip(actual_values, expected_values):
            if isinstance(expected, float):
                assert actual == pytest.approx(expected, rel=1e-5)
            else:
                assert actual == expected

    def test_define_controller(self):
        """
        Test the input and result columns of a Chiller controller.
        """
        prosumer = create_empty_prosumer_container()
        period = define_period(prosumer, 1,
                               name="sn_chiller",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 11:59:59",
                               timezone="utc")

        chiller_index = init_chiller_element(prosumer)
        init_chiller_controller(prosumer, period, [chiller_index])

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_chiller(self):
        """
        Test to check the input and result columns of a Chiller controller.
        """
        prosumer = create_empty_prosumer_container()
        period = define_period(prosumer, 1,
                               name="sn_chiller",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 11:59:59",
                               timezone="utc")

        chiller_index = init_chiller_element(prosumer)
        init_chiller_controller(prosumer,
                                period,
                                [chiller_index],
                                input_columns=['t_set_pt_c', 'q_load_kw'],
                                result_columns=['q_evap_kw', 'unmet_load_kw', 'w_in_tot_kw', 'eer', 'plr',
                                                't_out_ev_in_c', 't_out_cond_in_c'])

        chiller_controller = prosumer.controller.iloc[0].object

        input_columns_expected = ['t_set_pt_c', 'q_load_kw']
        result_columns_expected = [
            'q_evap_kw', 'unmet_load_kw', 'w_in_tot_kw', 'eer', 'plr',
            't_out_ev_in_c', 't_out_cond_in_c'
        ]

        assert chiller_controller.input_columns == input_columns_expected
        assert chiller_controller.result_columns == result_columns_expected


