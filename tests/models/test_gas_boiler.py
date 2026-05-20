import pytest
import numpy as np
from pandaprosumer import create_empty_prosumer_container, create_period, create_gas_boiler, create_controlled_gas_boiler
from pandaprosumer.controller.models.gas_boiler import _calculate_gas_boiler_temp
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


def _default_argument():
    return {'max_q_kw': 100,
            'heating_value_kj_per_kg': 20e3}


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

        create_gas_boiler(prosumer, **_default_argument())
        assert hasattr(prosumer, "gas_boiler")
        assert len(prosumer.gas_boiler) == 1
        expected_columns = ["name", "max_q_kw", "min_q_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s", "heating_value_kj_per_kg", "efficiency_percent", "allow_stop", "max_t_out_c", "in_service", "overflow_strategy"]
        expected_values = [None, 100, np.nan, np.nan, np.nan, 20e3, 100, True, np.nan, True, 'dump_proportional']

        assert sorted(prosumer.gas_boiler.columns) == sorted(expected_columns)

        assert prosumer.gas_boiler.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_with_parameters(self):
        """
        Test the creation of a Gas Boiler element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'max_q_kw': 250,
                  'min_q_kw': 20,
                  'max_ramp_up_kw_per_s': 0.02,
                  'max_ramp_down_kw_per_s': 0.03,
                  'efficiency_percent': 75,
                  'heating_value_kj_per_kg': 18e3,
                  'allow_stop': False,
                  'max_t_out_c': 90.0}

        gsb_idx = create_gas_boiler(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "gas_boiler")
        assert len(prosumer.gas_boiler) == 1
        assert gsb_idx == 4
        assert prosumer.gas_boiler.index[0] == gsb_idx

        expected_columns = ["name", "max_q_kw", "min_q_kw", "max_ramp_up_kw_per_s", "max_ramp_down_kw_per_s", "heating_value_kj_per_kg", "efficiency_percent", "allow_stop", "max_t_out_c", "in_service", "overflow_strategy", "custom"]
        expected_values = ['foo', 250, 20, 0.02, 0.03, 18e3, 75, False, 90.0, False, 'dump_proportional', 'test']
        assert sorted(prosumer.gas_boiler.columns) == sorted(expected_columns)
        assert prosumer.gas_boiler.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_controller(self):
        """
        Test the creation of a Gas Boiler controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_gas_boiler(prosumer, period=_default_period(prosumer), **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of the Gas Boiler controller"""
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **_default_argument())
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
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **_default_argument())
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object

        gsb_controller.t_m_to_deliver = lambda x: (0, 0, [0])

        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        expected = [0, 0, 0, 0, 0]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_demand(self):
        """
        Test the Gas Boiler run control method with a demand.
        Expect the demand to be delivered.
        """

        params = {'max_q_kw': 500,
                  'heating_value_kj_per_kg': 20e3}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object

        gsb_controller.t_m_to_deliver = lambda x: (80, 20, [1.5])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        expected = [1.5 * 4.186 * (80 - 20), 1.5, 20, 80, 1.5 * 4.186 * (80 - 20) / 20e3]
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
        t_hot_c = 80
        t_cold_c = 20
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        gsb_controller.t_m_to_deliver = lambda x: (t_hot_c, t_cold_c, [4])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        q_expected = params['max_q_kw']
        t_expected_out_c = t_hot_c
        mdot_expected_kg_per_s = q_expected / ((t_expected_out_c - t_cold_c) * 4.186)
        mdot_fuel_expected_kg_per_s = q_expected / params['heating_value_kj_per_kg'] / (params['efficiency_percent'] / 100)
        expected = [q_expected, mdot_expected_kg_per_s, t_cold_c, t_expected_out_c, mdot_fuel_expected_kg_per_s]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_expected_kg_per_s, .01)}]

    def test_controller_run_control_outrange_3demands(self):
        """
        Test the Gaz Boiler run control method with 3 demands, the total being higher than the maximum power.
        Expect the demand to be delivered with the maximum power.
        Dispatch according to the merit order.
        """
        params = {'max_q_kw': 500,
                  'efficiency_percent': 50,
                  'heating_value_kj_per_kg': 20e3}
        t_hot_c = 80
        t_cold_c = 20
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        gsb_controller.t_m_to_deliver = lambda x: (t_hot_c, t_cold_c, [3, 2, 4])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        q_expected = params['max_q_kw']
        t_expected_out_c = t_hot_c
        mdot_expected_kg_per_s = q_expected / ((t_expected_out_c - t_cold_c) * 4.186)
        mdot_fuel_expected_kg_per_s = q_expected / params['heating_value_kj_per_kg'] / (params['efficiency_percent'] / 100)
        expected = [q_expected, mdot_expected_kg_per_s, t_cold_c, t_expected_out_c, mdot_fuel_expected_kg_per_s]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [
            {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
             FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_expected_kg_per_s, .01)},
            {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
             FluidMixMapping.MASS_FLOW_KEY: 0.},
            {FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_expected_out_c, .01),
             FluidMixMapping.MASS_FLOW_KEY: 0.}
        ]

    def test_controller_run_control_ramp_speed(self):
        """
        Test the Gas Boiler run control method with a demand with a constraint on the ramp up and ramp down speeds.
        """
        max_ramp_up_kw_per_s = 100
        max_ramp_down_kw_per_s = 50
        resol_s = 1
        lhv = 20e3
        params = {'max_q_kw': 500,
                  'efficiency_percent': 100,
                  'max_ramp_up_kw_per_s': max_ramp_up_kw_per_s,
                  'max_ramp_down_kw_per_s': max_ramp_down_kw_per_s,
                  'heating_value_kj_per_kg': lhv,
                  'overflow_strategy': 'cap'}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object

        t_high_c = 80
        t_low_c = 20
        mdot_init = 1.5

        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_init])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        power_init_kw = mdot_init * 4.186 * (t_high_c - t_low_c)
        expected = [power_init_kw, mdot_init, t_low_c, t_high_c, power_init_kw / lhv]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: t_high_c,
                                                              FluidMixMapping.MASS_FLOW_KEY: mdot_init}]
        
        # Increase the heat demand faster than the max ramp up speed
        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [3])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:01")
        gsb_controller.control_step(prosumer)

        power_up_kw = power_init_kw + max_ramp_up_kw_per_s * resol_s
        expected = [power_up_kw, 1.8985759, t_low_c, t_high_c, power_up_kw / lhv]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: t_high_c,
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(1.8985759042371968)}]
        
        # Decrease the heat demand faster than the max ramp down speed
        mdot_demand_kg_per_s = 1.
        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_demand_kg_per_s])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:02")
        gsb_controller.control_step(prosumer)
        
        # The mass flow is limited by the demand, so the boiler's output temperature is recalculated so that the delivered power is the minimum allowed.
        power_down_kw = power_up_kw - max_ramp_down_kw_per_s * resol_s
        t_high_recalculated_c = t_low_c + power_down_kw / (mdot_demand_kg_per_s * 4.186)
        mdot_fuel_expected_kg_per_s = power_down_kw / (lhv * (params['efficiency_percent'] / 100))
        expected = [power_down_kw, mdot_demand_kg_per_s, t_low_c, t_high_recalculated_c, mdot_fuel_expected_kg_per_s]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_high_recalculated_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_demand_kg_per_s)}]
        
    def test_controller_run_control_min_power(self):
        """
        Test the Gas Boiler run control method with a demand below the minimum boiler power.
        """
        min_power_kw = 20
        max_ramp_up_kw_per_s = 100
        max_ramp_down_kw_per_s = 50
        lhv = 20e3
        params = {'max_q_kw': 500,
                  'min_q_kw': min_power_kw,
                  'efficiency_percent': 100,
                  'max_ramp_up_kw_per_s': max_ramp_up_kw_per_s,
                  'max_ramp_down_kw_per_s': max_ramp_down_kw_per_s,
                  'heating_value_kj_per_kg': lhv,
                  'overflow_strategy': 'cap'}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        
        t_high_c = 80
        t_low_c = 20
        mdot_dmd = 0.05

        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_dmd])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        # The mass flow is limited by the boiler's minimum power, so the boiler's output temperature is recalculated so that the delivered power is the minimum allowed.
        t_high_recalculated_c = t_low_c + min_power_kw / (mdot_dmd * 4.186)
        mdot_fuel_expected_kg_per_s = min_power_kw / (lhv * (params['efficiency_percent'] / 100))
        expected = [min_power_kw, mdot_dmd, t_low_c, t_high_recalculated_c, mdot_fuel_expected_kg_per_s]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_high_recalculated_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_dmd, .01)}]

    def test_controller_run_control_allow_stop_false(self):
        """
        Test the Gas Boiler run control method with allow_stop=False, preventing the boiler from stopping.
        """
        min_power_kw = 20
        lhv = 20e3
        params = {'max_q_kw': 500,
                  'min_q_kw': min_power_kw,
                  'efficiency_percent': 100,
                  'heating_value_kj_per_kg': lhv,
                  'allow_stop': False,
                  'overflow_strategy': 'cap'}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        
        t_high_c = 80
        t_low_c = 20
        mdot_dmd = 0.01  # Very low demand that would normally stop the boiler

        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_dmd])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        # With allow_stop=False, the boiler should maintain minimum power even when demand is very low
        t_high_recalculated_c = t_low_c + min_power_kw / (mdot_dmd * 4.186)
        mdot_fuel_expected_kg_per_s = min_power_kw / (lhv * (params['efficiency_percent'] / 100))
        expected = [min_power_kw, mdot_dmd, t_low_c, t_high_recalculated_c, mdot_fuel_expected_kg_per_s]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)

    def test_controller_run_control_max_t_out_c(self):
        """
        Test the Gas Boiler run control method with max_t_out_c constraint.
        """
        lhv = 20e3
        max_temp_c = 70  # Maximum output temperature constraint
        params = {'max_q_kw': 500,
                  'efficiency_percent': 100,
                  'heating_value_kj_per_kg': lhv,
                  'max_t_out_c': max_temp_c,
                  'overflow_strategy': 'cap'}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object

        t_high_c = 80  # Requested temperature higher than max constraint
        t_low_c = 20
        mdot_dmd = 1.5

        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_dmd])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        # The output temperature should be limited to max_t_out_c
        # After mass/energy balance adjustment, the temperature constraint is reapplied
        # and power is recalculated to be consistent with the constrained temperature
        q_kw = mdot_dmd * 4.186 * (max_temp_c - t_low_c)  # Power with constrained temperature
        mdot_fuel_expected_kg_per_s = q_kw / lhv
        expected = [q_kw, mdot_dmd, t_low_c, max_temp_c, mdot_fuel_expected_kg_per_s]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(max_temp_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_dmd, .01)}]

    @pytest.mark.parametrize("min_power_kw, max_temp_c, t_high_c, t_low_c, mdot_dmd", [
        # Base case: moderate temperature constraint, low demand
        (20, 70, 80, 20, 0.05),
        # Edge case: higher minimum power
        (30, 70, 80, 20, 0.05),
        # Edge case: lower temperature constraint
        (20, 60, 80, 20, 0.05),
        # Edge case: different temperature difference
        (20, 70, 90, 30, 0.05),
        # Edge case: very low demand
        (20, 70, 80, 20, 0.01),
    ])
    def test_controller_run_control_allow_stop_false_with_max_t_out_c_parametrized(
            self, min_power_kw, max_temp_c, t_high_c, t_low_c, mdot_dmd):
        """
        Parametrized test for Gas Boiler with allow_stop=False and max_t_out_c constraint.
        Tests various combinations of minimum power, temperature constraints, and demand levels.
        """
        lhv = 20e3
        
        params = {'max_q_kw': 500,
                  'min_q_kw': min_power_kw,
                  'efficiency_percent': 100,
                  'heating_value_kj_per_kg': lhv,
                  'allow_stop': False,  # Boiler cannot stop
                  'max_t_out_c': max_temp_c}
        
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        
        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_dmd])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)
        
        # With allow_stop=False, the boiler should maintain minimum power even when demand is low
        # and temperature is constrained. This is achieved by increasing mass flow.
        cp_fluid = 4.186  # kJ/kgK (approximate for water)
        mdot_delivered_expected = min_power_kw / (cp_fluid * (max_temp_c - t_low_c))
        mdot_fuel_expected_kg_per_s = min_power_kw / lhv
        
        result = gsb_controller.step_results[0]
        q_kw = result[0]
        mdot_delivered = result[1]
        t_out_c = result[3]
        
        # Verify key constraints
        assert q_kw >= min_power_kw - 1e-2, f"Power {q_kw} kW should be at least {min_power_kw} kW"
        assert t_out_c <= max_temp_c + 1e-2, f"Temperature {t_out_c} °C should not exceed {max_temp_c} °C"
        assert mdot_delivered > mdot_dmd, f"Mass flow should be increased above demand"
        
        # Verify expected values with reasonable tolerance
        assert q_kw == pytest.approx(min_power_kw, rel=1e-2)
        assert mdot_delivered == pytest.approx(mdot_delivered_expected, rel=1e-2)
        assert t_out_c == pytest.approx(max_temp_c, rel=1e-2)
        
    def test_controller_run_control_allow_stop_false_with_max_t_out_c(self):
        """
        Test the Gas Boiler run control method with allow_stop=False and max_t_out_c constraint.
        This ensures that when temperature is constrained, the boiler maintains minimum power
        by increasing mass flow rather than dropping below min_q_kw.
        """
        min_power_kw = 20
        max_temp_c = 70  # Maximum output temperature constraint
        lhv = 20e3
        
        params = {'max_q_kw': 500,
                  'min_q_kw': min_power_kw,
                  'efficiency_percent': 100,
                  'heating_value_kj_per_kg': lhv,
                  'allow_stop': False,  # Boiler cannot stop
                  'max_t_out_c': max_temp_c}
        
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        
        t_high_c = 80  # Requested temperature higher than max constraint
        t_low_c = 20
        mdot_dmd = 0.05  # Low demand that would normally result in power below min_q_kw
        
        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_dmd])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)
        
        # With allow_stop=False, the boiler should maintain minimum power even when demand is low
        # and temperature is constrained. This is achieved by increasing mass flow.
        cp_fluid = 4.186  # kJ/kgK (approximate for water)
        mdot_delivered_expected = min_power_kw / (cp_fluid * (max_temp_c - t_low_c))
        mdot_fuel_expected_kg_per_s = min_power_kw / lhv
        
        expected = [min_power_kw, mdot_delivered_expected, t_low_c, max_temp_c, mdot_fuel_expected_kg_per_s]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(max_temp_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_delivered_expected, .01)}]

    def test_controller_run_control_max_t_out_c_at_boundary(self):
        """
        Test edge case where requested temperature equals max_t_out_c constraint.
        This should not trigger the temperature constraint logic.
        """
        lhv = 20e3
        max_temp_c = 70  # Maximum output temperature constraint
        params = {'max_q_kw': 500,
                  'efficiency_percent': 100,
                  'heating_value_kj_per_kg': lhv,
                  'max_t_out_c': max_temp_c}
        prosumer = create_empty_prosumer_container()
        gsb_controller_index = create_controlled_gas_boiler(prosumer,
                                                            period=_default_period(prosumer),
                                                            **params)
        gsb_controller = prosumer.controller.iloc[gsb_controller_index].object
        
        t_high_c = 70  # Requested temperature exactly at max constraint
        t_low_c = 20
        mdot_dmd = 1.5

        gsb_controller.t_m_to_deliver = lambda x: (t_high_c, t_low_c, [mdot_dmd])
        gsb_controller.time_step(prosumer, "2020-01-01 00:00:00")
        gsb_controller.control_step(prosumer)

        # Should work normally without triggering temperature constraint
        q_kw = mdot_dmd * 4.186 * (t_high_c - t_low_c)
        mdot_fuel_expected_kg_per_s = q_kw / lhv
        expected = [q_kw, mdot_dmd, t_low_c, t_high_c, mdot_fuel_expected_kg_per_s]
        assert gsb_controller.step_results == pytest.approx(np.array([expected]), .01)
        assert gsb_controller.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: pytest.approx(t_high_c, .01),
                                                              FluidMixMapping.MASS_FLOW_KEY: pytest.approx(mdot_dmd, .01)}]

    def test_gas_boiler_t_in_greater_than_max_t_out(self):
        """Test gas boiler calculation when t_in_c > max_t_out_c."""
        # Test parameters
        mdot_kg_per_s = 1.0  # Initial mass flow
        t_in_c = 70.0        # Input temperature > max_t_out_c
        t_out_c = 80.0      # Requested output temperature
        cp_fluid_kj_per_kgk = 4.18  # Heat capacity of water
        heating_value_kj_per_kg = 50000
        efficiency_percent = 90
        max_q_kw = 1000e3
        min_q_kw = 100e3
        q_previous_kw = np.nan
        delta_t_previous_c = np.nan
        max_ramp_up_kw_per_s = None
        max_ramp_down_kw_per_s = None
        time_step_s = 3600
        allow_stop = True
        max_t_out_c = 60.0  # Maximum output temperature
        
        # Call the calculation function
        q_fluid_kw, mdot_result, t_in_result, t_out_result, mdot_fuel = _calculate_gas_boiler_temp(
            mdot_kg_per_s, t_out_c, t_in_c, cp_fluid_kj_per_kgk, heating_value_kj_per_kg,
            efficiency_percent, max_q_kw, min_q_kw, q_previous_kw, delta_t_previous_c,
            max_ramp_up_kw_per_s, max_ramp_down_kw_per_s, time_step_s, allow_stop, max_t_out_c
        )
        
        # When t_in_c > max_t_out_c, we should have:
        # t_out_c = t_in_c, mdot = 0, q_kw = 0
        expected_t_out_c = t_in_c  # Should equal input temperature
        expected_mdot = 0.0        # Should be zero
        expected_q_kw = 0.0        # Should be zero
        
        np.testing.assert_almost_equal(t_out_result, expected_t_out_c, decimal=6,
                                      err_msg="When t_in_c > max_t_out_c, t_out_c should equal t_in_c")
        
        np.testing.assert_almost_equal(mdot_result, expected_mdot, decimal=6,
                                      err_msg="When t_in_c > max_t_out_c, mass flow should be zero")
        
        np.testing.assert_almost_equal(q_fluid_kw, expected_q_kw, decimal=6,
                                      err_msg="When t_in_c > max_t_out_c, heat output should be zero")

    def test_gas_boiler_normal_operation_with_max_t_out_constraint(self):
        """Test gas boiler normal operation where t_out_c > max_t_out_c but t_in_c < max_t_out_c."""
        # Test parameters
        mdot_kg_per_s = 1.0  # Initial mass flow
        t_in_c = 40.0        # Input temperature < max_t_out_c
        t_out_c = 70.0      # Requested output temperature > max_t_out_c
        cp_fluid_kj_per_kgk = 4.18  # Heat capacity of water
        heating_value_kj_per_kg = 50000
        efficiency_percent = 90
        max_q_kw = 1000e3
        min_q_kw = 100e3
        q_previous_kw = np.nan
        delta_t_previous_c = np.nan
        max_ramp_up_kw_per_s = None
        max_ramp_down_kw_per_s = None
        time_step_s = 3600
        allow_stop = True
        max_t_out_c = 60.0  # Maximum output temperature
        
        # Call the calculation function
        q_fluid_kw, mdot_result, t_in_result, t_out_result, mdot_fuel = _calculate_gas_boiler_temp(
            mdot_kg_per_s, t_out_c, t_in_c, cp_fluid_kj_per_kgk, heating_value_kj_per_kg,
            efficiency_percent, max_q_kw, min_q_kw, q_previous_kw, delta_t_previous_c,
            max_ramp_up_kw_per_s, max_ramp_down_kw_per_s, time_step_s, allow_stop, max_t_out_c
        )
        
        # When t_out_c > max_t_out_c but t_in_c < max_t_out_c,
        # t_out_c should be constrained to max_t_out_c, but mdot and q_kw should be non-zero
        expected_t_out_c = max_t_out_c  # Should be constrained to max_t_out_c
        
        np.testing.assert_almost_equal(t_out_result, expected_t_out_c, decimal=1,
                                      err_msg="When t_out_c > max_t_out_c but t_in_c < max_t_out_c, t_out_c should be constrained to max_t_out_c")
        
        # Mass flow and heat output should be non-zero (since we can still deliver heat at constrained temperature)
        assert mdot_result > 0, "Mass flow should be non-zero when t_in_c < max_t_out_c"
        assert q_fluid_kw > 0, "Heat output should be non-zero when t_in_c < max_t_out_c"
