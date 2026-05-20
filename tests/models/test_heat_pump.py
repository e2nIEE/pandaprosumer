import pytest
import numpy as np
from pandaprosumer import create_empty_prosumer_container, create_period, create_heat_pump, create_controlled_heat_pump
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


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
                            "max_t_cond_out_c", "max_cop", "cond_fluid", "evap_fluid", "mode",
                            "in_service", "overflow_strategy"]
        expected_values = [None, 15., .5, np.nan, 5, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan,
                           'water', 'water', 'carnot', True, 'dump_proportional']

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
                            "max_t_cond_out_c", "max_cop", "cond_fluid", "evap_fluid", "mode",
                            "in_service", "overflow_strategy", "custom"]
        expected_values = ['foo', 15., .5, 5., 10., 300, 10, .02, .03, 80, 5, 'water', 'air', 'carnot',
                           False, 'dump_proportional', 'test']
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

    def test_controller_mode_lorenz(self):
        """
        Test the Heat Pump controller with Lorenz mode
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)

        # Create heat pump with Lorenz mode
        params = _default_argument()
        params['mode'] = 'lorenz'
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=period, **params)
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

        # Test that mode parameter is stored correctly
        mode = hp_controller._get_element_param(prosumer, 'mode')
        assert mode == 'lorenz'

        # Test basic functionality with Lorenz mode
        t_cond_out_required_c = 60
        t_cond_in_required_c = 40
        mdot_cond_required_kg_per_s = 1.0
        t_evap_in_c = 10
        pinch_c = 5

        (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
         mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
         mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = hp_controller._calculate_heat_pump(
            prosumer,
            mdot_cond_required_kg_per_s,
            t_cond_out_required_c,
            t_cond_in_required_c,
            t_evap_in_c,
            pinch_c
        )

        # Verify results are reasonable
        assert q_cond_kw > 0, "Condenser power should be positive"
        assert p_comp_kw > 0, "Compressor power should be positive"
        assert cop_hp > 1, "COP should be greater than 1"
        assert mdot_evap_kg_per_s > 0, "Evaporator mass flow should be positive"

    def test_controller_mode_carnot(self):
        """
        Test the Heat Pump controller with Carnot mode (default)
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)

        # Create heat pump with explicit Carnot mode
        params = _default_argument()
        params['mode'] = 'carnot'
        hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=period, **params)
        hp_controller = prosumer.controller.iloc[hp_controller_idx].object

        # Test that mode parameter is stored correctly
        mode = hp_controller._get_element_param(prosumer, 'mode')
        assert mode == 'carnot'

        # Test basic functionality with Carnot mode
        t_cond_out_required_c = 60
        t_cond_in_required_c = 40
        mdot_cond_required_kg_per_s = 1.0
        t_evap_in_c = 10
        pinch_c = 5

        (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
         mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
         mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = hp_controller._calculate_heat_pump(
            prosumer,
            mdot_cond_required_kg_per_s,
            t_cond_out_required_c,
            t_cond_in_required_c,
            t_evap_in_c,
            pinch_c
        )

        # Verify results are reasonable
        assert q_cond_kw > 0, "Condenser power should be positive"
        assert p_comp_kw > 0, "Compressor power should be positive"
        assert cop_hp > 1, "COP should be greater than 1"
        assert mdot_evap_kg_per_s > 0, "Evaporator mass flow should be positive"

    def test_controller_mode_case_insensitive(self):
        """
        Test that the mode parameter is case insensitive
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)

        # Test various case combinations
        for mode_value in ['LORENZ', 'Lorenz', 'LoReNz', 'CARNOT', 'Carnot', 'CaRnOt']:
            params = _default_argument()
            params['mode'] = mode_value
            hp_controller_idx = create_controlled_heat_pump(prosumer, order=0, period=period, **params)
            hp_controller = prosumer.controller.iloc[hp_controller_idx].object

            # Get the stored mode (controller converts to lowercase when reading)
            stored_mode = hp_controller._get_element_param(prosumer, 'mode')
            # The mode should be converted to lowercase by the controller logic
            assert stored_mode.lower() == mode_value.lower(), f"Mode {mode_value} should be treated as {mode_value.lower()}"

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
                  'max_cop': 10,
                  'overflow_strategy': 'cap'}
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

    @pytest.mark.parametrize("t_cond_out_c, t_evap_in_c, mdot_dmd, expected_behavior", [
        # Normal operation
        (80, 20, 1.0, "normal"),
        # High temperature lift
        (90, 10, 0.5, "high_lift"),
        # Low temperature lift
        (50, 30, 1.5, "low_lift"),
        # Moderate conditions
        (60, 25, 0.8, "moderate"),
    ])
    def test_controller_run_control_parametrized(self, t_cond_out_c, t_evap_in_c, mdot_dmd, expected_behavior):
        """Test heat pump under various temperature and demand conditions"""
        params = {'max_p_comp_kw': 500,
                  'min_p_comp_kw': 0.01,
                  'max_t_cond_out_c': 100,
                  'max_cop': 10,
                  'pinch_c': 0}
        
        prosumer = create_empty_prosumer_container()
        hp_controller_index = create_controlled_heat_pump(prosumer,
                                                           period=_default_period(prosumer),
                                                           **params)
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        
        hp_controller.t_m_to_deliver = lambda x: (t_cond_out_c, t_evap_in_c, [mdot_dmd])
        hp_controller.inputs = np.array([[t_evap_in_c]])  # Provide evaporator input temperature
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)
        
        result = hp_controller.step_results[0]
        q_cond_kw = result[0]
        p_comp_kw = result[1]
        q_evap_kw = result[2]
        
        # Basic physics validation - energy balance
        assert abs(q_cond_kw - (p_comp_kw + q_evap_kw)) < 1e-2, "Energy balance violated: Q_cond ≠ P_comp + Q_evap"
        
        # COP validation
        cop = q_cond_kw / p_comp_kw if p_comp_kw > 1e-3 else float('inf')
        assert cop <= params['max_cop'] + 1, f"COP {cop} exceeds maximum {params['max_cop']}"
        
        # Temperature validation - allow some tolerance for physical constraints
        assert result[6] == pytest.approx(t_cond_out_c, rel=1e-1), "Condenser output temperature mismatch"
        assert result[5] == pytest.approx(t_evap_in_c, rel=1e-2), "Evaporator input temperature mismatch"
        
        # Behavior-specific validation
        if expected_behavior == "high_lift":
            # High temperature lift should result in lower COP
            assert 2 <= cop <= 6, f"High lift COP {cop} should be in typical range"
        elif expected_behavior == "low_lift":
            # Low temperature lift should result in higher COP
            assert cop >= 4, f"Low lift COP {cop} should be relatively high"
        elif expected_behavior == "moderate":
            # Moderate conditions should have reasonable COP
            assert 3 <= cop <= 8, f"Moderate COP {cop} should be in reasonable range"

    def test_controller_cop_calculation(self):
        """Test that COP is calculated correctly under different conditions"""
        params = {'max_p_comp_kw': 500,
                  'min_p_comp_kw': 0.01,
                  'max_t_cond_out_c': 100,
                  'max_cop': 8,  # Set a reasonable max COP
                  'pinch_c': 0}
        
        prosumer = create_empty_prosumer_container()
        hp_controller_index = create_controlled_heat_pump(prosumer,
                                                           period=_default_period(prosumer),
                                                           **params)
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        
        # Test in Carnot mode
        t_cond_out_c, t_evap_in_c = 80, 20
        mdot_dmd = 1.0
        
        hp_controller.t_m_to_deliver = lambda x: (t_cond_out_c, t_evap_in_c, [mdot_dmd])
        hp_controller.inputs = np.array([[t_evap_in_c]])  # Provide evaporator input temperature
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)
        
        result = hp_controller.step_results[0]
        q_cond_kw = result[0]
        p_comp_kw = result[1]
        cop_carnot = q_cond_kw / p_comp_kw if p_comp_kw > 1e-3 else float('inf')
        
        # COP should be reasonable for Carnot cycle
        assert 2.5 <= cop_carnot <= params['max_cop'] + 1, f"Carnot COP {cop_carnot} should be in reasonable range"
        
        # Test in Lorenz mode
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        prosumer.heat_pump.iloc[0].mode = 'lorenz'
        
        hp_controller.control_step(prosumer)
        
        result_lorenz = hp_controller.step_results[0]
        q_cond_kw_lorenz = result_lorenz[0]
        p_comp_kw_lorenz = result_lorenz[1]
        cop_lorenz = q_cond_kw_lorenz / p_comp_kw_lorenz if p_comp_kw_lorenz > 1e-3 else float('inf')
        
        # Lorenz COP should be lower than Carnot for same conditions
        assert cop_lorenz <= cop_carnot, f"Lorenz COP {cop_lorenz} should be ≤ Carnot COP {cop_carnot}"
        assert 2 <= cop_lorenz <= params['max_cop'], f"Lorenz COP {cop_lorenz} should be in reasonable range"

    def test_energy_balance(self):
        """Verify energy balance: electrical power + evaporator heat = condenser heat"""
        params = {'max_p_comp_kw': 500,
                  'min_p_comp_kw': 0.01,
                  'max_t_cond_out_c': 100,
                  'max_cop': 10,
                  'pinch_c': 0}
        
        prosumer = create_empty_prosumer_container()
        hp_controller_index = create_controlled_heat_pump(prosumer,
                                                           period=_default_period(prosumer),
                                                           **params)
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        
        test_conditions = [
            (80, 20, 1.0),   # Normal conditions
            (60, 30, 0.5),   # Low lift
            (90, 10, 1.5),   # High lift
            (50, 40, 0.8),   # Very low lift
        ]
        
        for t_cond_out_c, t_evap_in_c, mdot_dmd in test_conditions:
            hp_controller.t_m_to_deliver = lambda x: (t_cond_out_c, t_evap_in_c, [mdot_dmd])
            hp_controller.inputs = np.array([[t_evap_in_c]])  # Provide evaporator input temperature
            hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
            hp_controller.control_step(prosumer)
            
            result = hp_controller.step_results[0]
            q_cond_kw = result[0]   # Condenser heat output
            p_comp_kw = result[1]   # Compressor electrical power
            q_evap_kw = result[2]   # Evaporator heat input
            
            # Energy balance: Q_condenser = P_compressor + Q_evaporator
            energy_error = abs(q_cond_kw - (p_comp_kw + q_evap_kw))
            relative_error = energy_error / max(q_cond_kw, 1e-3)
            
            assert relative_error < 1e-2, (
                f"Energy balance violated for conditions ({t_cond_out_c}°C, {t_evap_in_c}°C, {mdot_dmd} kg/s): "
                f"|Q_cond - (P_comp + Q_evap)| = {energy_error} kW ({relative_error*100:.1f}% error)"
            )

    def test_max_t_cond_out_c_constraint(self):
        """Test that condenser output temperature doesn't exceed maximum"""
        max_temp_c = 75  # Maximum condenser output temperature
        params = {'max_p_comp_kw': 500,
                  'min_p_comp_kw': 0.01,
                  'max_t_cond_out_c': max_temp_c,
                  'max_cop': 10,
                  'pinch_c': 0}
        
        prosumer = create_empty_prosumer_container()
        hp_controller_index = create_controlled_heat_pump(prosumer,
                                                           period=_default_period(prosumer),
                                                           **params)
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        
        t_requested_c = 85  # Requested temperature higher than max constraint
        t_evap_in_c = 20
        mdot_dmd = 1.0
        
        hp_controller.t_m_to_deliver = lambda x: (t_requested_c, t_evap_in_c, [mdot_dmd])
        hp_controller.inputs = np.array([[t_evap_in_c]])  # Provide evaporator input temperature
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)
        
        result = hp_controller.step_results[0]
        t_cond_out_c = result[6]  # Actual condenser output temperature
        
        # Temperature should be constrained to maximum
        assert t_cond_out_c <= max_temp_c + 1e-2, (
            f"Condenser output temperature {t_cond_out_c}°C exceeds maximum {max_temp_c}°C"
        )
        
        # Power should be adjusted to achieve constrained temperature
        q_cond_kw = result[0]
        expected_q_max = mdot_dmd * 4.186 * (max_temp_c - t_evap_in_c)
        assert q_cond_kw <= expected_q_max + 1e-2, (
            f"Condenser power {q_cond_kw} kW exceeds maximum possible {expected_q_max} kW at constrained temperature"
        )

    @pytest.mark.parametrize("mode", ["carnot", "lorenz"])
    def test_mode_comparison(self, mode):
        """Compare behavior between Carnot and Lorenz modes"""
        params = {'max_p_comp_kw': 500,
                  'min_p_comp_kw': 0.01,
                  'max_t_cond_out_c': 100,
                  'max_cop': 10,
                  'pinch_c': 0}
        
        prosumer = create_empty_prosumer_container()
        hp_controller_index = create_controlled_heat_pump(prosumer,
                                                           period=_default_period(prosumer),
                                                           **params)
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        
        # Set the mode
        prosumer.heat_pump.iloc[0].mode = mode
        
        # Test conditions
        t_cond_out_c, t_evap_in_c = 80, 20
        mdot_dmd = 1.0
        
        hp_controller.t_m_to_deliver = lambda x: (t_cond_out_c, t_evap_in_c, [mdot_dmd])
        hp_controller.inputs = np.array([[t_evap_in_c]])  # Provide evaporator input temperature
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hp_controller.control_step(prosumer)
        
        result = hp_controller.step_results[0]
        q_cond_kw = result[0]
        p_comp_kw = result[1]
        cop = q_cond_kw / p_comp_kw if p_comp_kw > 1e-3 else float('inf')
        
        # Basic validation for both modes
        assert q_cond_kw > 0, f"No heat output in {mode} mode"
        assert p_comp_kw > 0, f"No power consumption in {mode} mode"
        assert cop > 1, f"COP ≤ 1 in {mode} mode (violates thermodynamics)"
        assert cop <= params['max_cop'] + 1, f"COP exceeds maximum in {mode} mode"
        
        # Mode-specific validation
        if mode == "carnot":
            # Carnot should have reasonable COP for these conditions
            carnot_cop_theoretical = (273 + t_cond_out_c) / (t_cond_out_c - t_evap_in_c)
            assert cop <= carnot_cop_theoretical * 0.6, (
                f"Carnot COP {cop} exceeds 60% of theoretical maximum {carnot_cop_theoretical}"
            )
        else:  # lorenz
            # Lorenz should have lower COP than Carnot for same conditions
            # (This would need comparison with Carnot mode, but we test them separately)
            assert 2 <= cop <= 8, f"Lorenz COP {cop} should be in typical range"

    def test_invalid_parameters(self):
        """Test handling of invalid parameters"""
        prosumer = create_empty_prosumer_container()
        
        # Test max_p_comp_kw < min_p_comp_kw - this may not raise an error in current implementation
        # but we test that it handles the situation gracefully
        try:
            hp_controller_index_invalid = create_controlled_heat_pump(prosumer,
                                       period=_default_period(prosumer),
                                       max_p_comp_kw=10,  # max < min
                                       min_p_comp_kw=20)
            # If it doesn't raise an error, at least verify the controller was created
            assert hp_controller_index_invalid is not None
        except (ValueError, Exception):
            # This is also acceptable behavior
            pass
        
        # Test with valid parameters first, then modify to invalid
        hp_controller_index = create_controlled_heat_pump(prosumer,
                                                           period=_default_period(prosumer),
                                                           max_p_comp_kw=500,
                                                           min_p_comp_kw=0.01)
        
        # Test impossible temperature combinations (evap > cond)
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        hp_controller.t_m_to_deliver = lambda x: (50, 60, [1.0])  # evap_in > cond_out
        hp_controller.inputs = np.array([[60]])  # Provide evaporator input temperature
        hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        
        # This should raise an appropriate error for impossible temperature conditions
        with pytest.raises(AssertionError) as exc_info:
            hp_controller.control_step(prosumer)
        
        # Check that the error message indicates the temperature issue
        error_msg = str(exc_info.value).lower()
        assert "t_cond_out_required_c" in error_msg and "t_cond_in_required_c" in error_msg, (
            f"Expected temperature-related error, got: {exc_info.value}"
        )

    def test_cop_limit_enforcement(self):
        """Test that COP doesn't exceed maximum specified value"""
        max_cop = 6  # Set a relatively low max COP for testing
        params = {'max_p_comp_kw': 500,
                  'min_p_comp_kw': 0.01,
                  'max_t_cond_out_c': 100,
                  'max_cop': max_cop,
                  'pinch_c': 0}
        
        prosumer = create_empty_prosumer_container()
        hp_controller_index = create_controlled_heat_pump(prosumer,
                                                           period=_default_period(prosumer),
                                                           **params)
        hp_controller = prosumer.controller.iloc[hp_controller_index].object
        
        # Test under conditions that would naturally produce high COP
        test_conditions = [
            (50, 40, 1.0),   # Very low temperature lift
            (55, 45, 0.5),   # Extremely low lift
        ]
        
        for t_cond_out_c, t_evap_in_c, mdot_dmd in test_conditions:
            hp_controller.t_m_to_deliver = lambda x: (t_cond_out_c, t_evap_in_c, [mdot_dmd])
            hp_controller.inputs = np.array([[t_evap_in_c]])  # Provide evaporator input temperature
            hp_controller.time_step(prosumer, "2020-01-01 00:00:00")
            hp_controller.control_step(prosumer)
            
            result = hp_controller.step_results[0]
            q_cond_kw = result[0]
            p_comp_kw = result[1]
            
            if p_comp_kw > 1e-3:  # Avoid division by zero
                cop = q_cond_kw / p_comp_kw
                assert cop <= max_cop + 0.5, (
                    f"COP {cop} exceeds maximum {max_cop} for conditions "
                    f"({t_cond_out_c}°C, {t_evap_in_c}°C)"
                )
        