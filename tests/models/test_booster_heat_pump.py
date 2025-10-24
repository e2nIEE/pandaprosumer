import pytest
from pandaprosumer.create import *
from pandaprosumer.create_controlled import *


def _default_period(prosumer):
    return create_period(prosumer, 1,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 11:59:59",
                               timezone="utc")

class TestBoosterHeatPump:

    def test_define_element(self):
        """
        Test the creation of a Booster Heat Pump element with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)
        create_booster_heat_pump(prosumer, 'water-water1', name="example_hp")

        assert hasattr(prosumer, 'booster_heat_pump')
        assert len(prosumer.booster_heat_pump) == 1

        expected_columns = ['name', 'hp_type', 'in_service']
        expected_values = ['example_hp', 'water-water1', True]

        assert list(prosumer.booster_heat_pump.columns) == expected_columns
        assert list(prosumer.booster_heat_pump.iloc[0]) == expected_values

    def test_define_element_with_parameters(self):
        """
        Test the creation of a Booster Heat Pump element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)
        bhp_idx = create_booster_heat_pump(prosumer, 'water-water1', name="example_hp")

        assert hasattr(prosumer, 'booster_heat_pump')
        assert len(prosumer.booster_heat_pump) == 1
        assert prosumer.booster_heat_pump.index[0] == bhp_idx
        assert isinstance(prosumer.booster_heat_pump.columns[0], str)
        assert isinstance(prosumer.booster_heat_pump.columns[1], str)
        assert isinstance(prosumer.booster_heat_pump.columns[2], str)
        assert isinstance(prosumer.booster_heat_pump.iloc[0].values[0], str)
        assert isinstance(prosumer.booster_heat_pump.iloc[0].values[1], str)
        assert bool(prosumer.booster_heat_pump.iloc[0].values[2])

    def test_define_controller(self):
        """
        Test the creation of a Booster Heat Pump controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='water-water1')

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of a Booster Heat Pump controller
        """
        prosumer = create_empty_prosumer_container()

        bhp_controller_idx = create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='water-water1')
        bhp_controller = prosumer.controller.iloc[bhp_controller_idx].object

        input_columns_expected = ["t_source_k", 'demand', 'mode', 'q_received_kw', 'p_received_kw']
        result_columns_expected = ['cop_floor', 'cop_radiator', 'p_el_floor', 'p_el_radiator', 'q_remain', 'q_floor', 'q_radiator']

        assert bhp_controller.input_columns == input_columns_expected
        assert bhp_controller.result_columns == result_columns_expected

    def test_controller_get_param(self):
        """
        Test the method to get the input values of a Booster Heat Pump controller

        """
        prosumer = create_empty_prosumer_container()
        bhp_controller_idx = create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='water-water1', t_source_k=300)
        bhp_controller = prosumer.controller.iloc[bhp_controller_idx].object

        assert bhp_controller.element_instance.iloc[0]['t_source_k'] == pytest.approx(300.0)


    def test_controller_run_control_no_demand(self):
        """
        Test the Heat Pump controller without any demand
        Expect the Booster Heat Pump to be off
        """
        prosumer = create_empty_prosumer_container()
        bhp_controller_idx = create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='water-water1')
        bhp_controller = prosumer.controller.iloc[bhp_controller_idx].object

        bhp_controller.inputs = np.array([[295, 0, 3, 0, 0]])
        bhp_controller.time_step(prosumer, "2020-01-01 00:00:00")

        bhp_controller.control_step(prosumer)

        expected = [5.21054, 5.26054, 0.0, 0.0 ,0.0, 0.0, 0.0 ] # results

        assert bhp_controller.step_results[0, 0] >= 1 or bhp_controller.step_results[0, 0] == 0
        assert bhp_controller.step_results[0, 1] >= 1 or bhp_controller.step_results[0, 1] == 0
        assert bhp_controller.step_results[0, 2] <= bhp_controller.step_results[0, 5]
        assert bhp_controller.step_results[0, 3] <= bhp_controller.step_results[0, 6]
        assert bhp_controller.step_results == pytest.approx(np.array([expected]))



    def test_controller_run_control_demand(self):
        """
        Test the Heat Pump controller with a demand
        """
        prosumer = create_empty_prosumer_container()

        bhp_controller_idx = create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='water-water1')
        bhp_controller = prosumer.controller.iloc[bhp_controller_idx].object

        bhp_controller.inputs = np.array([[295, 1.0, 3, 0, 0]])
        bhp_controller.q_requested_kw = lambda x: 1.0

        bhp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        bhp_controller.control_step(prosumer)

        expected = [5.21054, 5.26054, 0.191918, 0.19009, 0.0, 1.0, 1.0]

        assert bhp_controller.step_results[0, 0] >= 1 or bhp_controller.step_results[0, 0] == 0
        assert bhp_controller.step_results[0, 1] >= 1 or bhp_controller.step_results[0, 1] == 0
        assert bhp_controller.step_results[0, 2] <= bhp_controller.step_results[0, 5]
        assert bhp_controller.step_results[0, 3] <= bhp_controller.step_results[0, 6]
        assert bhp_controller.step_results == pytest.approx(np.array([expected]), rel=1e-2)

    def test_different_bhp_types(self):
        prosumer = create_empty_prosumer_container()

        bhp_controller_idx_ww1 = create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='water-water1')
        bhp_controller_ww1 = prosumer.controller.iloc[bhp_controller_idx_ww1].object
        bhp_controller_ww1.inputs = np.array([[295, 1.0, 3, 0, 0]])
        bhp_controller_ww1.q_requested_kw = lambda x: 1.0
        bhp_controller_ww1.time_step(prosumer, "2020-01-01 00:00:00")
        bhp_controller_ww1.control_step(prosumer)

        bhp_controller_idx_aw = create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='air-water')
        bhp_controller_aw = prosumer.controller.iloc[bhp_controller_idx_aw].object
        bhp_controller_aw.inputs = np.array([[295, 1.0, 3, 0, 0]])
        bhp_controller_aw.q_requested_kw = lambda x: 1.0
        bhp_controller_aw.time_step(prosumer, "2020-01-01 00:00:00")
        bhp_controller_aw.control_step(prosumer)

        bhp_controller_idx_ww2 = create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='water-water2')
        bhp_controller_ww2 = prosumer.controller.iloc[bhp_controller_idx_ww2].object
        bhp_controller_ww2.inputs = np.array([[295, 1.0, 3, 0, 0]])
        bhp_controller_ww2.q_requested_kw = lambda x: 1.0
        bhp_controller_ww2.time_step(prosumer, "2020-01-01 00:00:00")
        bhp_controller_ww2.control_step(prosumer)

        assert bhp_controller_ww1.step_results[0, 0] == bhp_controller_aw.step_results[0, 0]
        assert bhp_controller_ww1.step_results[0, 1] == bhp_controller_aw.step_results[0, 1]
        assert bhp_controller_ww1.step_results[0, 2] == bhp_controller_aw.step_results[0, 2]
        assert bhp_controller_ww1.step_results[0, 3] == bhp_controller_aw.step_results[0, 3]

        assert bhp_controller_ww1.step_results[0, 0] <= bhp_controller_ww2.step_results[0, 0]
        assert bhp_controller_ww1.step_results[0, 1] <= bhp_controller_ww2.step_results[0, 1]
        assert bhp_controller_ww1.step_results[0, 2] >= bhp_controller_ww2.step_results[0, 2]
        assert bhp_controller_ww1.step_results[0, 3] >= bhp_controller_ww2.step_results[0, 3]

        assert bhp_controller_aw.step_results[0, 0] <= bhp_controller_ww2.step_results[0, 0]
        assert bhp_controller_aw.step_results[0, 1] <= bhp_controller_ww2.step_results[0, 1]
        assert bhp_controller_aw.step_results[0, 2] >= bhp_controller_ww2.step_results[0, 2]
        assert bhp_controller_aw.step_results[0, 3] >= bhp_controller_ww2.step_results[0, 3]

    def test_different_modes(self):
        prosumer = create_empty_prosumer_container()
        bhp_controller_idx_ww1 = create_controlled_booster_heat_pump(
            prosumer, order=0, period=_default_period(prosumer), hp_type='water-water1')
        bhp_controller_ww1 = prosumer.controller.iloc[bhp_controller_idx_ww1].object

        bhp_controller_ww1.inputs = np.array([[295, 1.0, 1, 1.0, 1.0]])
        bhp_controller_ww1.q_requested_kw = lambda x: 1.0
        bhp_controller_ww1.time_step(prosumer, "2020-01-01 00:00:00")
        bhp_controller_ww1.control_step(prosumer)
        first_result = bhp_controller_ww1.step_results

        bhp_controller_ww1.inputs = np.array([[295, 1.0, 2, 0, 1.0]])
        bhp_controller_ww1.q_requested_kw = lambda x: 1.0
        bhp_controller_ww1.time_step(prosumer, "2020-01-01 00:01:00")
        bhp_controller_ww1.control_step(prosumer)
        second_result = bhp_controller_ww1.step_results

        bhp_controller_ww1.inputs = np.array([[295, 1.0, 3, 0, 0]])
        bhp_controller_ww1.q_requested_kw = lambda x: 1.0
        bhp_controller_ww1.time_step(prosumer, "2020-01-01 00:02:00")
        bhp_controller_ww1.control_step(prosumer)
        third_result = bhp_controller_ww1.step_results

        expected = [5.21054, 4.8605, 0.191919, 0.205738, 0.0, 1.0, 1.0]

        assert first_result[0, 0] == second_result[0, 0]
        assert first_result[0, 1] == second_result[0, 1]
        assert first_result[0, 2] == second_result[0, 2]
        assert first_result[0, 3] == second_result[0, 3]
        assert first_result[0, 5] >= second_result[0, 5]
        assert first_result[0, 6] >= second_result[0, 6]

        assert first_result[0, 0] == third_result[0, 0]
        assert first_result[0, 1] == third_result[0, 1]
        assert first_result[0, 2] >= third_result[0, 2]
        assert first_result[0, 3] >= third_result[0, 3]
        assert first_result[0, 5] >= third_result[0, 5]
        assert first_result[0, 6] >= third_result[0, 6]

        assert second_result[0, 0] == third_result[0, 0]
        assert second_result[0, 1] == third_result[0, 1]
        assert second_result[0, 2] >= third_result[0, 2]
        assert second_result[0, 3] >= third_result[0, 3]
        assert second_result[0, 5] >= third_result[0, 5]
        assert second_result[0, 6] >= third_result[0, 6]












