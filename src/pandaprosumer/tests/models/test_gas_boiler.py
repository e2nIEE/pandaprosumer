
import pytest
from pandaprosumer import *
def _default_argument():
    return {'max_q_kw': 100,
            'heating_value_kj_per_kg':20e3}

def _default_period(prosumer):
    return create_period(prosumer, 1,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 11:59:59",
                               timezone="utc")


class TestGasBoiler:
    """
    Tests the functionalities of a Gaz Boiler element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a Gas Boiler element with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_gas_boiler(prosumer,**_default_argument())
        assert hasattr(prosumer, "gas_boiler")
        assert len(prosumer.gas_boiler) == 1
        expected_columns = ["name", "max_q_kw","heating_value_kj_per_kg", "efficiency_percent", "in_service"]
        expected_values = [None, 100, 20e3, 100, True]

        assert sorted(prosumer.gas_boiler.columns) == sorted(expected_columns)

        assert prosumer.gas_boiler.iloc[0].values == pytest.approx(expected_values)

    def test_define_element_with_parameters(self):
        """
        Test the creation of a Gas Boiler element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'max_q_kw': 250,
                  'efficiency_percent': 75,
                  'heating_value_kj_per_kg': 18e3}

        gsb_idx = create_gas_boiler(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "gas_boiler")
        assert len(prosumer.gas_boiler) == 1
        assert gsb_idx == 4
        assert prosumer.gas_boiler.index[0] == gsb_idx

        expected_columns = ["name", "max_q_kw","heating_value_kj_per_kg", "efficiency_percent", "in_service", "custom"]
        expected_values = ['foo', 250,18e3, 75, False, 'test']
        assert sorted(prosumer.gas_boiler.columns) == sorted(expected_columns)
        assert prosumer.gas_boiler.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """
        Test the creation of a Gas Boiler controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_gas_boiler(prosumer,period=_default_period(prosumer),**_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of the Gas Boiler controller"""
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,period=_default_period(prosumer),**_default_argument())
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object

        input_columns_expected = []
        result_columns_expected = ['q_kw', 'mdot_kg_per_s', 't_in_c', 't_out_c', 'mdot_gas_kg_per_s']

        assert gsb_controller.input_columns == input_columns_expected
        assert gsb_controller.result_columns == result_columns_expected

    def test_controller_run_control_no_demand(self):
        """
        Test the Gas Boiler run control method with no demand.
        Expected results no heat to be delivered.
        """
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer, period=_default_period(prosumer),
                                                            **_default_argument())
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object

        gsb_controller.t_m_to_deliver = lambda x: (0, 0, [0])

        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        expected = [0, 0, 0,0, 0]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_demand(self):
        """
        Test the Gas Boiler run control method with a demand.
        Expect the demand to be delivered.
        """

        params = {'max_q_kw': 500,
                  'heating_value_kj_per_kg': 20e3}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer, period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object

        gsb_controller.t_m_to_deliver = lambda x: (80, 20, [1.5])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        expected = [1.5*4.186*(80-20), 1.5, 20, 80, 1.5*4.186*(80-20)/20e3]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                              FluidMixMapping.MASS_FLOW_KEY: 1.5}]

    def test_controller_run_control_outrange(self):
        """
        Test the Gas Boiler run control method with a demand that is higher than the maximum power.
        Expect the demand to be delivered with the maximum power.
        """
        params = {'max_q_kw': 500,
                  'efficiency_percent': 50,
                  'heating_value_kj_per_kg': 20e3}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer, period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        gsb_controller.t_m_to_deliver = lambda x: (80, 20, [4])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        q_expected = 500
        t_expected_out_c = 20+q_expected/(4*4.186)
        expected = [q_expected, 4, 20, t_expected_out_c,500/20e3]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: 4}]

    def test_controller_run_control_outrange_3demands(self):
        """
        Test the Gaz Boiler run control method with 3 demands, the total being higher than the maximum power.
        Expect the demand to be delivered with the maximum power.
        Dispatch according to the merit order.
        """
        params = {'max_q_kw': 500,
                  'efficiency_percent': 50,
                  'heating_value_kj_per_kg': 20e3}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer, period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        gsb_controller.t_m_to_deliver = lambda x: (80, 20, [3, 2, 4])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        q_expected = 500
        t_expected_out_c = 20+q_expected/(9*4.186)
        expected = [q_expected, 9, 20, t_expected_out_c, 500/20e3]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: 3},
                                                             {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: 2},
                                                             {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: 4}]
