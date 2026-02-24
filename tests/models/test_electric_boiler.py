import pytest
import numpy as np

from pandaprosumer import *


def _default_argument():
    return {'max_p_kw': 100}


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


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

        create_electric_boiler(prosumer, **_default_argument())
        assert hasattr(prosumer, "electric_boiler")
        assert len(prosumer.electric_boiler) == 1
        expected_columns = ["name", "max_p_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s", "efficiency_percent", "in_service"]
        expected_values = [None, 100, np.nan, np.nan, 100, True]

        assert sorted(prosumer.electric_boiler.columns) == sorted(expected_columns)

        assert prosumer.electric_boiler.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_with_parameters(self):
        """
        Test the creation of a Electric Boiler element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'max_p_kw': 250,
                  'max_ramp_up_kw_per_s': 0.02,
                  'max_ramp_down_kw_per_s': 0.03,
                  'efficiency_percent': 75}

        elb_idx = create_electric_boiler(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "electric_boiler")
        assert len(prosumer.electric_boiler) == 1
        assert elb_idx == 4
        assert prosumer.electric_boiler.index[0] == elb_idx

        expected_columns = ["name", "max_p_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s", "efficiency_percent", "in_service", "custom"]
        expected_values = ['foo', 250, 0.02, 0.03, 75, False, 'test']
        assert sorted(prosumer.electric_boiler.columns) == sorted(expected_columns)
        assert prosumer.electric_boiler.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_controller(self):
        """
        Test the creation of a Electric Boiler controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_electric_boiler(prosumer,
                                          order=0,
                                          period=_default_period(prosumer),
                                          **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of the Electric Boiler controller"""
        prosumer = create_empty_prosumer_container()
        elb_controller_idx = create_controlled_electric_boiler(prosumer,

                                                               order=0,
                                                               period=_default_period(prosumer),
                                                               **_default_argument())
        print(elb_controller_idx)
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
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
        elb_controller_idx = create_controlled_electric_boiler(prosumer,
                                                               order=0,
                                                               period=_default_period(prosumer),
                                                               **_default_argument())
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
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
        params = {'max_p_kw': 500,
                  'order': 0}
        prosumer = create_empty_prosumer_container()
        elb_controller_idx = create_controlled_electric_boiler(prosumer,
                                                               period=_default_period(prosumer),
                                                               **params)
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
        elb_controller.t_m_to_deliver = lambda x: (80, 20, [1.5])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        expected = [1.5 * 4.186 * (80 - 20), 1.5, 20, 80, 1.5 * 4.186 * (80 - 20)]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert elb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                              FluidMixMapping.MASS_FLOW_KEY: 1.5}]

    def test_controller_run_control_outrange(self):
        """
        Test the Electric Boiler run control method with a demand that is higher than the maximum power.
        Expect the demand to be delivered with the maximum power.
        """
        params = {'max_p_kw': 500,
                  'efficiency_percent': 50,
                  'order': 0}
        prosumer = create_empty_prosumer_container()
        elb_controller_idx = create_controlled_electric_boiler(prosumer,
                                                               period=_default_period(prosumer),
                                                               **params)
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
        elb_controller.t_m_to_deliver = lambda x: (80, 20, [4])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        mdot_expected_kg_per_s = 250 / ((80 - 20) * 4.186)
        expected = [250, mdot_expected_kg_per_s, 20, 80, 500]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .1)
        assert elb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(80, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_expected_kg_per_s, .01)}]

    def test_controller_run_control_outrange_3demands(self):
        """
        Test the Electric Boiler run control method with 3 demands, the total being higher than the maximum power.
        Expect the demand to be delivered with the maximum power.
        Dispatch according to the merit order.
        """
        params = {'max_p_kw': 500,
                  'efficiency_percent': 50,
                  'order': 0}
        prosumer = create_empty_prosumer_container()
        elb_controller_idx = create_controlled_electric_boiler(prosumer,
                                                               period=_default_period(prosumer),
                                                               **params)
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
        elb_controller.t_m_to_deliver = lambda x: (80, 20, [3, 2, 4])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        mdot_expected_kg_per_s = 250 / ((80 - 20) * 4.186)
        expected = [250, mdot_expected_kg_per_s, 20, 80, 500]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert elb_controller.result_mass_flow_with_temp == [
            {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(80, .01),
             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_expected_kg_per_s, .01)},
            {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(80, .01),
             FluidMixMapping.MASS_FLOW_KEY: 0.},
            {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(80, .01),
             FluidMixMapping.MASS_FLOW_KEY: 0.}
        ]

    def test_controller_run_control_ramp_speed(self):
        """
        Test the Electric Boiler run control method with a demand with a constraint on the ramp up and ramp down speeds.
        """
        max_ramp_up_kw_per_s = 100
        max_ramp_down_kw_per_s = 50
        resol_s = 1
        params = {'max_p_kw': 500,
                  'max_ramp_up_kw_per_s': max_ramp_up_kw_per_s,
                  'max_ramp_down_kw_per_s': max_ramp_down_kw_per_s}
        prosumer = create_empty_prosumer_container()
        elb_controller_index = create_controlled_electric_boiler(prosumer,
                                                                period=_default_period(prosumer),
                                                                **params)
        elb_controller = prosumer.controller.iloc[elb_controller_index].object
        
        t_high_c = 80
        t_low_c = 20
        mdot_init = 1.5

        elb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_init])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        power_init_kw = mdot_init * 4.186 * (t_high_c - t_low_c)
        expected = [power_init_kw, mdot_init, t_low_c, t_high_c, power_init_kw]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert elb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: t_high_c,
                                                              FluidMixMapping.MASS_FLOW_KEY: mdot_init}]
        
        # Increase the heat demand faster than the max ramp up speed
        mdot_demand_high_kg_per_s = 3.
        elb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_demand_high_kg_per_s])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:01")
        elb_controller.control_step(prosumer)

        power_up_kw = power_init_kw + max_ramp_up_kw_per_s * resol_s
        mdot_provided_high_kg_per_s = power_up_kw / (4.186 * (t_high_c - t_low_c))
        expected = [power_up_kw, mdot_provided_high_kg_per_s, t_low_c, t_high_c, power_up_kw]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert elb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: t_high_c,
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_provided_high_kg_per_s, .01)}]
        
        # Decrease the heat demand faster than the max ramp down speed
        mdot_demand_low_kg_per_s = 1.
        elb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_demand_low_kg_per_s])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:02")
        elb_controller.control_step(prosumer)
        
        power_down_kw = power_up_kw - max_ramp_down_kw_per_s * resol_s
        t_high_recalculated_c = t_low_c + power_down_kw / (mdot_demand_low_kg_per_s * 4.186)
        expected = [power_down_kw, mdot_demand_low_kg_per_s, t_low_c, t_high_recalculated_c, power_down_kw]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert elb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_high_recalculated_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_demand_low_kg_per_s, .01)}]
        