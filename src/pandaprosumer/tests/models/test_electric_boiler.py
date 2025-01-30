import numpy as np
import pytest

from pandaprosumer2.create import create_empty_prosumer_container, create_electric_boiler, create_period
from pandaprosumer2.controller import ElectricBoilerController, ElectricBoilerControllerData
from pandaprosumer2.run_time_series import run_timeseries
from ..create_elements_controllers import *


def _create_electric_boiler_controller(prosumer, **kwargs):
    period = create_period(prosumer, 1,
                           name="foo",
                           start="2020-01-01 00:00:00",
                           end="2020-01-01 11:59:59",
                           timezone="utc")

    electric_boiler_index = init_elb_element(prosumer, **kwargs)
    init_elb_controller(prosumer, period, [electric_boiler_index])
    elb_controller = prosumer.controller.iloc[0].object
    return elb_controller


class TestElectricBoiler:
    """
    Tests the functionalities of a Electric Boiler element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a Electric Boiler element with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        init_elb_element(prosumer)
        assert hasattr(prosumer, "electric_boiler")
        assert len(prosumer.electric_boiler) == 1
        expected_columns = ["name", "max_p_kw", "efficiency_percent", "in_service"]
        expected_values = [None, 100, 100, True]

        assert sorted(prosumer.electric_boiler.columns) == sorted(expected_columns)

        assert prosumer.electric_boiler.iloc[0].values == pytest.approx(expected_values)

    def test_define_element_with_parameters(self):
        """
        Test the creation of a Electric Boiler element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'max_p_kw': 250,
                  'efficiency_percent': 75}

        elb_idx = init_elb_element(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "electric_boiler")
        assert len(prosumer.electric_boiler) == 1
        assert elb_idx == 4
        assert prosumer.electric_boiler.index[0] == elb_idx

        expected_columns = ["name", "max_p_kw", "efficiency_percent", "in_service", "custom"]
        expected_values = ['foo', 250, 75, False, 'test']
        assert sorted(prosumer.electric_boiler.columns) == sorted(expected_columns)
        assert prosumer.electric_boiler.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """
        Test the creation of a Electric Boiler controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        _create_electric_boiler_controller(prosumer)

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of the Electric Boiler controller"""
        prosumer = create_empty_prosumer_container()
        elb_controller = _create_electric_boiler_controller(prosumer)

        input_columns_expected = []
        result_columns_expected = ['q_kw', 'mdot_kg_per_s', 't_in_c', 't_out_c', 'p_kw']

        assert elb_controller.input_columns == input_columns_expected
        assert elb_controller.result_columns == result_columns_expected

    def test_controller_run_control_no_demand(self):
        """
        Test the Electric Boiler run control method with no demand.
        Expected results no heat to be delivered.
        """
        prosumer = create_empty_prosumer_container()
        elb_controller = _create_electric_boiler_controller(prosumer)

        elb_controller.t_m_to_deliver = lambda x: (0, 0, [0])

        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        expected = [0, 0, 0, 0, 0]
        assert elb_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_demand(self):
        """
        Test the Electric Boiler run control method with a demand.
        Expect the demand to be delivered.
        """
        params = {'max_p_kw': 500}
        prosumer = create_empty_prosumer_container()
        elb_controller = _create_electric_boiler_controller(prosumer, **params)

        elb_controller.t_m_to_deliver = lambda x: (80, 20, [1.5])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        expected = [1.5*4.186*(80-20), 1.5, 20, 80, 1.5*4.186*(80-20)]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert elb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                              FluidMixMapping.MASS_FLOW_KEY: 1.5}]

    def test_controller_run_control_outrange(self):
        """
        Test the Electric Boiler run control method with a demand that is higher than the maximum power.
        Expect the demand to be delivered with the maximum power.
        """
        params = {'max_p_kw': 500,
                  'efficiency_percent': 50}
        prosumer = create_empty_prosumer_container()
        elb_controller = _create_electric_boiler_controller(prosumer, **params)

        elb_controller.t_m_to_deliver = lambda x: (80, 20, [4])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        t_expected_out_c = 20+250/(4*4.186)
        expected = [250, 4, 20, t_expected_out_c, 500]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert elb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: 4}]

    def test_controller_run_control_outrange_3demands(self):
        """
        Test the Electric Boiler run control method with 3 demands, the total being higher than the maximum power.
        Expect the demand to be delivered with the maximum power.
        Dispatch according to the merit order.
        """
        params = {'max_p_kw': 500,
                  'efficiency_percent': 50}
        prosumer = create_empty_prosumer_container()
        elb_controller = _create_electric_boiler_controller(prosumer, **params)

        elb_controller.t_m_to_deliver = lambda x: (80, 20, [3, 2, 4])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        t_expected_out_c = 20+250/(9*4.186)
        expected = [250, 9, 20, t_expected_out_c, 500]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert elb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: 3},
                                                             {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: 2},
                                                             {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: 4}]
