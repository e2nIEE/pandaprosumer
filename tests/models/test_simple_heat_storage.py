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
            'capacity_kg', 'init_temperature_c', 'min_temp_c', 'max_temp_c',
            'u_w_per_m2k', 'area_wall_m2', 't_ext_c'
        ]
        assert sorted(prosumer.heat_storage.columns) == sorted(expected_columns)
        row = prosumer.heat_storage.iloc[0]
        assert row['name'] is None
        assert row['in_service'] == True or row['in_service'] is True
        assert row['e_capacity_kwh'] == 0 or (isinstance(row['e_capacity_kwh'], (int, float)) and np.isclose(row['e_capacity_kwh'], 0))
        for col in ['capacity_kg', 'init_temperature_c', 'min_temp_c', 'max_temp_c',
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
            'capacity_kg', 'init_temperature_c', 'min_temp_c', 'max_temp_c',
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
        result_columns_expected = ["soc", "q_delivered_kw"]

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
        expected = [soc, q_out_kw]
        assert shs_controller.step_results == pytest.approx(np.array([expected]))

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
        expected = [soc, q_out_kw]
        assert shs_controller.step_results == pytest.approx(np.array([expected]))

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
        expected = [soc, q_out_kw]
        assert shs_controller.step_results == pytest.approx(np.array([expected]))

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
                                             init_temperature_c=low_temp_c, min_temp_c=low_temp_c, max_temp_c=high_temp_c, period=period)
        ctrl = prosumer.controller.iloc[idx].object
        ctrl.time_step(prosumer, "2020-01-01 00:00:00")
        ctrl.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: high_temp_c, FluidMixMapping.MASS_FLOW_KEY: mdot_charge_kg_per_s}
        ctrl.control_step(prosumer)
        # Step ran; step_results must be (1, 2)
        assert ctrl.step_results.shape == (1, 2)
        
        # Calculate expected temperature using proper mixing formula
        capacity_kg = 1000.0
        m_received_kg = mdot_charge_kg_per_s * ctrl.resol
        t_tank_expected_c = ((capacity_kg - m_received_kg) * low_temp_c + m_received_kg * high_temp_c) / capacity_kg
        soc_expected = (t_tank_expected_c - low_temp_c) / (high_temp_c - low_temp_c)
        # q_delivered_kw is negative when charging (heat is delivered TO the tank)
        # Using cp = 4181.554 J/kgK (water at ~50°C, from fluid model)
        q_delivered_expected_kw = mdot_charge_kg_per_s * (low_temp_c - high_temp_c) * 4181.554 / 1000  # kW
        
        assert not np.isnan(ctrl.step_results[0, 0])
        soc = ctrl.step_results[0, 0]
        if not np.isnan(soc):
            assert 0 <= soc <= 1
        assert soc == pytest.approx(soc_expected)
        assert ctrl.step_results[0, 1] == pytest.approx(q_delivered_expected_kw)
        
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
                                       init_temperature_c=50.0, min_temp_c=20.0, max_temp_c=80.0, period=period)
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
                                             init_temperature_c=high_temp_c, min_temp_c=low_temp_c, max_temp_c=high_temp_c, period=period)
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
        
        assert ctrl.step_results.shape == (1, 2)
        assert not np.isnan(ctrl.step_results[0, 0])
        soc = ctrl.step_results[0, 0]
        assert 0 <= soc <= 1
        assert soc == pytest.approx(soc_expected)
        assert ctrl.step_results[0, 1] == pytest.approx(q_delivered_expected_kw)
        
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
                                             init_temperature_c=init_temp_c, min_temp_c=min_temp_c, max_temp_c=max_temp_c,
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
        
        assert ctrl.step_results.shape == (1, 2)
        assert not np.isnan(ctrl.step_results[0, 0])
        soc = ctrl.step_results[0, 0]
        assert 0 <= soc <= 1
        assert soc == pytest.approx(soc_expected)
        assert ctrl.step_results[0, 1] == pytest.approx(0.0)  # No flow, so no heat delivered
        
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
            init_temperature_c=50.0,
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
        for ts, md, ti in zip(times, mdot, t_in):
            ctrl.time_step(prosumer, ts)
            ctrl.input_mass_flow_with_temp = {
                FluidMixMapping.TEMPERATURE_KEY: float(ti),
                FluidMixMapping.MASS_FLOW_KEY: float(md),
            }
            ctrl.control_step(prosumer)
            soc, qk = ctrl.step_results[0]
            socs.append(soc)
            q_del.append(qk)

        assert max(socs) > min(socs)
        assert any(q != 0.0 for q in q_del)  # Check that at least one timestep has a non-zero delivery
        