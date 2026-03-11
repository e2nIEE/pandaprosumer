import pytest
import numpy as np
import pandas as pd
from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_heat_storage, create_heat_storage
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


def _default_argument():
    return {"e_capacity_kwh": 100}


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestSimpleHeatStorage:
    """
    Tests the functionalities of a SHS element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a  heat storage element in a prosumer container with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        shs_params = {}

        create_heat_storage(prosumer, **shs_params)
        assert hasattr(prosumer, "heat_storage")
        assert len(prosumer.heat_storage) == 1

        expected_columns = [
            'name', 'e_capacity_kwh', 'in_service',
            'capacity_kg', 't_tank_init_c', 'min_temp_c', 'max_temp_c',
            'u_w_per_m2k', 'area_wall_m2', 't_ext_c'
        ]
        assert sorted(prosumer.heat_storage.columns) == sorted(expected_columns)
        row = prosumer.heat_storage.iloc[0]
        assert row['name'] is None
        assert row['in_service'] == True or row['in_service'] is True
        assert row['e_capacity_kwh'] == 0 or (isinstance(row['e_capacity_kwh'], (int, float)) and np.isclose(row['e_capacity_kwh'], 0))
        for col in ['capacity_kg', 't_tank_init_c', 'min_temp_c', 'max_temp_c',
                    'u_w_per_m2k', 'area_wall_m2', 't_ext_c']:
            assert col in row.index and (pd.isna(row[col]) or row[col] is None)

    def test_define_element_param(self):
        """
        Test the creation of a  heat storage element in a prosumer container with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        shs_params = {"e_capacity_kwh": 100}

        shs_idx = create_heat_storage(prosumer, name='foo', in_service=False, custom='test', index=4, **shs_params)
        assert hasattr(prosumer, "heat_storage")
        assert len(prosumer.heat_storage) == 1
        assert shs_idx == 4
        assert prosumer.heat_storage.index[0] == shs_idx

        expected_columns = [
            'name', 'e_capacity_kwh', 'in_service', 'custom',
            'capacity_kg', 't_tank_init_c', 'min_temp_c', 'max_temp_c',
            'u_w_per_m2k', 'area_wall_m2', 't_ext_c'
        ]
        assert sorted(prosumer.heat_storage.columns) == sorted(expected_columns)
        row = prosumer.heat_storage.iloc[0]
        assert row['name'] == 'foo' and row['in_service'] == False and row['e_capacity_kwh'] == 100 and row['custom'] == 'test'

    def test_define_controller(self):
        """
        Test the creation of a  heat storage controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_heat_storage(prosumer,
                                       order=0,
                                       period=_default_period(prosumer),
                                       **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        """
        Check that the input and result columns of the  heat storage controller are the one expected
        """
        prosumer = create_empty_prosumer_container()
        shs_controller_idx = create_controlled_heat_storage(prosumer,
                                                            order=0,
                                                            period=_default_period(prosumer),
                                                            **_default_argument())
        shs_controller = prosumer.controller.iloc[shs_controller_idx].object

        input_columns_expected = ["q_received_kw"]
        result_columns_expected = ["soc", "t_tank_c", "q_ch_kw", "q_dch_kw", "q_delivered_kw", "mdot_ch_kg_per_s", "t_ch_in_c", "t_ch_out_c", "mdot_dch_kg_per_s", "t_dch_in_c", "t_dch_out_c"]

        assert shs_controller.input_columns == input_columns_expected
        assert shs_controller.result_columns == result_columns_expected

    def test_controller_run_control_no_demand(self):
        """
        Test the control step of the controller with no demand
        """
        prosumer = create_empty_prosumer_container()
        shs_controller_idx = create_controlled_heat_storage(prosumer,
                                                            order=0,
                                                            period=_default_period(prosumer),
                                                            **_default_argument())
        shs_controller = prosumer.controller.iloc[shs_controller_idx].object

        q_in_kw = 0
        q_out_kw = 0
        shs_controller.inputs = np.array([[q_in_kw]])
        shs_controller.q_to_deliver_kw = lambda x: q_out_kw
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        soc = (q_in_kw - q_out_kw) * shs_controller.resol / 3600 / 100
        t_tank_c = 40.0  # default temperature when not in fluid mix mode
        q_ch_kw = 0.0  # no charging in power-only mode in these test cases
        t_received_out_c = t_tank_c  # in power-only mode, t_received_out_c = t_tank_c
        # Additional outputs for power-only mode (all NaN or 0)
        q_charge_kw = 0.0
        q_discharge_kw = q_out_kw  # discharge power equals delivered power
        t_charge_in_c = t_tank_c  # Default to tank temp when not charging
        t_charge_out_c = t_tank_c  # Default to tank temp when not charging
        t_discharge_in_c = t_tank_c  # Default to tank temp when not discharging
        t_discharge_out_c = t_discharge_in_c  # When no discharge, match input temp
        mdot_charge_kg_per_s = 0.0
        mdot_discharge_kg_per_s = 0.0
        # Check values with new column order (no NaN values)
        assert shs_controller.step_results[0, 0] == pytest.approx(soc)  # soc
        assert shs_controller.step_results[0, 1] == pytest.approx(t_tank_c)  # t_tank_c
        assert shs_controller.step_results[0, 2] == pytest.approx(q_ch_kw)  # q_ch_kw
        assert shs_controller.step_results[0, 3] == pytest.approx(q_discharge_kw)  # q_dch_kw
        assert shs_controller.step_results[0, 4] == pytest.approx(q_discharge_kw)  # q_delivered_kw (equals q_dch_kw in power-only)
        assert shs_controller.step_results[0, 5] == pytest.approx(mdot_charge_kg_per_s)  # mdot_ch_kg_per_s
        # Charge temperatures (should be tank temp when not charging)
        assert shs_controller.step_results[0, 6] == pytest.approx(t_charge_in_c)  # t_ch_in_c
        assert shs_controller.step_results[0, 7] == pytest.approx(t_charge_out_c)  # t_ch_out_c
        assert shs_controller.step_results[0, 8] == pytest.approx(mdot_discharge_kg_per_s)  # mdot_dch_kg_per_s
        # Discharge temperatures (should be tank temp when not discharging)
        assert shs_controller.step_results[0, 9] == pytest.approx(t_discharge_in_c)  # t_dch_in_c
        assert shs_controller.step_results[0, 10] == pytest.approx(t_discharge_out_c)  # t_dch_out_c

    def test_controller_run_control_charge(self):
        """
        Test the control step of the controller with no demand
        """
        prosumer = create_empty_prosumer_container()
        shs_controller_idx = create_controlled_heat_storage(prosumer,
                                                            order=0,
                                                            period=_default_period(prosumer),
                                                            **_default_argument())
        shs_controller = prosumer.controller.iloc[shs_controller_idx].object

        q_in_kw = 10
        q_out_kw = 0
        shs_controller.inputs = np.array([[q_in_kw]])
        shs_controller.q_to_deliver_kw = lambda x: q_out_kw
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        soc = (q_in_kw - q_out_kw) * shs_controller.resol / 3600 / 100
        t_tank_c = 40.0  # default temperature when not in fluid mix mode
        q_ch_kw = q_in_kw  # charging power equals input power
        t_received_out_c = t_tank_c  # in power-only mode, t_received_out_c = t_tank_c
        # Additional outputs for power-only mode (all NaN or 0)
        q_charge_kw = q_ch_kw  # charge power equals charging power
        q_discharge_kw = 0.0  # no discharge when charging
        t_charge_in_c = t_tank_c  # charge temperature equals tank temperature in power-only mode
        t_charge_out_c = t_tank_c  # charge temperature equals tank temperature in power-only mode
        t_discharge_in_c = t_tank_c  # Default to tank temp when not discharging
        t_discharge_out_c = t_discharge_in_c  # When no discharge, match input temp
        mdot_charge_kg_per_s = 0.0  # no mass flow info in power-only mode
        mdot_discharge_kg_per_s = 0.0  # no mass flow info in power-only mode
        
        # Check values with new column order (no NaN values)
        assert shs_controller.step_results[0, 0] == pytest.approx(soc)  # soc
        assert shs_controller.step_results[0, 1] == pytest.approx(t_tank_c)  # t_tank_c
        assert shs_controller.step_results[0, 2] == pytest.approx(q_ch_kw)  # q_ch_kw
        assert shs_controller.step_results[0, 3] == pytest.approx(q_discharge_kw)  # q_dch_kw
        assert shs_controller.step_results[0, 4] == pytest.approx(q_discharge_kw)  # q_delivered_kw
        assert shs_controller.step_results[0, 5] == pytest.approx(mdot_charge_kg_per_s)  # mdot_ch_kg_per_s
        # Charge temperatures (should be tank temp when charging)
        assert shs_controller.step_results[0, 6] == pytest.approx(t_charge_in_c)  # t_ch_in_c
        assert shs_controller.step_results[0, 7] == pytest.approx(t_charge_out_c)  # t_ch_out_c
        assert shs_controller.step_results[0, 8] == pytest.approx(mdot_discharge_kg_per_s)  # mdot_dch_kg_per_s
        # Discharge temperatures (should be tank temp when not discharging)
        assert shs_controller.step_results[0, 9] == pytest.approx(t_discharge_in_c)  # t_dch_in_c
        assert shs_controller.step_results[0, 10] == pytest.approx(t_discharge_out_c)  # t_dch_out_c

    def test_controller_run_control_discharge(self):
        """
        Test the control step of the controller with no demand
        """
        prosumer = create_empty_prosumer_container()
        shs_controller_idx = create_controlled_heat_storage(prosumer,
                                                            order=0,
                                                            period=_default_period(prosumer),
                                                            init_soc=0.5,
                                                            **_default_argument())
        shs_controller = prosumer.controller.iloc[shs_controller_idx].object

        q_in_kw = 10
        q_out_kw = 100
        shs_controller.inputs = np.array([[q_in_kw]])
        shs_controller.q_to_deliver_kw = lambda x: q_out_kw
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        soc = 0.5 + (q_in_kw - q_out_kw) * shs_controller.resol / 3600 / 100
        t_tank_c = 40.0  # default temperature when not in fluid mix mode
        q_ch_kw = 0.0  # no charging when discharging
        t_received_out_c = t_tank_c  # in power-only mode, t_received_out_c = t_tank_c
        # Additional outputs for power-only mode
        q_charge_kw = 0.0  # no charging when discharging
        q_discharge_kw = q_out_kw  # discharge power equals delivered power
        t_charge_in_c = t_tank_c  # Default to tank temp when not charging
        t_charge_out_c = t_tank_c  # Default to tank temp when not charging
        t_discharge_in_c = t_tank_c  # discharge temperature equals tank temperature in power-only mode
        t_discharge_out_c = t_tank_c  # discharge temperature equals tank temperature in power-only mode
        mdot_charge_kg_per_s = 0.0  # no mass flow info in power-only mode
        mdot_discharge_kg_per_s = 0.0  # no mass flow info in power-only mode
        
        # Check values with new column order (no NaN values)
        assert shs_controller.step_results[0, 0] == pytest.approx(soc)  # soc
        assert shs_controller.step_results[0, 1] == pytest.approx(t_tank_c)  # t_tank_c
        assert shs_controller.step_results[0, 2] == pytest.approx(q_ch_kw)  # q_ch_kw
        assert shs_controller.step_results[0, 3] == pytest.approx(q_discharge_kw)  # q_dch_kw
        assert shs_controller.step_results[0, 4] == pytest.approx(q_discharge_kw)  # q_delivered_kw
        assert shs_controller.step_results[0, 5] == pytest.approx(mdot_charge_kg_per_s)  # mdot_ch_kg_per_s
        # Charge temperatures (should be tank temp when not charging)
        assert shs_controller.step_results[0, 6] == pytest.approx(t_charge_in_c)  # t_ch_in_c
        assert shs_controller.step_results[0, 7] == pytest.approx(t_charge_out_c)  # t_ch_out_c
        assert shs_controller.step_results[0, 8] == pytest.approx(mdot_discharge_kg_per_s)  # mdot_dch_kg_per_s
        # Discharge temperatures
        assert shs_controller.step_results[0, 9] == pytest.approx(t_discharge_in_c)  # t_dch_in_c
        assert shs_controller.step_results[0, 10] == pytest.approx(t_discharge_out_c)  # t_dch_out_c

    def test_controller_run_control_overcharge(self):
        """
        Test the control step of the controller with no demand
        """
        prosumer = create_empty_prosumer_container()
        shs_controller_idx = create_controlled_heat_storage(prosumer,
                                                            order=0,
                                                            period=_default_period(prosumer),
                                                            init_soc=0.5,
                                                            **_default_argument())
        shs_controller = prosumer.controller.iloc[shs_controller_idx].object

        q_in_kw = 1e6
        q_out_kw = 1000
        shs_controller.inputs = np.array([[q_in_kw]])
        shs_controller.q_to_deliver_kw = lambda x: q_out_kw
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")

        with pytest.raises(ValueError):
            shs_controller.control_step(prosumer)

        # Case where the extra charge would be added to output of the storage instead of raising an exception
        # capacity_kwh = 100
        # soc = 0.5 - (q_in_kw - q_out_kw) * shs_controller.resol / 3600 / 100
        # overcharge_kwh = (1 - soc) * capacity_kwh
        # soc = 1
        # q_out_kw += (overcharge_kwh - capacity_kwh) * 3600 / shs_controller.resol
        # expected = [soc, q_out_kw]
        # assert shs_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_t_m_to_receive(self):
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 1,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 00:00:09",
                               timezone="utc")
        e_capacity_kwh = 100
        init_soc = 0.4
        shs_params = {"e_capacity_kwh": e_capacity_kwh}

        shs_controller_indx = create_controlled_heat_storage(prosumer, init_soc=init_soc, period=period, **shs_params)
        shs_controller = prosumer.controller.iloc[shs_controller_indx].object

        q_to_fill_kwh = (1-init_soc) * e_capacity_kwh
        assert shs_controller.q_to_receive_kw(prosumer) == pytest.approx(q_to_fill_kwh * 3600/shs_controller.resol)

        q_in_kw = 1000
        q_out_kw = 100
        shs_controller.q_to_deliver_kw = lambda x: q_out_kw
        assert shs_controller.q_to_receive_kw(prosumer) == pytest.approx(q_to_fill_kwh * 3600/shs_controller.resol + q_out_kw)

        shs_controller.inputs = np.array([[q_in_kw]])
        assert shs_controller.q_to_receive_kw(prosumer) == pytest.approx(q_to_fill_kwh * 3600/shs_controller.resol + q_out_kw - q_in_kw)

    def test_fluid_mix_mode_step(self):
        """Test FluidMix mode: uniform tank with input T and mdot; check step_results and optional result_mass_flow_with_temp."""
        prosumer = create_empty_prosumer_container(fluid="water")
        resol_s = 60 * 5
        period = create_period(prosumer, resol_s, name="foo",
                               start="2020-01-01 00:00:00", end="2020-01-01 00:00:09", timezone="utc")
        e_capacity_kwh = 10
        low_temp_c = 50.0
        high_temp_c = 70.0
        mdot_charge_kg_per_s = 0.5
        idx = create_controlled_heat_storage(prosumer, e_capacity_kwh=e_capacity_kwh, capacity_kg=1000.0,
                                             t_tank_init_c=low_temp_c, min_temp_c=low_temp_c, max_temp_c=high_temp_c, period=period)
        ctrl = prosumer.controller.iloc[idx].object
        ctrl.time_step(prosumer, "2020-01-01 00:00:00")
        ctrl.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: high_temp_c, FluidMixMapping.MASS_FLOW_KEY: mdot_charge_kg_per_s}
        ctrl.control_step(prosumer)
        # Step ran; step_results must be (1, 2)
        assert ctrl.step_results.shape == (1, 11)
        
        # Calculate expected temperature using proper mixing formula
        capacity_kg = 1000.0
        m_received_kg = mdot_charge_kg_per_s * ctrl.resol
        t_tank_expected_c = ((capacity_kg - m_received_kg) * low_temp_c + m_received_kg * high_temp_c) / capacity_kg
        soc_expected = (t_tank_expected_c - low_temp_c) / (high_temp_c - low_temp_c)
        # q_delivered_kw should be 0 when charging (no delivery)
        # q_ch_kw should be positive when charging
        # Using cp = 4181.554 J/kgK (water at ~50°C, from fluid model)
        q_ch_expected_kw = mdot_charge_kg_per_s * (high_temp_c - low_temp_c) * 4181.554 / 1000  # kW
        # t_received_out_c should be initial tank temp when only charging
        t_received_out_expected_c = low_temp_c
        # Additional outputs for charging scenario
        q_charge_kw_expected = q_ch_expected_kw
        q_discharge_kw_expected = 0.0
        t_charge_in_expected = high_temp_c
        t_charge_out_expected = t_tank_expected_c
        t_discharge_in_expected = np.nan
        t_discharge_out_expected = np.nan
        mdot_charge_kg_per_s_expected = mdot_charge_kg_per_s
        mdot_discharge_kg_per_s_expected = 0.0
        
        assert not np.isnan(ctrl.step_results[0, 0])
        soc = ctrl.step_results[0, 0]
        if not np.isnan(soc):
            assert 0 <= soc <= 1
        assert soc == pytest.approx(soc_expected)
        assert ctrl.step_results[0, 1] == pytest.approx(t_tank_expected_c)  # t_tank_c
        assert ctrl.step_results[0, 2] == pytest.approx(q_ch_expected_kw)  # q_ch_kw
        assert ctrl.step_results[0, 3] == pytest.approx(0.0)  # q_dch_kw (no discharge when charging)
        assert ctrl.step_results[0, 4] == pytest.approx(0.0)  # q_delivered_kw (no delivery when charging with no demand)
        assert ctrl.step_results[0, 5] == pytest.approx(mdot_charge_kg_per_s_expected)  # mdot_ch_kg_per_s
        assert ctrl.step_results[0, 6] == pytest.approx(t_charge_in_expected)  # t_ch_in_c
        assert ctrl.step_results[0, 7] == pytest.approx(t_charge_out_expected)  # t_ch_out_c
        # Discharge values (should be defaults when not discharging)
        assert ctrl.step_results[0, 8] == pytest.approx(0.0)  # mdot_dch_kg_per_s
        assert ctrl.step_results[0, 9] == pytest.approx(t_tank_expected_c)  # t_dch_in_c (default to tank temp)
        assert ctrl.step_results[0, 10] == pytest.approx(t_tank_expected_c)  # t_dch_out_c (default to tank temp)
        
        # When finalized (e.g. no FluidMix initiators), result_mass_flow_with_temp is set
        assert len(ctrl.result_mass_flow_with_temp) == 1
        assert ctrl.result_mass_flow_with_temp[0][FluidMixMapping.MASS_FLOW_KEY] == mdot_charge_kg_per_s
        assert ctrl.result_mass_flow_with_temp[0][FluidMixMapping.TEMPERATURE_KEY] == t_tank_expected_c
        assert ctrl.applied is True

    def test_soc_from_temperature(self):
        """Test SOC from tank temperature when min_temp_c and max_temp_c are set."""
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 1, name="foo",
                               start="2020-01-01 00:00:00", end="2020-01-01 00:00:09", timezone="utc")
        create_controlled_heat_storage(prosumer, e_capacity_kwh=10, capacity_kg=1000.0,
                                       t_tank_init_c=50.0, min_temp_c=20.0, max_temp_c=80.0, period=period)
        ctrl = prosumer.controller.iloc[0].object
        ctrl._temperature = 50.0
        assert ctrl._soc_from_temperature(prosumer) == pytest.approx((50.0 - 20.0) / (80.0 - 20.0))
        ctrl._temperature = 80.0
        assert ctrl._soc_from_temperature(prosumer) == pytest.approx(1.0)
        ctrl._temperature = 20.0
        assert ctrl._soc_from_temperature(prosumer) == pytest.approx(0.0)

    def test_fluid_mix_mode_discharge(self):
        """Test FluidMix mode with discharging (hot water out, cold water in)."""
        prosumer = create_empty_prosumer_container(fluid="water")
        resol_s = 60 * 5
        period = create_period(prosumer, resol_s, name="foo",
                               start="2020-01-01 00:00:00", end="2020-01-01 00:00:09", timezone="utc")
        e_capacity_kwh = 10
        high_temp_c = 70.0
        low_temp_c = 50.0
        mdot_discharge_kg_per_s = 0.5
        idx = create_controlled_heat_storage(prosumer, e_capacity_kwh=e_capacity_kwh, capacity_kg=1000.0,
                                             t_tank_init_c=high_temp_c, min_temp_c=low_temp_c, max_temp_c=high_temp_c, period=period)
        ctrl = prosumer.controller.iloc[idx].object
        ctrl.time_step(prosumer, "2020-01-01 00:00:00")
        # Discharging: hot water out (70°C), cold water in (50°C)
        ctrl.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: low_temp_c, FluidMixMapping.MASS_FLOW_KEY: mdot_discharge_kg_per_s}
        ctrl.control_step(prosumer)
        
        # Calculate expected values
        capacity_kg = 1000.0
        m_received_kg = mdot_discharge_kg_per_s * ctrl.resol
        t_tank_expected_c = ((capacity_kg - m_received_kg) * high_temp_c + m_received_kg * low_temp_c) / capacity_kg
        soc_expected = (t_tank_expected_c - low_temp_c) / (high_temp_c - low_temp_c)
        # q_delivered_kw is positive when discharging (heat is delivered FROM the tank)
        # Using cp = 4190.3005 J/kgK (water at ~70°C, from fluid model)
        q_delivered_expected_kw = mdot_discharge_kg_per_s * (high_temp_c - low_temp_c) * 4190.3005 / 1000  # kW
        
        # Expected values for new column structure
        mdot_discharge_kg_per_s_expected = mdot_discharge_kg_per_s
        t_discharge_in_expected = low_temp_c
        t_discharge_out_expected = high_temp_c
        
        assert ctrl.step_results.shape == (1, 11)
        assert not np.isnan(ctrl.step_results[0, 0])
        soc = ctrl.step_results[0, 0]
        assert 0 <= soc <= 1
        assert soc == pytest.approx(soc_expected)
        assert ctrl.step_results[0, 1] == pytest.approx(t_tank_expected_c)
        # q_ch_kw should be 0 for discharging
        assert ctrl.step_results[0, 2] == pytest.approx(0.0)
        # q_dch_kw should be the delivered power
        assert ctrl.step_results[0, 3] == pytest.approx(q_delivered_expected_kw)
        # q_delivered_kw should be the total delivered power
        assert ctrl.step_results[0, 4] == pytest.approx(q_delivered_expected_kw)
        # mdot_ch_kg_per_s should be 0 for discharging
        assert ctrl.step_results[0, 5] == pytest.approx(0.0)
        # Charge temperatures (should be tank temp when not charging)
        assert ctrl.step_results[0, 6] == pytest.approx(t_tank_expected_c)
        assert ctrl.step_results[0, 7] == pytest.approx(t_tank_expected_c)
        # mdot_dch_kg_per_s should be the discharge mass flow
        assert ctrl.step_results[0, 8] == pytest.approx(mdot_discharge_kg_per_s_expected)
        # Discharge temperatures
        assert ctrl.step_results[0, 9] == pytest.approx(t_discharge_in_expected)
        assert ctrl.step_results[0, 10] == pytest.approx(t_discharge_out_expected)
        
        assert ctrl.step_results[0, 2] == pytest.approx(0.0)  # q_ch_kw (no charging when discharging)
        assert ctrl.step_results[0, 3] == pytest.approx(q_delivered_expected_kw)  # q_dch_kw
        assert ctrl.step_results[0, 4] == pytest.approx(q_delivered_expected_kw)  # q_delivered_kw (bypass + discharge)
        assert ctrl.step_results[0, 5] == pytest.approx(0.0)  # mdot_ch_kg_per_s (no charging)
        # Charge values (should be defaults when not charging)
        assert ctrl.step_results[0, 6] == pytest.approx(t_tank_expected_c)  # t_ch_in_c (default to tank temp)
        assert ctrl.step_results[0, 7] == pytest.approx(t_tank_expected_c)  # t_ch_out_c (default to tank temp)
        assert ctrl.step_results[0, 8] == pytest.approx(mdot_discharge_kg_per_s_expected)  # mdot_dch_kg_per_s
        assert ctrl.step_results[0, 9] == pytest.approx(t_discharge_in_expected)  # t_dch_in_c
        assert ctrl.step_results[0, 10] == pytest.approx(t_discharge_out_expected)  # t_dch_out_c
        
        # Check result_mass_flow_with_temp
        assert len(ctrl.result_mass_flow_with_temp) == 1
        assert ctrl.result_mass_flow_with_temp[0][FluidMixMapping.MASS_FLOW_KEY] == mdot_discharge_kg_per_s
        assert ctrl.result_mass_flow_with_temp[0][FluidMixMapping.TEMPERATURE_KEY] == t_tank_expected_c
        assert ctrl.applied is True

    def test_fluid_mix_mode_with_heat_losses(self):
        """Test FluidMix mode with heat losses when u and area are set."""
        prosumer = create_empty_prosumer_container(fluid="water")
        resol_s = 60 * 5
        period = create_period(prosumer, resol_s, name="foo",
                               start="2020-01-01 00:00:00", end="2020-01-01 00:00:09", timezone="utc")
        e_capacity_kwh = 10
        init_temp_c = 60.0
        min_temp_c = 50.0
        max_temp_c = 70.0
        t_ext_c = 20.0
        u_w_per_m2k = 1.0  # W/m²K
        area_wall_m2 = 5.0  # m²
        idx = create_controlled_heat_storage(prosumer, e_capacity_kwh=e_capacity_kwh, capacity_kg=1000.0,
                                             t_tank_init_c=init_temp_c, min_temp_c=min_temp_c, max_temp_c=max_temp_c,
                                             u_w_per_m2k=u_w_per_m2k, area_wall_m2=area_wall_m2, t_ext_c=t_ext_c, period=period)
        ctrl = prosumer.controller.iloc[idx].object
        ctrl.time_step(prosumer, "2020-01-01 00:00:00")
        # No flow, so only heat losses should affect temperature
        ctrl.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan, FluidMixMapping.MASS_FLOW_KEY: np.nan}
        ctrl.control_step(prosumer)
        
        # Calculate expected temperature drop due to heat losses
        # q_loss_w = u * area * (t_tank - t_ext)
        # loss_w_per_k = cp_j_per_kgk * resol * capacity_kg
        # t_loss_c = q_loss_w / loss_w_per_k
        q_loss_w = u_w_per_m2k * area_wall_m2 * (init_temp_c - t_ext_c)
        cp_j_per_kgk = 4180.0  # default water
        loss_w_per_k = cp_j_per_kgk * ctrl.resol * 1000.0
        t_loss_expected_c = q_loss_w / loss_w_per_k
        t_tank_expected_c = init_temp_c - t_loss_expected_c
        soc_expected = (t_tank_expected_c - min_temp_c) / (max_temp_c - min_temp_c)
        
        assert ctrl.step_results.shape == (1, 11)
        assert not np.isnan(ctrl.step_results[0, 0])
        soc = ctrl.step_results[0, 0]
        assert 0 <= soc <= 1
        assert soc == pytest.approx(soc_expected)
        assert ctrl.step_results[0, 1] == pytest.approx(t_tank_expected_c)  # t_tank_c
        assert ctrl.step_results[0, 2] == pytest.approx(0.0)  # q_ch_kw (no charging)
        assert ctrl.step_results[0, 3] == pytest.approx(0.0)  # q_dch_kw (no discharging)
        assert ctrl.step_results[0, 4] == pytest.approx(0.0)  # q_delivered_kw (no flow)
        assert ctrl.step_results[0, 5] == pytest.approx(0.0)  # mdot_ch_kg_per_s (no flow)
        # Temperature values (should be tank temp when no flow)
        assert ctrl.step_results[0, 6] == pytest.approx(t_tank_expected_c)  # t_ch_in_c
        assert ctrl.step_results[0, 7] == pytest.approx(t_tank_expected_c)  # t_ch_out_c
        assert ctrl.step_results[0, 8] == pytest.approx(0.0)  # mdot_dch_kg_per_s (no flow)
        assert ctrl.step_results[0, 9] == pytest.approx(t_tank_expected_c)  # t_dch_in_c
        assert ctrl.step_results[0, 10] == pytest.approx(t_tank_expected_c)  # t_dch_out_c
        
        # Check result_mass_flow_with_temp
        assert len(ctrl.result_mass_flow_with_temp) == 1
        assert ctrl.result_mass_flow_with_temp[0][FluidMixMapping.MASS_FLOW_KEY] == 0.0
        assert ctrl.result_mass_flow_with_temp[0][FluidMixMapping.TEMPERATURE_KEY] == pytest.approx(t_tank_expected_c)
        assert ctrl.applied is True

    def test_fluid_mix_mode_simple_charge_discharge(self):
        """Simple direct FluidMix charge then discharge example."""
        prosumer = create_empty_prosumer_container(fluid="water")
        resol_s = 60 * 5
        start = "2020-01-01 00:00:00"
        end = "2020-01-01 02:00:00"
        period = create_period(
            prosumer,
            resol_s,
            name="foo",
            start=start,
            end=end,
            timezone="utc",
        )

        idx = create_controlled_heat_storage(
            prosumer,
            e_capacity_kwh=10.0,
            capacity_kg=1000.0,
            t_tank_init_c=50.0,
            min_temp_c=50.0,
            max_temp_c=70.0,
            period=period,
        )
        ctrl = prosumer.controller.iloc[idx].object

        # Build a time index consistent with the period definition
        times = pd.date_range(start=start, end=end, freq=f"{resol_s}S", tz="utc", inclusive="left")

        mdot = np.zeros(len(times))
        t_in = np.full(len(times), 50.0)
        half = len(times) // 2
        mdot[:half] = 0.5
        t_in[:half] = 70.0
        mdot[half:] = 0.5
        t_in[half:] = 50.0

        socs = []
        q_del = []
        t_tanks = []
        q_ch = []
        q_dch = []
        t_charge_in = []
        t_charge_out = []
        t_discharge_in = []
        t_discharge_out = []
        mdot_ch_list = []
        mdot_dch_list = []
        for ts, md, ti in zip(times, mdot, t_in):
            ctrl.time_step(prosumer, ts)
            ctrl.input_mass_flow_with_temp = {
                FluidMixMapping.TEMPERATURE_KEY: float(ti),
                FluidMixMapping.MASS_FLOW_KEY: float(md),
            }
            ctrl.control_step(prosumer)
            soc, t_tank, q_ch_kw, q_dch_kw, q_delivered_kw, mdot_ch, t_ch_in, t_ch_out, mdot_dch, t_dch_in, t_dch_out = ctrl.step_results[0]
            socs.append(soc)
            t_tanks.append(t_tank)
            q_ch.append(q_ch_kw)
            q_dch.append(q_dch_kw)
            mdot_ch_list.append(mdot_ch)
            t_charge_in.append(t_ch_in)
            t_charge_out.append(t_ch_out)
            mdot_dch_list.append(mdot_dch)
            t_discharge_in.append(t_dch_in)
            t_discharge_out.append(t_dch_out)

        assert max(socs) > min(socs)
        assert any(q != 0.0 for q in q_dch)  # Check that at least one timestep has a non-zero discharge
        