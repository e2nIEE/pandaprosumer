import pytest
import numpy as np
from pandaprosumer import create_empty_prosumer_container, create_period, create_electric_boiler, create_controlled_electric_boiler
from pandaprosumer.controller.models.electric_boiler import _calculate_electric_boiler_temp
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


def _default_argument():
    return {'max_p_kw': 100}


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


    @pytest.mark.parametrize("allow_stop, max_t_out_c, min_p_kw", [
        (True, np.nan, np.nan),      # Default case
        (False, np.nan, np.nan),     # allow_stop=False without min_p_kw
        (True, 75, np.nan),          # Only max temperature constraint
        (False, 75, 50),             # Both constraints
        (True, 60, 30),              # Both constraints with allow_stop=True
    ])
    def test_define_element_with_various_parameters(self, allow_stop, max_t_out_c, min_p_kw):
        """
        Test the creation of a Electric Boiler element with various parameter combinations.
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'max_p_kw': 100}
        if not np.isnan(min_p_kw):
            params['min_p_kw'] = min_p_kw
        if not np.isnan(max_t_out_c):
            params['max_t_out_c'] = max_t_out_c
        params['allow_stop'] = allow_stop
        
        create_electric_boiler(prosumer, **params)
        assert hasattr(prosumer, "electric_boiler")
        assert len(prosumer.electric_boiler) == 1
        
        # Check that parameters are set correctly
        elb = prosumer.electric_boiler.iloc[0]
        assert elb.max_p_kw == 100
        assert elb.allow_stop == allow_stop
        if not np.isnan(min_p_kw):
            assert elb.min_p_kw == min_p_kw
        else:
            assert np.isnan(elb.min_p_kw)
        if not np.isnan(max_t_out_c):
            assert elb.max_t_out_c == max_t_out_c
        else:
            assert np.isnan(elb.max_t_out_c)


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
        expected_columns = ["name", "max_p_kw", "min_p_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s", "efficiency_percent", "allow_stop", "max_t_out_c", "min_on_time_s", "min_off_time_s", "in_service", "overflow_strategy"]
        expected_values = [None, 100, np.nan, np.nan, np.nan, 100, True, np.nan, np.nan, np.nan, True, 'dump_proportional']

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
                  'efficiency_percent': 75,
                  'min_on_time_s': 6 * 3600,
                  'min_p_kw': 20,
                  'min_off_time_s': 3 * 3600}

        elb_idx = create_electric_boiler(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "electric_boiler")
        assert len(prosumer.electric_boiler) == 1
        assert elb_idx == 4
        assert prosumer.electric_boiler.index[0] == elb_idx

        expected_columns = ["name", "max_p_kw", "min_p_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s", "efficiency_percent", "allow_stop", "max_t_out_c", "min_on_time_s", "min_off_time_s", "in_service", "overflow_strategy", "custom"]
        expected_values = ['foo', 250, 20, 0.02, 0.03, 75, True, np.nan, 6 * 3600, 3 * 3600, False, 'dump_proportional', 'test']
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
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
        input_columns_expected = ['max_p_kw_setpoint']
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
                  'max_ramp_down_kw_per_s': max_ramp_down_kw_per_s,
                  'overflow_strategy': 'cap'}
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
        
    @pytest.mark.parametrize("requested_temp, max_t_out_c, expected_temp", [
        (80, 60, 60),    # Temperature constrained
        (80, 90, 80),    # No constraint needed
        (50, 60, 50),    # Requested temp below constraint
        (80, 75, 75),    # Constraint at 75°C
    ])
    def test_controller_run_control_max_temperature_constraint_parametrized(self, requested_temp, max_t_out_c, expected_temp):
        """
        Test the Electric Boiler run control method with various maximum temperature constraints.
        """
        params = {'max_p_kw': 500,
                  'max_t_out_c': max_t_out_c,
                  'order': 0,
                  'overflow_strategy': 'cap'}
        prosumer = create_empty_prosumer_container()
        elb_controller_idx = create_controlled_electric_boiler(prosumer,
                                                               period=_default_period(prosumer),
                                                               **params)
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
        
        # Request a temperature that may be constrained
        elb_controller.t_m_to_deliver = lambda x: (requested_temp, 20, [1.5])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)

        # Check that output temperature respects the constraint
        result = elb_controller.step_results[0]
        assert result[3] == pytest.approx(expected_temp, .01), f"Output temperature should be {expected_temp}°C"
        
        # Check that power is calculated correctly for the actual output temperature
        expected_q_kw = 1.5 * 4.186 * (expected_temp - 20)
        assert result[4] == pytest.approx(expected_q_kw, .01), "Power should match the constrained temperature"
        
        # Check mass flow is maintained
        assert result[1] == pytest.approx(1.5, .01), "Mass flow should be maintained"
        
    @pytest.mark.parametrize("allow_stop, min_p_kw, target_power_kw, expected_power_kw", [
        (True, 50, 25, 50),   # Min power constraint with allow_stop=True
        (True, 30, 20, 30),   # Different min power level
        (True, 60, 55, 60),   # Power just below min_p_kw
    ])
    def test_controller_run_control_min_power_constraint_parametrized(self, allow_stop, min_p_kw, target_power_kw, expected_power_kw):
        """
        Test the Electric Boiler run control method with various minimum power constraints.
        """
        params = {'max_p_kw': 500,
                  'min_p_kw': min_p_kw,
                  'allow_stop': allow_stop,
                  'order': 0}
        prosumer = create_empty_prosumer_container()
        elb_controller_idx = create_controlled_electric_boiler(prosumer,
                                                               period=_default_period(prosumer),
                                                               **params)
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
        
        # Test case with demand below minimum power
        mdot_for_target_power = target_power_kw / (4.186 * (80 - 20))
        elb_controller.t_m_to_deliver = lambda x: (80, 20, [mdot_for_target_power])
        
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)
        
        # Should be constrained to minimum power
        result = elb_controller.step_results[0]
        assert result[4] >= expected_power_kw - 1e-2, f"Power should be at least {expected_power_kw} kW"
        assert result[4] <= expected_power_kw + 1e-2, f"Power should not exceed {expected_power_kw} kW significantly"
        
        # Verify energy balance: P_el = Q_thermal / efficiency
        thermal_power_kw = result[0]
        electrical_power_kw = result[4]
        efficiency_percent = 100  # Default in our test
        assert electrical_power_kw == pytest.approx(thermal_power_kw / (efficiency_percent / 100), .01), "Energy balance should be maintained"

    def test_controller_run_control_allow_stop_false(self):
        """
        Test the Electric Boiler run control method with allow_stop=False.
        This should prevent the boiler from reaching zero power.
        """
        params = {'max_p_kw': 500,
                  'min_p_kw': 50,  # Minimum power when allow_stop=False
                  'allow_stop': False,
                  'order': 0}
        prosumer = create_empty_prosumer_container()
        elb_controller_idx = create_controlled_electric_boiler(prosumer,
                                                               period=_default_period(prosumer),
                                                               **params)
        elb_controller = prosumer.controller.iloc[elb_controller_idx].object
        
        # First timestep with demand
        elb_controller.t_m_to_deliver = lambda x: (80, 20, [1.5])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        elb_controller.control_step(prosumer)
        
        power_init_kw = 1.5 * 4.186 * (80 - 20)
        expected = [power_init_kw, 1.5, 20, 80, power_init_kw]
        assert elb_controller.step_results == pytest.approx(np.array([expected]), .01)
        
        # Next timestep with zero demand - should not go to zero due to allow_stop=False
        elb_controller.t_m_to_deliver = lambda x: (80, 20, [0])
        elb_controller.time_step(prosumer, "2020-01-01 00:00:01")
        elb_controller.control_step(prosumer)
        
        # Should maintain minimum power of 50 kW instead of going to zero
        result = elb_controller.step_results[0]
        assert result[4] >= 50 - 1e-3, "Power should be at least min_p_kw when allow_stop=False"
        assert result[4] <= 50 + 1e-3, "Power should not exceed min_p_kw significantly"
        


    def test_define_element_with_new_parameters(self):
        """
        Test the creation of a Electric Boiler element with the new parameters.
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'max_p_kw': 100,
                  'min_p_kw': 10,
                  'allow_stop': False,
                  'max_t_out_c': 75}
        
        create_electric_boiler(prosumer, **params)
        assert hasattr(prosumer, "electric_boiler")
        assert len(prosumer.electric_boiler) == 1
        expected_columns = ["name", "max_p_kw", "min_p_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s", "efficiency_percent", "allow_stop", "max_t_out_c", "min_on_time_s", "min_off_time_s", "in_service", "overflow_strategy"]
        expected_values = [None, 100, 10, np.nan, np.nan, 100, False, 75, np.nan, np.nan, True, 'dump_proportional']

        assert sorted(prosumer.electric_boiler.columns) == sorted(expected_columns)
        assert prosumer.electric_boiler.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_electric_boiler_t_in_greater_than_max_t_out(self):
        """Test electric boiler calculation when t_in_c > max_t_out_c."""
        # Test parameters
        mdot_kg_per_s = 1.0  # Initial mass flow
        t_in_c = 70.0        # Input temperature > max_t_out_c
        t_out_c = 80.0      # Requested output temperature
        cp_fluid_kj_per_kgk = 4.18  # Heat capacity of water
        efficiency_percent = 95
        max_p_kw = 500e3
        min_p_kw = 50e3
        p_el_consumed_previous_kw = np.nan
        max_ramp_up_kw_per_s = None
        max_ramp_down_kw_per_s = None
        time_step_s = 3600
        allow_stop = True
        max_t_out_c = 60.0  # Maximum output temperature
        
        # Call the calculation function
        q_fluid_kw, mdot_result, t_in_result, t_out_result, p_el_consumed = _calculate_electric_boiler_temp(
            mdot_kg_per_s, t_out_c, t_in_c, cp_fluid_kj_per_kgk, efficiency_percent,
            max_p_kw, min_p_kw, p_el_consumed_previous_kw, max_ramp_up_kw_per_s,
            max_ramp_down_kw_per_s, time_step_s, allow_stop, max_t_out_c
        )
        
        # When t_in_c > max_t_out_c, we should have:
        # t_out_c = t_in_c, mdot = 0, q_kw = 0, p_el_consumed = 0
        expected_t_out_c = t_in_c  # Should equal input temperature
        expected_mdot = 0.0        # Should be zero
        expected_q_kw = 0.0        # Should be zero
        expected_p_el = 0.0        # Should be zero
        
        np.testing.assert_almost_equal(t_out_result, expected_t_out_c, decimal=6,
                                      err_msg="When t_in_c > max_t_out_c, t_out_c should equal t_in_c")
        
        np.testing.assert_almost_equal(mdot_result, expected_mdot, decimal=6,
                                      err_msg="When t_in_c > max_t_out_c, mass flow should be zero")
        
        np.testing.assert_almost_equal(q_fluid_kw, expected_q_kw, decimal=6,
                                      err_msg="When t_in_c > max_t_out_c, heat output should be zero")
        
        np.testing.assert_almost_equal(p_el_consumed, expected_p_el, decimal=6,
                                      err_msg="When t_in_c > max_t_out_c, electric power should be zero")

    def test_electric_boiler_normal_operation_with_max_t_out_constraint(self):
        """Test electric boiler normal operation where t_out_c > max_t_out_c but t_in_c < max_t_out_c."""
        # Test parameters
        mdot_kg_per_s = 1.0  # Initial mass flow
        t_in_c = 40.0        # Input temperature < max_t_out_c
        t_out_c = 70.0      # Requested output temperature > max_t_out_c
        cp_fluid_kj_per_kgk = 4.18  # Heat capacity of water
        efficiency_percent = 95
        max_p_kw = 500e3
        min_p_kw = 50e3
        p_el_consumed_previous_kw = np.nan
        max_ramp_up_kw_per_s = None
        max_ramp_down_kw_per_s = None
        time_step_s = 3600
        allow_stop = True
        max_t_out_c = 60.0  # Maximum output temperature
        
        # Call the calculation function
        q_fluid_kw, mdot_result, t_in_result, t_out_result, p_el_consumed = _calculate_electric_boiler_temp(
            mdot_kg_per_s, t_out_c, t_in_c, cp_fluid_kj_per_kgk, efficiency_percent,
            max_p_kw, min_p_kw, p_el_consumed_previous_kw, max_ramp_up_kw_per_s,
            max_ramp_down_kw_per_s, time_step_s, allow_stop, max_t_out_c
        )
        
        # When t_out_c > max_t_out_c but t_in_c < max_t_out_c,
        # t_out_c should be constrained to max_t_out_c, but mdot, q_kw, and p_kw should be non-zero
        expected_t_out_c = max_t_out_c  # Should be constrained to max_t_out_c
        
        np.testing.assert_almost_equal(t_out_result, expected_t_out_c, decimal=1,
                                      err_msg="When t_out_c > max_t_out_c but t_in_c < max_t_out_c, t_out_c should be constrained to max_t_out_c")
        
        # Mass flow, heat output, and electric power should be non-zero
        assert mdot_result > 0, "Mass flow should be non-zero when t_in_c < max_t_out_c"
        assert q_fluid_kw > 0, "Heat output should be non-zero when t_in_c < max_t_out_c"
        assert p_el_consumed > 0, "Electric power should be non-zero when t_in_c < max_t_out_c"

    @staticmethod
    def _run_hourly_steps(prosumer, elb_controller, mdot_demands_kg_per_s, n_control_steps=1):
        """
        Drive the controller over consecutive hourly time steps with a demand at 80/20 °C
        (a null demand is sent as a heat demand does: no mass flow and no temperature difference).
        finalize_step is called as in run_timeseries, as it records the on/off state of the boiler.
        n_control_steps > 1 re-runs control_step within a time step, as a reapply does.
        Return the step results of each time step.
        """
        results = []
        for i, mdot_kg_per_s in enumerate(mdot_demands_kg_per_s):
            time = f"2020-01-01 {i:02d}:00:00"
            t_out_c = 80 if mdot_kg_per_s > 0 else 20
            elb_controller.t_m_to_deliver = lambda x, mdot_kg_per_s=mdot_kg_per_s, t_out_c=t_out_c: (t_out_c, 20, [mdot_kg_per_s])
            elb_controller.time_step(prosumer, time)
            for _ in range(n_control_steps):
                elb_controller.control_step(prosumer)
            elb_controller.finalize_step(prosumer, time)
            results.append(elb_controller.step_results[0].copy())
        return np.array(results)

    @staticmethod
    def _hourly_controller(**params):
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 3600,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 23:59:59",
                               timezone="utc")
        elb_params = {'max_p_kw': 500,
                      'min_p_kw': 20,
                      'overflow_strategy': 'cap'}
        elb_params.update(params)
        elb_controller_index = create_controlled_electric_boiler(prosumer, period=period, **elb_params)
        return prosumer, prosumer.controller.iloc[elb_controller_index].object

    @pytest.mark.parametrize("n_control_steps", [1, 2])
    def test_controller_run_control_min_on_time(self, n_control_steps):
        """
        Once started, the boiler keeps running at min_p_kw when the demand stops, until it has run for min_on_time_s
        """
        prosumer, elb_controller = self._hourly_controller(min_on_time_s=3 * 3600)
        results = self._run_hourly_steps(prosumer, elb_controller, [0, .2, 0, 0, 0, 0], n_control_steps)

        q_on_kw = .2 * 4.186 * 60
        # Started at 01:00: still locked on at 02:00 and 03:00, free to stop at 04:00
        assert results[:, 0] == pytest.approx([0, q_on_kw, 20, 20, 0, 0], rel=.01)
        # The electrical power follows the delivered heat (100 % efficiency)
        assert results[:, 4] == pytest.approx(results[:, 0], rel=1e-6)
        # Without demand, the held power is carried with the temperature difference of the previous time step
        assert results[2:4, 3] - results[2:4, 2] == pytest.approx([60, 60], rel=1e-3)

    @pytest.mark.parametrize("n_control_steps", [1, 2])
    def test_controller_run_control_min_off_time(self, n_control_steps):
        """
        Once stopped, the boiler does not restart when the demand comes back, until it has been stopped for min_off_time_s
        """
        prosumer, elb_controller = self._hourly_controller(min_off_time_s=3 * 3600)
        results = self._run_hourly_steps(prosumer, elb_controller, [.2, 0, .2, .2, .2, .2], n_control_steps)

        q_on_kw = .2 * 4.186 * 60
        # Stopped at 01:00: still locked off at 02:00 and 03:00, free to restart at 04:00
        assert results[:, 0] == pytest.approx([q_on_kw, 0, 0, 0, q_on_kw, q_on_kw], rel=.01)
        # A locked-off boiler delivers no mass flow, consumes no electricity and does not heat the fluid
        locked = results[2:4]
        assert locked[:, 1] == pytest.approx([0, 0])
        assert locked[:, 3] == pytest.approx(locked[:, 2])
        assert locked[:, 4] == pytest.approx([0, 0])

    def test_controller_run_control_min_on_and_off_time(self):
        """
        With a demand alternating every hour, both durations are respected:
        every run lasts at least min_on_time_s and every stop at least min_off_time_s
        """
        prosumer, elb_controller = self._hourly_controller(min_on_time_s=2 * 3600, min_off_time_s=2 * 3600)
        results = self._run_hourly_steps(prosumer, elb_controller, [0, .2, 0, .2, 0, .2, 0, .2, 0, .2])

        q_on_kw = .2 * 4.186 * 60
        # Started at 01:00, stopped at 04:00, restarted at 07:00
        assert results[:, 0] == pytest.approx([0, q_on_kw, 20, q_on_kw, 0, 0, 0, q_on_kw, 20, q_on_kw], rel=.01)

    def test_controller_run_control_min_times_default(self):
        """
        Without min_on_time_s and min_off_time_s, the boiler follows the demand immediately
        """
        prosumer, elb_controller = self._hourly_controller()
        results = self._run_hourly_steps(prosumer, elb_controller, [.2, 0, .2, 0])

        q_on_kw = .2 * 4.186 * 60
        assert results[:, 0] == pytest.approx([q_on_kw, 0, q_on_kw, 0], rel=.01)

    @pytest.mark.parametrize("mdot_demands_kg_per_s, q_expected_kw", [
        # Off at the first time step: free to start at the next one
        ([0, .2, 0], [0, .2 * 4.186 * 60, 20]),
        # On at the first time step: free to stop at the next one
        ([.2, 0, .2], [.2 * 4.186 * 60, 0, 0]),
    ])
    def test_controller_run_control_min_times_first_step(self, mdot_demands_kg_per_s, q_expected_kw):
        """
        The state at the first time step of a run is assumed to have lasted long enough:
        only a start or a stop during the run locks the boiler
        """
        prosumer, elb_controller = self._hourly_controller(min_on_time_s=6 * 3600, min_off_time_s=6 * 3600)
        results = self._run_hourly_steps(prosumer, elb_controller, mdot_demands_kg_per_s)

        assert results[:, 0] == pytest.approx(q_expected_kw, rel=.01)

    @pytest.mark.parametrize("min_p_kw", [np.nan, 0])
    def test_define_controller_min_on_time_without_min_p_kw(self, min_p_kw):
        """
        min_on_time_s needs a positive min_p_kw: it is the power that holds the boiler on
        """
        with pytest.raises(ValueError, match="min_on_time_s"):
            self._hourly_controller(min_p_kw=min_p_kw, min_on_time_s=3600)

    def test_controller_run_control_allow_stop_false_without_demand(self):
        """
        allow_stop=False with a null demand sent as a heat demand does (no mass flow, no temperature difference):
        the boiler is held at min_p_kw with the temperature difference of the previous time step
        """
        prosumer, elb_controller = self._hourly_controller(allow_stop=False)
        results = self._run_hourly_steps(prosumer, elb_controller, [.2, 0])

        assert results[1, 0] == pytest.approx(20, rel=1e-3)
        assert results[1, 3] - results[1, 2] == pytest.approx(60, rel=1e-3)
        assert np.isfinite(results).all()

@pytest.mark.parametrize("setpoint, expected_p_kw", [(np.nan, 500), (-1, 500), (200, 200), (900, 500), (0, 0)])
def test_controller_max_p_kw_setpoint_caps_the_power(setpoint, expected_p_kw):
    """A mapped ``max_p_kw_setpoint`` lowers the power for the step; negative or NaN = no cap."""
    prosumer = create_empty_prosumer_container()
    idx = create_controlled_electric_boiler(prosumer, period=_default_period(prosumer), max_p_kw=500, order=0)
    controller = prosumer.controller.iloc[idx].object
    controller.t_m_to_deliver = lambda x: (80, 20, [4])
    controller.time_step(prosumer, "2020-01-01 00:00:00")
    controller.inputs[0, controller.input_columns.index("max_p_kw_setpoint")] = setpoint
    controller.control_step(prosumer)
    assert controller.step_results[0][4] == pytest.approx(expected_p_kw, abs=1e-2)
