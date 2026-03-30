import pytest
import numpy as np
from pandaprosumer import create_empty_prosumer_container, create_period, create_heat_demand, create_controlled_heat_demand
from pandaprosumer.constants import TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


def _default_argument():
    return {}


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestHeatDemand:
    """
    Tests the functionalities of a Heat Pump element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a heat demand element in a prosumer container with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_heat_demand(prosumer)
        assert hasattr(prosumer, "heat_demand")
        assert len(prosumer.heat_demand) == 1

        expected_columns = ["name", "t_in_set_c", "t_out_set_c", "in_service"]
        expected_values = [None, np.nan, np.nan, True]

        assert sorted(prosumer.heat_demand.columns) == sorted(expected_columns)
        assert prosumer.heat_demand.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        """
        Test the creation of a heat demand element in a prosumer container with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        hd_params = {"t_in_set_c": 63,
                     "t_out_set_c": 35}

        hd_idx = create_heat_demand(prosumer, name='foo', in_service=False, index=4, custom='test', **hd_params)
        assert hasattr(prosumer, "heat_demand")
        assert len(prosumer.heat_demand) == 1
        assert hd_idx == 4
        assert prosumer.heat_demand.index[0] == hd_idx

        expected_columns = ["name", "t_in_set_c", "t_out_set_c", "in_service", "custom"]
        expected_values = ['foo', 63, 35, False, 'test']

        assert sorted(prosumer.heat_demand.columns) == sorted(expected_columns)
        assert prosumer.heat_demand.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """
        Test the creation of a heat demand controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer), **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        """
        Check that the input and result columns of the heat demand controller are the one expected
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer),
                                                          **_default_argument())
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object
        input_columns_expected = ["q_demand_kw", "mdot_demand_kg_per_s", "t_feed_demand_c", "t_return_demand_c",
                                  "q_received_kw"]
        result_columns_expected = ["q_received_kw", "q_uncovered_kw", "mdot_kg_per_s", "t_in_c", "t_out_c"]

        assert hd_controller.input_columns == input_columns_expected
        assert hd_controller.result_columns == result_columns_expected

    def test_required_temp_and_mdot(self):
        """
        Test the _demand_q_tf_tr_m method of the heat demand controller
        Check that for different inputs of required demand power, mass flow and temperature,
          the method returns the expected values
        """
        params = {"scaling": 1,
                  "t_in_set_c": 76.85,
                  "t_out_set_c": 30}
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer),
                                                          **params)
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object
        with pytest.raises(ValueError):
            assert hd_controller.t_m_to_receive(prosumer)

        hd_controller.inputs = np.array([[100, np.nan, np.nan, np.nan]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((76.85, 30., 0.5102989))

        hd_controller.inputs = np.array([[np.nan, 0.8, np.nan, np.nan]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((76.85, 30., 0.8))

        with pytest.raises(ValueError):
            hd_controller.inputs = np.array([[np.nan, np.nan, 80, np.nan]])
            hd_controller.t_m_to_receive(prosumer)

        with pytest.raises(ValueError):
            hd_controller.inputs = np.array([[np.nan, np.nan, np.nan, 35]])
            hd_controller.t_m_to_receive(prosumer)

        hd_controller.inputs = np.array([[np.nan, 0.8, 80, 35]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((80, 35., 0.8))

        hd_controller.inputs = np.array([[100, np.nan, 80, 35]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((80, 35., 0.53109161))

        hd_controller.inputs = np.array([[100, 0.8, np.nan, 35]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((64.905433, 35., 0.8))

        hd_controller.inputs = np.array([[100, 0.8, 80, np.nan]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((80, 50.217, .8))

        with pytest.raises(ValueError):
            hd_controller.inputs = np.array([[100, 0.8, 80, 35]])
            hd_controller.t_m_to_receive(prosumer)

    def test_controller_run_control(self):
        """
        Test the control step of the heat demand controller with different inputs
        """
        params = {'t_in_set_c': 76.85,
                  't_out_set_c': 30}
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer),
                                                          **params)
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object
        # Provide the exact amount of energy required
        # For the default value of t_out_set_c (30°C),
        # For a heat demand of 104.58385 kW at 80°C and 0.5 kg/s
        # Q = m * cp * dT = 0.5 * 4.186 * (80-30) = 104.6 kW
        # FixMe: Not exactly the good value, because of the cp value dependant on the temperature
        hd_controller.inputs = np.array([[104.58385, .5, 80, np.nan, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = .5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [104.243, .34, .5, 80., 30.1628]  # no uncovered demand
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01, 1)

        # Required more energy than supplied
        hd_controller.inputs = np.array([[200, np.nan, 80, np.nan, np.nan]])  # Requiring 200 kW
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = .5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [104.58385, 95.4, .5, 80., 30.]  # uncovered demand
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01)

        # Provide more that the amount of energy required (uncovered demand < 0)
        hd_controller.inputs = np.array([[0, np.nan, 80, np.nan, np.nan]])  # Requiring 0 kW
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = .5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [104.58385, -104.58385, .5, 80., 30.]  # Extra supplied energy
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01)

        # Provide too low feed temperature
        hd_controller.inputs = np.array([[104.6, np.nan, 80, np.nan, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 40
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = .5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [20.8992125, 83.7, .5, 40., 30.]  # Power supplied: .5*4.186*(40-30) = 20.9, thus 83.7 uncovered
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01)

    def test_controller_t_m_to_receive(self):
        """
        For a fixed heat demand, test the t_m_to_receive method
        The demand power, mass flow and temperatures are fixed
        Put different values for the fluid input mass flow and temperature (as is actually provided by first
        merit order upstream controllers) and check that the method returns the expected values for the
        feed temperature, return temperature and mass flow that are still to be provided (as to be provided
        by remaining later merit order initiators)
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer),
                                                          **_default_argument())
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object
        q_demand_kw = 104.58385
        mdot_demand_kg_per_s = .5
        t_feed_demand_c = 80
        cp_kj_per_kgk = prosumer.fluid.get_heat_capacity(273.15 + t_feed_demand_c) / 1000
        t_return_demand_c = t_feed_demand_c - q_demand_kw / (mdot_demand_kg_per_s * cp_kj_per_kgk)

        hd_controller.inputs = np.array([[q_demand_kw, mdot_demand_kg_per_s, t_feed_demand_c, np.nan]])

        assert hd_controller._demand_q_tf_tr_m(prosumer) == pytest.approx(
            (q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s), .001)
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx(
            (t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s), .001)

        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c, t_return_demand_c, 0.), .001)

        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s / 3
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx(
            (t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s * 2 / 3), .001)

        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c / 2
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s / 2
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx(
            (t_feed_demand_c * 1.5, t_return_demand_c, mdot_demand_kg_per_s / 2), .001)

        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c / 2
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s + 1
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c, t_return_demand_c, 0.), .001)

    def test_controller_run_control_air(self):
        """
        Test the control step of the heat demand controller with different inputs
        """
        params = {'t_in_set_c': 76.85,
                  't_out_set_c': 30}
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer),
                                                          **params)
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object
        # Provide the exact amount of energy required
        # For the default value of t_out_set_c (30°C),
        # For a heat demand of 104.58385 kW at 80°C and 0.5 kg/s
        # Q = m * cp * dT = 0.5 * 4.186 * (80-30) = 104.6 kW
        hd_controller.inputs = np.array([[104.58385, .5, 80, np.nan, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = np.nan
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [104.58385, 0., .50163058, 80., 30.16287]  # no uncovered demand
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01, 1)



    def test_state_management(self):
        """
        Test state backup and restore functionality
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer))
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object

        # Set some initial state
        hd_controller.t_previous_out_c = 50
        hd_controller.t_previous_in_c = 80
        hd_controller.mdot_previous_in_kg_per_s = 0.5

        # Test state backup
        hd_controller._save_state()
        assert hd_controller._backup_state["t_previous_out_c"] == 50
        assert hd_controller._backup_state["t_previous_in_c"] == 80
        assert hd_controller._backup_state["mdot_previous_in_kg_per_s"] == 0.5

        # Modify state
        hd_controller.t_previous_out_c = 60
        hd_controller.t_previous_in_c = 90
        hd_controller.mdot_previous_in_kg_per_s = 0.6

        # Test state restore
        hd_controller._restore_state()
        assert hd_controller.t_previous_out_c == 50
        assert hd_controller.t_previous_in_c == 80
        assert hd_controller.mdot_previous_in_kg_per_s == 0.5

    def test_partial_fulfillment_scenarios(self):
        """
        Test scenarios where demand is only partially fulfilled
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer))
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object

        # Test partial fulfillment with lower temperature
        hd_controller.inputs = np.array([[200, np.nan, 90, 30, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 60  # Lower than required
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0.5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        
        # Should show significant uncovered demand due to lower temperature
        assert hd_controller.step_results[0, 1] > 100  # More than half uncovered
        assert hd_controller.step_results[0, 0] < 100  # Less than half fulfilled

        # Test partial fulfillment with lower mass flow
        hd_controller.inputs = np.array([[200, np.nan, 90, 30, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 90
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0.2  # Lower than needed
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        
        # Should show uncovered demand due to insufficient mass flow
        assert hd_controller.step_results[0, 1] > 50  # Significant uncovered demand
        assert hd_controller.step_results[0, 2] == pytest.approx(0.2, 0.01)  # Mass flow limited

    def test_temperature_edge_cases(self):
        """
        Test temperature-related edge cases
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer))
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object

        # Test with very small temperature difference
        hd_controller.inputs = np.array([[10, np.nan, 50.1, 50, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 50.1
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0.1
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        
        # Should handle small temperature differences correctly
        assert hd_controller.step_results[0, 0] > 0  # Some power received
        assert hd_controller.step_results[0, 1] >= 0  # May have some uncovered demand

        # Test temperature convergence behavior
        hd_controller.inputs = np.array([[100, np.nan, 80, 30, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0.5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        
        # Check that temperature difference is reasonable
        temp_diff = abs(hd_controller.step_results[0, 3] - hd_controller.step_results[0, 4])
        assert temp_diff <= 60  # Should be less than the initial 50°C difference + some tolerance

    @pytest.mark.parametrize("q_demand, t_feed, t_return, mdot, expected_error", [
        (100, 80, np.nan, 0, None), 
        # Test case: q_demand_kw, t_feed_demand_c and t_return_demand_c provided (3 inputs, mdot=NaN) - should work
        (100, 80, 30, np.nan, None),  # Should work - exactly 3 inputs provided
        # Test case: q_demand_kw, t_feed_demand_c and mdot_demand_kg_per_s provided (3 inputs, t_return=NaN) - should work
        (100, 80, np.nan, 0.5, None),  # Should work - exactly 3 inputs provided
        # Test case: All 4 inputs provided (should work according to docs, but current implementation raises error)
        (100, 80, 30, 0.5, ValueError),  # Current bug: raises error when all 4 provided
        # Test case: No inputs provided (should raise error)
        (np.nan, np.nan, np.nan, np.nan, ValueError),
        # Test case: Only temperatures provided with zero mass flow (2 inputs) - should work with fallbacks
        (np.nan, 80, 30, 0, None),  # Should work - uses element set values for missing inputs
        # Test case: No demand - with mass flow provided (fixed division by zero bug)
        (0, 80, np.nan, 0, None),  # Should work - zero demand with zero mass flow
        # Test case: Very small demand with very small mass flow (potential numerical instability)
        (1e-6, 50, np.nan, 1e-6, None),  # Should work - very small values
        # Test case: Negative demand (should be handled gracefully)
        (-100, 80, np.nan, 0.5, None),  # Should work - negative demand
        # Test case: Equal feed and return temperatures (potential division by zero in mdot calculation)
        (100, 50, 50, np.nan, None),  # Should work - equal temperatures
        # Test case: Very large demand (potential overflow)
        (1e6, 100, np.nan, 1e3, None),  # Should work - large values
        # Test case: Zero feed temperature (edge case)
        (50, 0, np.nan, 0.1, None),  # Should work - zero feed temperature
    ])
    def test_parametrized_input_combinations(self, q_demand, t_feed, t_return, mdot, expected_error):
        """
        Test various input combinations using parametrized tests
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer))
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object

        # Set up inputs
        hd_controller.inputs = np.array([[q_demand, mdot, t_feed, t_return, np.nan]])
        
        if expected_error:
            # This combination should raise an error
            if expected_error == ValueError:
                # ValueError should be raised by _demand_q_tf_tr_m
                with pytest.raises(expected_error):
                    hd_controller._demand_q_tf_tr_m(prosumer)
            else:
                # Other errors (like AssertionError) should be raised by control_step
                with pytest.raises(expected_error):
                    hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed
                    hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot
                    hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
                    hd_controller.control_step(prosumer)
        else:
            # This combination should work
            if not np.isnan(t_feed):
                hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed
            else:
                # Use element's set temperature when input temperature is NaN
                hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = hd_controller.element_instance.t_in_set_c[hd_controller.element_index[0]]
                
            hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot
            hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
            
            # Should not raise an error
            try:
                hd_controller.control_step(prosumer)
                # If we get here, the test passed
                assert True
            except Exception as e:
                pytest.fail(f"Expected no error but got: {e}")

    @pytest.mark.parametrize("defined_vars", [
        # All combinations of exactly 3 out of 4 variables defined
        ("q_demand_kw", "mdot_demand_kg_per_s", "t_feed_demand_c"),  # Missing t_return
        ("q_demand_kw", "mdot_demand_kg_per_s", "t_return_demand_c"),  # Missing t_feed
        ("q_demand_kw", "t_feed_demand_c", "t_return_demand_c"),  # Missing mdot
        ("mdot_demand_kg_per_s", "t_feed_demand_c", "t_return_demand_c"),  # Missing q_demand
    ])
    def test_all_three_variable_combinations(self, defined_vars):
        """
        Test all valid combinations of exactly 3 out of 4 variables being defined
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer))
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object

        # Set up test values
        test_values = {
            "q_demand_kw": 100,
            "mdot_demand_kg_per_s": 0.5,
            "t_feed_demand_c": 80,
            "t_return_demand_c": 30
        }

        # Create inputs array with NaN for undefined variables
        inputs = []
        for var in ["q_demand_kw", "mdot_demand_kg_per_s", "t_feed_demand_c", "t_return_demand_c"]:
            if var in defined_vars:
                inputs.append(test_values[var])
            else:
                inputs.append(np.nan)
        inputs.append(np.nan)  # q_received_kw
        
        hd_controller.inputs = np.array([inputs])
        
        # Set up fluid input based on which temperatures are defined
        if not np.isnan(test_values["t_feed_demand_c"]):
            hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = test_values["t_feed_demand_c"]
        else:
            hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80  # Default
            
        if not np.isnan(test_values["mdot_demand_kg_per_s"]):
            hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = test_values["mdot_demand_kg_per_s"]
        else:
            hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0.5  # Default

        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        
        # Should not raise an error - this is a valid combination
        try:
            hd_controller.control_step(prosumer)
            # If we get here, the test passed
            assert True
        except Exception as e:
            pytest.fail(f"Combination {defined_vars} failed with error: {e}")

    def test_input_validation_edge_cases(self):
        """
        Test input validation edge cases
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer))
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object

        # Test invalid input combinations
        hd_controller.inputs = np.array([[100, 0.5, 80, 30, np.nan]])  # All inputs provided
        with pytest.raises(ValueError):
            hd_controller._demand_q_tf_tr_m(prosumer)

        # Test missing required inputs
        hd_controller.inputs = np.array([[np.nan, np.nan, np.nan, np.nan, np.nan]])  # No inputs
        with pytest.raises(ValueError):
            hd_controller._demand_q_tf_tr_m(prosumer)

        # Test zero demand with zero mass flow
        hd_controller.inputs = np.array([[0, np.nan, 80, 30, np.nan]])  # Zero demand
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0  # Zero mass flow for zero demand
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        # Should handle zero demand correctly
        assert hd_controller.step_results[0, 0] == pytest.approx(0, 0.01)
        assert hd_controller.step_results[0, 1] == pytest.approx(0, 0.01)

    def test_zero_mass_flow_with_non_zero_demand(self):
        """
        Test the edge case where mass flow is zero but heat demand is non-zero.
        This should result in zero effective heat demand since no mass flow means no heat transfer.
        """
        prosumer = create_empty_prosumer_container()
        hd_controller_idx = create_controlled_heat_demand(prosumer, order=0, period=_default_period(prosumer))
        hd_controller = prosumer.controller.iloc[hd_controller_idx].object

        # Test case: q_demand=100, t_feed=80, t_return=NaN, mdot=0
        # This should result in: q_demand_kw=0, t_feed=80, t_return=80, mdot=0
        hd_controller.inputs = np.array([[100, 0, 80, np.nan, np.nan]])
        result = hd_controller._demand_q_tf_tr_m(prosumer)
        
        # When mass flow is zero, no heat can be transferred
        assert result[0] == pytest.approx(0.0)  # q_demand_kw should be 0
        assert result[1] == pytest.approx(80.0)  # t_feed should remain 80
        assert result[2] == pytest.approx(80.0)  # t_return should equal t_feed
        assert result[3] == pytest.approx(0.0)  # mdot should remain 0

        # Test case: q_demand=50, t_feed=60, t_return=NaN, mdot=0
        # Even when t_feed is provided, zero mass flow means zero heat transfer
        hd_controller.inputs = np.array([[50, 0, 60, np.nan, np.nan]])
        result = hd_controller._demand_q_tf_tr_m(prosumer)
        
        assert result[0] == pytest.approx(0.0)  # q_demand_kw should be 0
        assert result[1] == pytest.approx(60.0)  # t_feed should remain 60
        assert result[2] == pytest.approx(60.0)  # t_return should equal t_feed
        assert result[3] == pytest.approx(0.0)  # mdot should remain 0
