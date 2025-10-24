import pytest
from pandaprosumer import *
import numpy as np


def _default_argument():
    return {
        'name': None,
        'cp_water': 4.186,
        't_sh': 5.0,
        't_sc': 2.0,
        'pp_cond': 5.0,
        'pp_evap': 5.0,
        'w_cond_pump': 200.0,
        'w_evap_pump': 200.0,
        'plf_cc': 0.9,
        'eng_eff': 1.0,
        'n_ref': 'R410A',
        'in_service': True
    }

def _default_period(prosumer):
    return create_period(prosumer, 3600,
                               name="foo",
                               start='2020-01-01 00:00:00',
                               end = '2020-01-01 01:59:59',
                               timezone="utc")

class TestChiller:
    """
    Tests the functionalities of a Chiller element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a Chiller element with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_chiller(prosumer, **_default_argument())
        assert hasattr(prosumer, "sn_chiller")
        assert len(prosumer.sn_chiller) == 1

        # Adjusted expected columns based on the output structure
        expected_columns = ["name", "in_service", "cp_water", "t_sh", "t_sc",
                            "pp_cond", "pp_evap", "w_cond_pump", "w_evap_pump",
                            "plf_cc", "eng_eff", "n_ref"]

        expected_values = [None, True, 4.186, 5.0, 2.0, 5.0, 5.0, 200.0,
                           200.0, 0.9, 1.0, 'R410A']

        assert sorted(prosumer.sn_chiller.columns) == sorted(expected_columns)
        assert list(prosumer.sn_chiller.iloc[0]) == expected_values

    def test_define_element_with_parameters(self):
        """
        Test the creation of a Chiller element with specific custom parameters values.
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        # Custom parameters for the chiller
        params = {
            'cp_water': 4.186,
            't_sh': 2.0,
            't_sc': 5.0,
            'pp_cond': 6.0,
            'pp_evap': 6.0,
            'w_cond_pump': 220,
            'w_evap_pump': 220,
            'plf_cc': 0.9,
            'eng_eff': 0.85,
        }

        chiller_idx = create_chiller(prosumer, name='foo', in_service=False,
                                     n_ref="R410A", index=4, **params)

        # Check if the chiller is added under the expected attribute
        assert hasattr(prosumer, "sn_chiller"), "Chiller was not added to prosumer."

        # Check the length and index
        assert len(prosumer.sn_chiller) == 1
        assert prosumer.sn_chiller.index[0] == chiller_idx

        expected_columns = [
            "name", "in_service", "cp_water", "t_sh", "t_sc",
            "pp_cond", "pp_evap", "w_cond_pump", "w_evap_pump",
            "plf_cc", "eng_eff", "n_ref"
        ]

        expected_values = ['foo', False, 4.186, 2.0, 5.0, 6.0, 6.0, 220, 220, 0.9, 0.85, "R410A"]

        # Check if the columns match expected columns
        assert sorted(prosumer.sn_chiller.columns) == sorted(expected_columns)

        # Use pytest.approx for floating point comparisons
        actual_values = prosumer.sn_chiller.iloc[0].values
        assert actual_values[0] == expected_values[0]
        assert actual_values[1] == expected_values[1]
        assert actual_values[2] == pytest.approx(expected_values[2])
        assert actual_values[3] == pytest.approx(expected_values[3])
        assert actual_values[4] == pytest.approx(expected_values[4])
        assert actual_values[5] == pytest.approx(expected_values[5])
        assert actual_values[6] == pytest.approx(expected_values[6])
        assert actual_values[7] == pytest.approx(expected_values[7])
        assert actual_values[8] == pytest.approx(expected_values[8])
        assert actual_values[9] == pytest.approx(expected_values[9])
        assert actual_values[10] == pytest.approx(expected_values[10])
        assert actual_values[11] == expected_values[11]

    def test_define_chiller_controller(self):
        """
        Test the creation of a Chiller controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_chiller(
            prosumer, order=0, period=_default_period(prosumer), name='foo', in_service=True)

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of the Chiller controller.
        """
        prosumer = create_empty_prosumer_container()
        chiller_controller_index = create_controlled_chiller(prosumer, period=_default_period(prosumer),
                                                             **_default_argument())
        chiller_controller = prosumer.controller.iloc[chiller_controller_index].object

        # Expected input and result columns for the chiller controller
        input_columns_expected = ["t_set_pt_c", "t_in_ev_c", "t_in_cond_c", "dt_cond_c", "q_load_kw", "n_is",
                                  "q_max_kw", "ctrl"]
        result_columns_expected = [
            "q_evap_kw",
            "unmet_load_kw",
            "w_in_tot_kw",
            "eer",
            "plr",
            "t_out_ev_in_c",
            "t_out_cond_in_c",
            "m_evap_kg_per_s",
            "m_cond_kg_per_s",
            "q_cond_kw",
        ]

        assert chiller_controller.input_columns == input_columns_expected
        assert chiller_controller.result_columns == result_columns_expected

    def test_controller_run_control_no_demand(self):
        """
        Test the Chiller controller without any demand.
        Expect the Chiller to be off and results to be zero.
        """
        prosumer = create_empty_prosumer_container()
        chiller_controller_idx = create_controlled_chiller(
            prosumer, order=0, period=_default_period(prosumer), n_ref="R410A"
        )
        chiller_controller = prosumer.controller.iloc[chiller_controller_idx].object

        # Set inputs with no demand
        chiller_controller.inputs = np.array([[280.15, 285.15, 303.15, 5, 0, 0.85, 337320, 0]])
        chiller_controller.time_step(prosumer, "2020-01-01 00:00:00")

        chiller_controller.control_step(prosumer)

        expected_results = [0.0, 0.0, 0.0, 0.0, 0.0, 285.15, 303.15, 0.0, 0.0,
                            0.0]

        # Assertions to verify chiller is off and results are as expected
        assert chiller_controller.step_results[0, 0] == 0.0
        assert chiller_controller.step_results[0, 1] == 0.0
        assert chiller_controller.step_results[0, 2] == 0.0
        assert chiller_controller.step_results[0, 3] == 0.0
        assert chiller_controller.step_results[0, 4] == 0.0
        assert chiller_controller.step_results[0, 5] == 285.15
        assert chiller_controller.step_results[0, 6] == 303.15
        assert chiller_controller.step_results[0, 7] == 0.0
        assert chiller_controller.step_results[0, 8] == 0.0
        assert chiller_controller.step_results[0, 9] == 0.0

        # Check that the results match expected values
        assert chiller_controller.step_results == pytest.approx(np.array([expected_results]), rel=1e-2)


    def test_controller_run_control_invalid_source_temperature(self):
        """
        Test the Chiller controller with source temperature too low to operate.
        Expect the chiller to not be activated.
        """
        prosumer = create_empty_prosumer_container()
        period_idx = _default_period(prosumer)

        chiller_controller_idx = create_controlled_chiller(
            prosumer, order=0, period=period_idx, n_ref="R410A"
        )
        chiller_controller = prosumer.controller.iloc[chiller_controller_idx].object

        # Set inputs with unreasonably low source temperature
        chiller_controller.inputs = np.array([[250.15, 285.15, 303.15, 5, 10000, 0.85, 337320, 1]])

        chiller_controller.time_step(prosumer, "2020-01-01 00:00:00")
        chiller_controller.control_step(prosumer)

        # Chiller should not run
        assert chiller_controller.step_results[0, 0] == 0.0
        assert chiller_controller.step_results[0, 3] == 0.0
        assert chiller_controller.step_results[0, 7] == 0.0

    def test_chiller_does_not_activate_when_setpoint_higher_than_inlet(self):
        """
        Chiller should not activate if the set point temp is higher than or equal to inlet.
        """
        prosumer = create_empty_prosumer_container()
        period_idx = _default_period(prosumer)
        idx = create_controlled_chiller(prosumer, order=0, period=period_idx, n_ref="R410A")
        chiller = prosumer.controller.iloc[idx].object

        # Providing inputs with control flag ON (1), but setpoint > inlet
        chiller.inputs = np.array([[280.15, 285.15, 303.15, 5, 15000, 0.85, 337320, 1]])

        chiller.time_step(prosumer, prosumer.period.iloc[0]["start"])
        chiller.control_step(prosumer)

        expected_outputs = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 285.15, 303.15, 0.0, 0.0, 0.0]])

        assert np.allclose(chiller.step_results, expected_outputs, rtol=1e-3)









