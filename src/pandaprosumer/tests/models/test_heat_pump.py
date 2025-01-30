import numpy as np
import pytest

from pandaprosumer2.create import create_empty_prosumer_container, create_heat_pump, create_period
from pandaprosumer2.controller import HeatPumpController, HeatPumpControllerData
from pandaprosumer2.run_time_series import run_timeseries
from ..create_elements_controllers import *


def _create_heat_pump_controller(prosumer, **kwargs):
    period = create_period(prosumer, 1,
                           name="foo",
                           start="2020-01-01 00:00:00",
                           end="2020-01-01 00:00:09",
                           timezone="utc")

    heat_pump_index = init_hp_element(prosumer, **kwargs)
    init_hp_controller(prosumer, period, [heat_pump_index])
    hp_controller = prosumer.controller.iloc[0].object
    return hp_controller


class TestHeatPump:
    """
    Tests the basic functionalities of a Heat Pump element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a Heat Pump element with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_heat_pump(prosumer)
        assert hasattr(prosumer, "heat_pump")
        assert len(prosumer.heat_pump) == 1
        expected_columns = ["name", "delta_t_evap_c", "carnot_efficiency", "pinch_c", "delta_t_hot_default_c",
                            "max_p_comp_kw", "min_p_comp_kw", "max_t_cond_out_c", "max_cop",
                            "cond_fluid", "evap_fluid", "in_service"]
        expected_values = [None, 15., .5, np.nan, 5, np.nan, np.nan, np.nan, np.nan, 'water', 'water', True]

        assert sorted(prosumer.heat_pump.columns) == sorted(expected_columns)

        assert prosumer.heat_pump.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_with_parameters(self):
        """
        Test the creation of a Heat Pump element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'carnot_efficiency': 0.5,
                  'pinch_c': 5,
                  'delta_t_hot_default_c': 10,
                  'delta_t_evap_c': 15,
                  'max_p_comp_kw': 300,
                  'min_p_comp_kw': 10,
                  'max_t_cond_out_c': 80,
                  'max_cop': 5,
                  'evap_fluid': 'air'}

        hp_idx = init_hp_element(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "heat_pump")
        assert len(prosumer.heat_pump) == 1
        assert hp_idx == 4
        assert prosumer.heat_pump.index[0] == hp_idx

        expected_columns = ["name", "delta_t_evap_c", "carnot_efficiency", "pinch_c", "delta_t_hot_default_c",
                            "max_p_comp_kw", "min_p_comp_kw", "max_t_cond_out_c", "max_cop",
                            "cond_fluid", "evap_fluid", "in_service", "custom"]
        expected_values = ['foo', 15., .5, 5., 10., 300, 10, 80, 5, 'water', 'air', False, 'test']
        assert sorted(prosumer.heat_pump.columns) == sorted(expected_columns)
        assert prosumer.heat_pump.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """
        Test the creation of a Heat Pump controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 1,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 11:59:59",
                               timezone="utc")
        heat_pump_index = init_hp_element(prosumer)
        init_hp_controller(prosumer, period, [heat_pump_index])

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of a Heat Pump controller
        """
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 1,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 11:59:59",
                               timezone="utc")

        heat_pump_index = init_hp_element(prosumer)
        init_hp_controller(prosumer, period, [heat_pump_index])
        hp_controller = prosumer.controller.iloc[0].object

        input_columns_expected = ["t_evap_in_c"]
        result_columns_expected = ['q_cond_kw', 'p_comp_kw', 'q_evap_kw', 'cop',
                                   'mdot_cond_kg_per_s', 't_cond_in_c', 't_cond_out_c',
                                   'mdot_evap_kg_per_s', 't_evap_in_c', 't_evap_out_c']

        assert hp_controller.input_columns == input_columns_expected
        assert hp_controller.result_columns == result_columns_expected

        assert hp_controller.inputs == pytest.approx(np.full([hp_controller._nb_elements, len(hp_controller.input_columns)], np.nan), nan_ok=True)
        assert hp_controller.input_mass_flow_with_temp == {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                           FluidMixMapping.MASS_FLOW_KEY: np.nan}

    def test_controller_columns(self):
        """
        Test to change the input and result columns of a Heat Pump controller
        """
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 1,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 11:59:59",
                               timezone="utc")

        heat_pump_index = init_hp_element(prosumer)
        init_hp_controller(prosumer,
                           period,
                           [heat_pump_index],
                           input_columns=['t_evap_in_c', 'mdot_kg_per_s'],
                           result_columns=['p_comp_kw', 'q_evap_kw', 'm_kg_per_s', 'cop', 't_cond_out_c', 't_cond_in_c'])
        hp_controller = prosumer.controller.iloc[0].object

        input_columns_expected = ['t_evap_in_c', 'mdot_kg_per_s']
        result_columns_expected = ['p_comp_kw', 'q_evap_kw', 'm_kg_per_s', 'cop', 't_cond_out_c', 't_cond_in_c']

        assert hp_controller.input_columns == input_columns_expected
        assert hp_controller.result_columns == result_columns_expected

    def test_controller_get_input(self):
        """
        Test the method to get the input values of a Heat Pump controller
        """
        prosumer = create_empty_prosumer_container()
        hp_params = {'carnot_efficiency': .5,
                     't_evap_in_c': 1.5}
        hp_controller = _create_heat_pump_controller(prosumer, **hp_params)

        assert np.isnan(hp_controller._get_input('t_evap_in_c'))
        assert hp_controller._get_input('t_evap_in_c', prosumer) == pytest.approx(1.5)
        hp_controller.inputs = np.array([[20]])
        assert hp_controller._get_input('t_evap_in_c', prosumer) == pytest.approx(20)

        with pytest.raises(KeyError):
            hp_controller._get_input('t_evap_out_c', prosumer)
        with pytest.raises(KeyError):
            hp_controller._get_input('carnot_efficiency', prosumer)

    def test_controller_get_param(self):
        """
        Test the method to get the element parameters of a Heat Pump controller
        """
        prosumer = create_empty_prosumer_container()
        hp_params = {'carnot_efficiency': .5}
        hp_controller = _create_heat_pump_controller(prosumer, **hp_params)

        hp_controller.inputs = np.array([[20]])
        assert hp_controller._get_element_param(prosumer, 'carnot_efficiency') == pytest.approx(.5)
        assert hp_controller._get_element_param(prosumer, 'evap_fluid') == 'water'
        assert hp_controller._get_element_param(prosumer, 't_evap_in_c') is None
        assert hp_controller._get_element_param(prosumer, 't_evap_out_c') is None

    def test_controller_run_control_no_demand(self):
        """
        Test the Heat Pump controller without any demand
        Expect the Heat Pump to be off (no heat exchange at evaporator and condenser 
        and no electricity consumption)
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer)

        hp_controller.inputs = np.array([[20]])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")

        hp_controller.control_step(prosumer)

        expected = [0] * 8 + [20, 20]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == pytest.approx([])

    def test_controller_run_control_demand(self):
        """
        Test the Heat Pump controller with a demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer)

        hp_controller.inputs = np.array([[20]])
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [2])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)

        expected = [418.3354, 142.14993062, 276.18546938, 2.94291667, 2., 30., 80., 4.39167745, 20., 5.]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: 2.}]

    def test_controller_run_control_2demands(self):
        """
        Test the Heat Pump controller with 2 demands
        Check the mass flow and temperature of the fluid dispatched to the 2 demands
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer)

        hp_controller.inputs = np.array([[20]])
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [1.5, .5])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)

        expected = [418.3354, 142.14993062, 276.18546938, 2.94291667, 2., 30., 80., 4.39167745, 20., 5.]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: 1.5},
                                                            {FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: .5}]

    def test_controller_run_control_demand_outrange(self):
        """
        Test the Heat Pump controller with a demand out of working range
        Check that the mass flow and temperature of the fluid dispatched to the demand is at the limit
        """
        params = {'carnot_efficiency': 0.5,
                  'pinch_c': 0,
                  'delta_t_evap_c': 15,
                  'max_p_comp_kw': 500,
                  'min_p_comp_kw': .01,
                  'max_t_cond_out_c': 100,
                  'max_cop': 10}
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer, **params)

        hp_controller.inputs = np.array([[20]])
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [10])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)

        expected = [1471.45833, 500., 971.45833, 2.94291667, 7.0348258, 30., 80., 15.4473429, 20., 5.]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(7.0348258)}]

    def test_controller_run_control_3demands_outrange(self):
        """
        Test the Heat Pump controller with 3 demands out of working range
        Test the merit order dispatch logic
        """
        params = {'carnot_efficiency': 0.5,
                  'pinch_c': 0,
                  'delta_t_evap_c': 15,
                  'max_p_comp_kw': 500,
                  'min_p_comp_kw': .01,
                  'max_t_cond_out_c': 100,
                  'max_cop': 10}
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer, **params)

        hp_controller.inputs = np.array([[20]])
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [5, 4, 1.5])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)

        expected = [1471.45833, 500., 971.45833, 2.94291667, 7.0348258, 30., 80., 15.4473429, 20., 5.]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: 5},
                                                            {FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(2.0348258)},
                                                            {FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: 0.}]

    def test_controller_t_m_to_receive(self):
        """
        Test the Heat Pump controller method to calculate the expected received Feed temperature,
        return temperature and mass flow with no demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer, delta_t_hot_default_c=45)
        t_evap_in_needed_c, t_evap_out_needed_c, mdot_evap_kg_per_s = hp_controller.t_m_to_receive(prosumer)
        # Fixme: t_evap_out_needed_c should be 35 ?
        assert (t_evap_in_needed_c, t_evap_out_needed_c, mdot_evap_kg_per_s) == (0, 0, 0)

    def test_controller_t_m_to_receive_demand(self):
        """
        Test the Heat Pump controller method to calculate the expected received Feed temperature,
        return temperature and mass flow with a demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer, delta_t_hot_default_c=45)
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [1.5, .5])
        t_evap_in_required_c, t_evap_out_required_c, mdot_evap_kg_per_s = hp_controller.t_m_to_receive(prosumer)
        assert (t_evap_in_required_c, t_evap_out_required_c, mdot_evap_kg_per_s) == (35, 35-15, pytest.approx(4.9707))

    def test_controller_t_m_to_receive_for_t(self):
        """
        Test the Heat Pump controller method to calculate the expected received Feed temperature,
        return temperature and mass flow with no demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer)
        t_evap_in_needed_c, t_evap_out_needed_c, mdot_evap_kg_per_s = hp_controller.t_m_to_receive_for_t(prosumer, 35)
        # Fixme: t_evap_out_needed_c should be 35 ?
        assert (t_evap_in_needed_c, t_evap_out_needed_c, mdot_evap_kg_per_s) == (0, 0, 0)

    def test_controller_t_m_to_receive_for_t_demand(self):
        """
        Test the Heat Pump controller method to calculate the expected received Feed temperature,
        return temperature and mass flow with a demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer)
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [1.5, .5])
        t_evap_in_required_c, t_evap_out_required_c, mdot_evap_kg_per_s = hp_controller.t_m_to_receive_for_t(prosumer, 35)
        assert (t_evap_in_required_c, t_evap_out_required_c, mdot_evap_kg_per_s) == (35, 35-15, pytest.approx(4.9707))

    def test_controller_run_control_demand_air(self):
        """
        Test the Heat Pump controller with a demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer)

        hp_controller.inputs = np.array([[20]])
        hp_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 20
        hp_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = np.nan
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [2])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)

        expected = [418.3354, 142.14993062, 276.18546938, 2.94291667, 2., 30., 80., 4.39167745, 20., 5.]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: 2.}]

    def test_controller_run_control_demand_higher_mass_flow(self):
        """
        Test the Heat Pump controller with a demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer)

        hp_controller.inputs = np.array([[20]])
        hp_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 20
        hp_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 4.39167745 + .5
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [2])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)

        expected = [418.3354, 142.14993062, 276.18546938, 2.94291667, 2., 30., 80., 4.89167745, 20., 6.5332163]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: 2.}]

    def test_controller_run_control_demand_lower_mass_flow(self):
        """
        Test the Heat Pump controller with a demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller = _create_heat_pump_controller(prosumer)

        hp_controller.inputs = np.array([[20]])
        hp_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 20
        hp_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 4.39167745 - .5
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [2])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)

        expected = [370.707198, 125.965917, 244.74128, 2.942916, 1.7722965, 30., 80., 3.8916774, 20., 5.]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(1.7722965, .001)}]
