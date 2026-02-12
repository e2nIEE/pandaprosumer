import pytest
import numpy as np

from pandaprosumer import *


def _default_argument():
    return {'max_p_comp_kw': 500,
            'min_p_comp_kw': .01,
            'max_t_cond_out_c': 100,
            'max_cop': 10,
            'pinch_c': 0
            }


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


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
                            "max_p_comp_kw", "min_p_comp_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s",
                            "max_t_cond_out_c", "max_cop", "cond_fluid", "evap_fluid", "in_service"]
        expected_values = [None, 15., .5, np.nan, 5, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 'water', 'water', True]

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
                  'max_ramp_up_kw_per_s': 0.02,
                  'max_ramp_down_kw_per_s': 0.03,
                  'max_t_cond_out_c': 80,
                  'max_cop': 5,
                  'evap_fluid': 'air'}

        hp_idx = create_heat_pump(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "heat_pump")
        assert len(prosumer.heat_pump) == 1
        assert hp_idx == 4
        assert prosumer.heat_pump.index[0] == hp_idx

        expected_columns = ["name", "delta_t_evap_c", "carnot_efficiency", "pinch_c", "delta_t_hot_default_c",
                            "max_p_comp_kw", "min_p_comp_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s", 
                            "max_t_cond_out_c", "max_cop", "cond_fluid", "evap_fluid", "in_service", "custom"]
        expected_values = ['foo', 15., .5, 5., 10., 300, 10, .02, .03, 80, 5, 'water', 'air', False, 'test']
        assert sorted(prosumer.heat_pump.columns) == sorted(expected_columns)
        assert prosumer.heat_pump.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """
        Test the creation of a Heat Pump controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()

        create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer), **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of a Heat Pump controller
        """
        prosumer = create_empty_prosumer_container()

        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer), **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

        input_columns_expected = ["t_evap_in_c"]
        result_columns_expected = ['q_cond_kw', 'p_comp_kw', 'q_evap_kw', 'cop',
                                   'mdot_cond_kg_per_s', 't_cond_in_c', 't_cond_out_c',
                                   'mdot_evap_kg_per_s', 't_evap_in_c', 't_evap_out_c']

        assert hp_controller.input_columns == input_columns_expected
        assert hp_controller.result_columns == result_columns_expected

        assert hp_controller.inputs == pytest.approx(np.full([hp_controller._nb_elements, len(hp_controller.input_columns)], np.nan), nan_ok=True)
        assert hp_controller.input_mass_flow_with_temp == {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                           FluidMixMapping.MASS_FLOW_KEY: np.nan}

    def test_controller_get_input(self):
        """
        Test the method to get the input values of a Heat Pump controller

        """
        prosumer = create_empty_prosumer_container()
        hp_params = {'carnot_efficiency': .5,
                     't_evap_in_c': 1.5}
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **hp_params)

        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

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
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **hp_params)
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object
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
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer), **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

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
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

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
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object
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
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **params)
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object
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
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **params)
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object
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

        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        delta_t_hot_default_c=45,
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

        t_evap_in_needed_c, t_evap_out_needed_c, mdot_evap_kg_per_s = hp_controller.t_m_to_receive(prosumer)
        # Fixme: t_evap_out_needed_c should be 35 ?
        assert (t_evap_in_needed_c, t_evap_out_needed_c, mdot_evap_kg_per_s) == (0, 0, 0)

    def test_controller_t_m_to_receive_demand(self):
        """
        Test the Heat Pump controller method to calculate the expected received Feed temperature,
        return temperature and mass flow with a demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        delta_t_hot_default_c=45,
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object
        hp_controller.t_m_to_deliver = lambda x: (80, 30, [1.5, .5])
        t_evap_in_required_c, t_evap_out_required_c, mdot_evap_kg_per_s = hp_controller.t_m_to_receive(prosumer)
        assert (t_evap_in_required_c, t_evap_out_required_c, mdot_evap_kg_per_s) == (35, 35 - 15, pytest.approx(4.9707))

    def test_controller_t_m_to_receive_for_t(self):
        """
        Test the Heat Pump controller method to calculate the expected received Feed temperature,
        return temperature and mass flow with no demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object
        t_evap_in_needed_c, t_evap_out_needed_c, mdot_evap_kg_per_s = hp_controller.t_m_to_receive_for_t(prosumer, 35)
        # Fixme: t_evap_out_needed_c should be 35 ?
        assert (t_evap_in_needed_c, t_evap_out_needed_c, mdot_evap_kg_per_s) == (0, 0, 0)

    def test_controller_t_m_to_receive_for_t_demand(self):
        """
        Test the Heat Pump controller method to calculate the expected received Feed temperature,
        return temperature and mass flow with a demand
        """
        prosumer = create_empty_prosumer_container()

        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

        hp_controller.t_m_to_deliver = lambda x: (80, 30, [1.5, .5])
        t_evap_in_required_c, t_evap_out_required_c, mdot_evap_kg_per_s = hp_controller.t_m_to_receive_for_t(prosumer, 35)
        assert (t_evap_in_required_c, t_evap_out_required_c, mdot_evap_kg_per_s) == (35, 35-15, pytest.approx(4.9707))

    def test_controller_run_control_demand_air(self):
        """
        Test the Heat Pump controller with a demand
        """
        prosumer = create_empty_prosumer_container()
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

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
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object
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
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=_default_period(prosumer),
                                                        **_default_argument())
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object
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

    def test_controller_run_control_ramp_speed(self):
        """
        Test the Heat Pump run control method with a demand with a constraint on the compressor ramp up and ramp down speeds.
        """
        max_ramp_up_kw_per_s = 50
        max_ramp_down_kw_per_s = 60
        resol_s = 1
        params = {'carnot_efficiency': 0.5,
                  'pinch_c': 0,
                  'delta_t_evap_c': 15,
                  'max_p_comp_kw': 500,
                  'min_p_comp_kw': .01,
                  'max_ramp_up_kw_per_s': max_ramp_up_kw_per_s,
                  'max_ramp_down_kw_per_s': max_ramp_down_kw_per_s,
                  'max_t_cond_out_c': 100,
                  'max_cop': 10}
        prosumer = create_empty_prosumer_container()
        hp_controller_index = create_controlled_heat_pump(prosumer,
                                                          period=_default_period(prosumer),
                                                          **params)
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        
        t_high_c = 80
        t_low_c = 30
        t_amb_c = 20
        t_out_c = t_amb_c - params['delta_t_evap_c']
        mdot_init = 1.5

        hp_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_init])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.inputs = np.array([[t_amb_c]])
        hp_controller.control_step(prosumer)

        q_cond_init_kw = 313.75155  # mdot_init * 4.186 * (t_high_c - t_low_c)
        power_comp_init_kw = 106.6124479
        q_evap_init_kw = q_cond_init_kw - power_comp_init_kw
        expected = [q_cond_init_kw, power_comp_init_kw, q_evap_init_kw, 2.942916, mdot_init, t_low_c, t_high_c, 3.29375808799, t_amb_c, t_out_c]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: t_high_c,
                                                             FluidMixMapping.MASS_FLOW_KEY: mdot_init}]
        
        # Increase the heat demand faster than the max ramp up speed
        hp_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [3.])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:01")
        hp_controller.inputs = np.array([[t_amb_c]])
        hp_controller.control_step(prosumer)

        power_comp_up_kw = power_comp_init_kw + max_ramp_up_kw_per_s * resol_s
        q_cond_up_kw = 460.89738333
        q_evap_up_kw = q_cond_up_kw - power_comp_up_kw
        expected = [q_cond_up_kw, power_comp_up_kw, q_evap_up_kw, 2.942916, 2.203482580, t_low_c, t_high_c, 4.838492380, t_amb_c, t_out_c]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: t_high_c,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(2.203482580, .01)}]
        
        # Decrease the heat demand faster than the max ramp down speed
        hp_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [1.])
        hp_controller.time_step(prosumer, "2020-01-01 00:00:02")
        hp_controller.inputs = np.array([[t_amb_c]])
        hp_controller.control_step(prosumer)
        
        power_comp_down_kw = power_comp_up_kw - max_ramp_down_kw_per_s * resol_s
        q_cond_down_kw = 284.3223833
        q_evap_down_kw = q_cond_down_kw - power_comp_down_kw
        expected = [q_cond_down_kw, power_comp_down_kw, q_evap_down_kw, 2.942916, 1.3593034839, t_low_c, t_high_c, 2.98481122, t_amb_c, t_out_c]
        assert hp_controller.step_results == pytest.approx(np.array([expected]))
        # FixMe: The mapped mass flow is 1 only, so the difference disappeared
        assert hp_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: t_high_c,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(1., .01)}]
        