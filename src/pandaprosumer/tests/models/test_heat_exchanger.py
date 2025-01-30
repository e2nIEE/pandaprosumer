import pytest

from ..create_elements_controllers import *


def _create_heat_exchanger_controller(prosumer, **kwargs):
    default = {'max_q_kw': 100,
               'min_delta_t_1_c': 5}
    default.update(kwargs)
    period = create_period(prosumer, 1,
                           name="foo",
                           start="2020-01-01 00:00:00",
                           end="2020-01-01 00:00:09",
                           timezone="utc")

    heat_exchanger_index = init_hx_element(prosumer, **default)
    init_hx_controller(prosumer, period, [heat_exchanger_index])
    hx_controller = prosumer.controller.iloc[0].object
    return hx_controller


class TestHeatExchanger:

    """
    Tests the functionalities of a Heat Exchanger element and controller
    """

    def test_define_element(self):
        """
        Test the definition of a Heat Exchanger element with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        init_hx_element(prosumer)
        assert hasattr(prosumer, "heat_exchanger")
        assert len(prosumer.heat_exchanger) == 1

        expected_columns = ['name', 't_1_in_nom_c', 't_1_out_nom_c', 't_2_in_nom_c', 't_2_out_nom_c',
                            'mdot_2_nom_kg_per_s', 'delta_t_hot_default_c', 'max_q_kw', 'min_delta_t_1_c',
                            'primary_fluid', 'secondary_fluid', 'in_service']
        expected_values = [None, 90, 65, 50, 60, 0.4, 5., np.nan, 5., 'water', 'water', True]

        assert sorted(prosumer.heat_exchanger.columns) == sorted(expected_columns)
        assert prosumer.heat_exchanger.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        """
        Test the definition of a Heat Exchanger element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'t_1_in_nom_c': 85,
                  't_1_out_nom_c': 67,
                  't_2_in_nom_c': 48,
                  't_2_out_nom_c': 62,
                  'mdot_2_nom_kg_per_s': 0.35,
                    'delta_t_hot_default_c': 10,
                  'max_q_kw': 100,
                  'min_delta_t_1_c': 10,
                  'primary_fluid': 'air',
                  'secondary_fluid': 'water'}

        hx_idx = init_hx_element(prosumer, name='foo', in_service=False, index=4, custom='test', **params)
        assert hasattr(prosumer, "heat_exchanger")
        assert len(prosumer.heat_exchanger) == 1
        assert hx_idx == 4
        assert prosumer.heat_exchanger.index[0] == hx_idx

        expected_columns = ['name', 't_1_in_nom_c', 't_1_out_nom_c', 't_2_in_nom_c', 't_2_out_nom_c',
                            'mdot_2_nom_kg_per_s', 'delta_t_hot_default_c', 'max_q_kw', 'min_delta_t_1_c',
                            'primary_fluid', 'secondary_fluid', 'in_service', 'custom']
        expected_values = ['foo', 85, 67, 48, 62, 0.35, 10, 100, 10, 'air', 'water', False, 'test']

        assert sorted(prosumer.heat_exchanger.columns) == sorted(expected_columns)
        assert prosumer.heat_exchanger.iloc[0].values == pytest.approx(expected_values)

    def test_define_element_param_fail(self):
        """
        Test the definition of a Heat Exchanger element with invalid custom parameters values that should fail
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'t_1_in_nom_c': 85,
                  't_1_out_nom_c': 90,
                  't_2_in_nom_c': 48,
                  't_2_out_nom_c': 62,
                  'mdot_2_nom_kg_per_s': 0.35,
                  'primary_fluid': 'air',
                  'secondary_fluid': 'water'}
        with pytest.raises(ValueError):
            init_hx_element(prosumer, name='foo', in_service=False, index=4, custom='test', **params)

        params = {'t_1_in_nom_c': 85,
                  't_1_out_nom_c': 67,
                  't_2_in_nom_c': 48,
                  't_2_out_nom_c': 45,
                  'mdot_2_nom_kg_per_s': 0.35,
                  'primary_fluid': 'air',
                  'secondary_fluid': 'water'}
        with pytest.raises(ValueError):
            init_hx_element(prosumer, name='foo', in_service=False, index=4, custom='test', **params)

    def test_define_controller(self):
        """
        Test the definition of a Heat Exchanger controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        _create_heat_exchanger_controller(prosumer)

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        """
        Check the input and result columns of the Heat Exchanger controller
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        input_columns_expected = ['t_feed_in_c']
        result_columns_expected = ["mdot_1_kg_per_s", "t_1_in_c", "t_1_out_c",
                                   "mdot_2_kg_per_s", "t_2_in_c", "t_2_out_c"]

        assert hx_controller.input_columns == input_columns_expected
        assert hx_controller.result_columns == result_columns_expected

    def test_controller_run_control_no_demand(self):
        """
        Test the control step of a Heat Exchanger controller with no downstream demand.
        Expect no mass flow and no temperature change at the primary and secondary.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[110]])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        expected = [0., 110., 110., 0., 0., 0.]
        assert hx_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_demand_nominal(self):
        """
        Test the control step of a Heat Exchanger controller with downstream demand at the nominal conditions.
        Expect the mass flow and temperatures at the primary and secondary to be the same as the nominal.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[90]])
        hx_controller.t_m_to_deliver = lambda x: (60, 50, [.4])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        expected = [0.15916, 90., 65., .4, 50., 60.]
        assert hx_controller.step_results == pytest.approx(np.array([expected]), .001)
        assert hx_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 60.,
                                                             FluidMixMapping.MASS_FLOW_KEY: .4}]

    def test_controller_run_control_demand(self):
        """
        Test the control step of a Heat Exchanger controller with downstream demand different from the nominal conditions.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[93]])
        hx_controller.t_m_to_deliver = lambda x: (70, 55, [.45])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        # expected = [1.42345, 110., 103.727, .6, 70., 55.]
        expected = [1.018526, 93., 88, .3410815, 55., 70.]
        assert hx_controller.step_results == pytest.approx(np.array([expected]), .001)
        assert hx_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 70.,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(.3410815)}]

    def test_controller_run_control_2demands(self):
        """
        Test the control step of a Heat Exchanger controller with two downstream demands.
        Expect the same mass flow and temperatures as with one demand.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[110]])
        hx_controller.t_m_to_deliver = lambda x: (70, 55, [.4, .2])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        # expected = [1.42345, 110., 103.727, .6, 70., 55.]
        expected = [1.642249, 110., 105, .5518196, 55., 70.]
        assert hx_controller.step_results == pytest.approx(np.array([expected]), .001)
        assert hx_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 70.,
                                                             FluidMixMapping.MASS_FLOW_KEY: .4},
                                                            {FluidMixMapping.TEMPERATURE_KEY: 70.,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(.1518196)}]

    def test_controller_run_control_demand_outrange(self):
        """
        Test the control step of a Heat Exchanger controller with downstream demand out of the working conditions.
        Expect no heat transfer and the return temperature to be the same as the feed temperature.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[95]])
        hx_controller.t_m_to_deliver = lambda x: (60, 50, [2])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        expected = [1.37628, 95., 90., .692119, 50., 60.]
        assert hx_controller.step_results == pytest.approx(np.array([expected]), .001)
        assert hx_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 60.,
                                                            FluidMixMapping.MASS_FLOW_KEY: pytest.approx(.692119)}]

    def test_controller_run_control_2demands_outrange(self):
        """
        Test the control step of a Heat Exchanger controller with two downstream demands out of the working conditions.
        Expect no heat transfer and the return temperature to be the same as the feed temperature for both demands.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[95]])
        hx_controller.t_m_to_deliver = lambda x: (80, 30, [1.5, .5])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        expected = [1.193106, 95., 90., .12, 30., 80.]
        assert hx_controller.step_results == pytest.approx(np.array([expected]))
        assert hx_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(.12)},
                                                            {FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                             FluidMixMapping.MASS_FLOW_KEY: 0.}]
    def test_controller_t_m_to_receive(self):
        """
        Test the method t_m_to_receive_for_t of a Heat Exchanger controller with no downstream demand.
        Expect no heat transfer and the return temperature to be the same as the feed temperature.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer, delta_t_hot_default_c=30)

        t_feed_c, t_out_1_c, mdot_1_kg_per_s = hx_controller.t_m_to_receive(prosumer)
        assert (t_feed_c, t_out_1_c, mdot_1_kg_per_s) == (30, 30, 0)

    def test_controller_t_m_to_receive_demand(self):
        """
        Test the method t_m_to_receive_for_t of a Heat Exchanger controller with a downstream demand.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer, delta_t_hot_default_c=30)

        hx_controller.t_m_to_deliver = lambda x: (60, 50, [.4])
        t_feed_c, t_out_1_c, mdot_1_kg_per_s = hx_controller.t_m_to_receive(prosumer)
        assert t_feed_c == 90.
        assert t_out_1_c == pytest.approx(65, .01)
        assert mdot_1_kg_per_s == pytest.approx(0.159543, .01)

    def test_controller_t_m_to_receive_for_t(self):
        """
        Test the method t_m_to_receive_for_t of a Heat Exchanger controller with no downstream demand.
        Expect no heat transfer and the return temperature to be the same as the feed temperature.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        t_feed_c, t_out_1_c, mdot_1_kg_per_s = hx_controller.t_m_to_receive_for_t(prosumer, 90)
        assert (t_feed_c, t_out_1_c, mdot_1_kg_per_s) == (90, 90, 0)

    def test_controller_t_m_to_receive_for_t_demand(self):
        """
        Test the method t_m_to_receive_for_t of a Heat Exchanger controller with a downstream demand.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.t_m_to_deliver = lambda x: (60, 50, [.4])
        t_feed_c, t_out_1_c, mdot_1_kg_per_s = hx_controller.t_m_to_receive_for_t(prosumer, 90)
        assert t_feed_c == 90.
        assert t_out_1_c == pytest.approx(65, .01)
        assert mdot_1_kg_per_s == pytest.approx(0.159543, .01)

    def test_controller_run_control_demand_air(self):
        """
        Test the control step of a Heat Exchanger controller with downstream demand different from the nominal conditions.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[]])
        hx_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 93
        hx_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = np.nan
        hx_controller.t_m_to_deliver = lambda x: (70, 55, [.45])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        expected = [1.018526, 93., 88, .3410815, 55., 70.]
        assert hx_controller.step_results == pytest.approx(np.array([expected]), .001)
        assert hx_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 70.,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(.3410815)}]

    def test_controller_run_control_demand_higher_mass_flow(self):
        """
        Test the control step of a Heat Exchanger controller with downstream demand different from the nominal conditions.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[]])
        hx_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 93
        hx_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 1.018526 + .5
        hx_controller.t_m_to_deliver = lambda x: (70, 55, [.45])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        expected = [1.018526 + .5, 93., 89.64633, .3410815, 55., 70.]
        assert hx_controller.step_results == pytest.approx(np.array([expected]), .001)
        assert hx_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 70.,
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(.3410815)}]

    def test_controller_run_control_demand_lower_mass_flow(self):
        """
        Test the control step of a Heat Exchanger controller with downstream demand different from the nominal conditions.
        """
        prosumer = create_empty_prosumer_container()
        hx_controller = _create_heat_exchanger_controller(prosumer)

        hx_controller.inputs = np.array([[]])
        hx_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 93
        hx_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 1.018526 - .5
        hx_controller.t_m_to_deliver = lambda x: (70, 55, [.45])
        hx_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hx_controller.control_step(prosumer)

        expected = [0.518526, 93., 88, .077384, 55., 88.68328]
        assert hx_controller.step_results == pytest.approx(np.array([expected]), .001)
        assert hx_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(88.68328, .001),
                                                             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(.077384, .001)}]
