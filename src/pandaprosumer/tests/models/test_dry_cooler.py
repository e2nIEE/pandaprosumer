import numpy as np
import pytest

from pandaprosumer.create import create_empty_prosumer_container, create_dry_cooler, create_period
from pandaprosumer.controller import DryCoolerController, DryCoolerControllerData
from pandaprosumer.run_time_series import run_timeseries
from ..create_elements_controllers import *


def _create_dry_cooler_controller(prosumer, **kwargs):
    period = create_period(prosumer, 1,
                           name="foo",
                           start="2020-01-01 00:00:00",
                           end="2020-01-01 11:59:59",
                           timezone="utc")

    dry_cooler_index = init_dc_element(prosumer, **kwargs)
    init_dc_controller(prosumer, period, [dry_cooler_index])
    dc_controller = prosumer.controller.iloc[0].object
    return dc_controller


class TestDryCooler:
    """
    Tests the functionalities of a Dry Cooler element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a Dry Cooler element with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        init_dc_element(prosumer)
        assert hasattr(prosumer, "dry_cooler")
        assert len(prosumer.dry_cooler) == 1
        expected_columns = ["name", "n_nom_rpm", "p_fan_nom_kw", "qair_nom_m3_per_h", "t_air_in_nom_c",
                            "t_air_out_nom_c", "t_fluid_in_nom_c", "t_fluid_out_nom_c", "fans_number",
                            "adiabatic_mode", "phi_adiabatic_sat_percent", "min_delta_t_air_c", "in_service"]
        expected_values = [None, 730, 9.38, 138200, 15, 35, 65, 40, 1, False, 99, 0, True]

        assert sorted(prosumer.dry_cooler.columns) == sorted(expected_columns)

        # Convert the np.nan to None to check a test with approx values, None and np.nan values, and mixed types
        values = [v if not (isinstance(v, float) and np.isnan(v)) else None for v in prosumer.dry_cooler.iloc[0].values]
        assert values == pytest.approx(expected_values)

    def test_define_element_with_parameters(self):
        """
        Test the creation of a Dry Cooler element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {'fans_number': 3,
                  'n_nom_rpm': 5,
                  'p_fan_nom_kw': 15,
                  'qair_nom_m3_per_h': 300,
                  't_air_in_nom_c': 20,
                  't_air_out_nom_c': 25,
                  't_fluid_in_nom_c': 50,
                  't_fluid_out_nom_c': 38,
                  'adiabatic_mode': True,
                  'phi_adiabatic_sat_percent': 95,
                  'min_delta_t_air_c': 5}

        dc_idx = init_dc_element(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "dry_cooler")
        assert len(prosumer.dry_cooler) == 1
        assert dc_idx == 4
        assert prosumer.dry_cooler.index[0] == dc_idx

        expected_columns = ["name", "n_nom_rpm", "p_fan_nom_kw", "qair_nom_m3_per_h", "t_air_in_nom_c",
                            "t_air_out_nom_c", "t_fluid_in_nom_c", "t_fluid_out_nom_c", "fans_number",
                            "adiabatic_mode", "phi_adiabatic_sat_percent", "min_delta_t_air_c", "in_service", "custom"]
        expected_values = ['foo', 5, 15, 300, 20, 25, 50, 38, 3, True, 95, 5, False, 'test']
        assert sorted(prosumer.dry_cooler.columns) == sorted(expected_columns)
        assert prosumer.dry_cooler.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """
        Test the creation of a Dry Cooler controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        _create_dry_cooler_controller(prosumer)

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """
        Test the input and result columns of the Dry Cooler controller
        """
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer)

        input_columns_expected = ["mdot_fluid_kg_per_s", "t_in_c", "t_out_c", "t_air_in_c", "phi_air_in_percent"]
        result_columns_expected = ['q_exchanged_kw', 'p_fans_kw', 'n_rpm', 'mdot_air_m3_per_h',
                                   'mdot_air_kg_per_s', 't_air_in_c', 't_air_out_c',
                                   'mdot_fluid_kg_per_s', 't_fluid_in_c', 't_fluid_out_c']

        assert dc_controller.input_columns == input_columns_expected
        assert dc_controller.result_columns == result_columns_expected

    def test_controller_run_control_no_demand(self):
        """
        Test the Dry Cooler controller run_control method with no demand (same temperature in and out)"""
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer)

        dc_controller.inputs = np.array([[2, 80, 80, 20, np.nan]])
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 2
        dc_controller.time_step(prosumer, "2020-01-01 00:00:00")

        dc_controller.control_step(prosumer)
        expected = [0.,  0.,  0.,  0.,  0., 20., 20.,  2., 80., 80.]
        assert dc_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_demand(self):
        """
        Test the Dry Cooler controller run_control method with a demand
        """
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer)

        dc_controller.inputs = np.array([[2, 80, 40, 20, np.nan]])
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 2
        dc_controller.time_step(prosumer, "2020-01-01 00:00:00")
        dc_controller.control_step(prosumer)

        expected = [334.81412, .027525388, 104.512057, 19785.70731,
                    5.9638259, 20., 75.75057,
                    2., 80., 40.]
        assert dc_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_nominal(self):
        """
        Test the Dry Cooler controller run_control method with nominal values
        """
        params = {'fans_number': 3,
                  'n_nom_rpm': 300,
                  'p_fan_nom_kw': 15,
                  'qair_nom_m3_per_h': 200,
                  't_air_in_nom_c': 20,
                  't_air_out_nom_c': 25,
                  't_fluid_in_nom_c': 50,
                  't_fluid_out_nom_c': 38}
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer, **params)

        q_w = 200 / 3600 * 1.177 * 1007 * (25 - 20)
        mdot_water_kg_per_s = q_w / (4180 * (50 - 38))

        dc_controller.inputs = np.array([[mdot_water_kg_per_s, 50, 38, 20, np.nan]])
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 50
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_water_kg_per_s
        dc_controller.time_step(prosumer, "2020-01-01 00:00:00")
        dc_controller.control_step(prosumer)

        expected = [q_w / 1000, 15 * 3, 300, 200,
                    .06510377, 20., 25.,
                    mdot_water_kg_per_s, 50., 38.]
        assert dc_controller.step_results == pytest.approx(np.array([expected]), .015)

    def test_controller_run_control_adiabatic_nominal(self):
        """
        Test the Dry Cooler controller run_control method with nominal values in adiabatic mode
        with 100% relative humidity -> no air pre-cooling
        """
        params = {'fans_number': 3,
                  'n_nom_rpm': 300,
                  'p_fan_nom_kw': 15,
                  'qair_nom_m3_per_h': 200,
                  't_air_in_nom_c': 20,
                  't_air_out_nom_c': 25,
                  't_fluid_in_nom_c': 50,
                  't_fluid_out_nom_c': 38,
                  'adiabatic_mode': True}
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer, **params)

        q_w = 200 / 3600 * 1.177 * 1007 * (25 - 20)
        mdot_water_kg_per_s = q_w / (4180 * (50 - 38))

        dc_controller.inputs = np.array([[mdot_water_kg_per_s, 50, 38, 20, 100]])
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 50
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_water_kg_per_s
        dc_controller.time_step(prosumer, "2020-01-01 00:00:00")
        dc_controller.control_step(prosumer)

        expected = [q_w / 1000, 15 * 3, 300, 200,
                    .06510377, 20., 25.02236376,
                    mdot_water_kg_per_s, 50., 38.]
        assert dc_controller.step_results == pytest.approx(np.array([expected]), .015)

    def test_controller_run_control_adiabatic(self):
        """
        Test the Dry Cooler controller run_control method with nominal values in adiabatic mode
        with relative humidity < 100% -> air pre-cooling -> lower power consumption
        """
        params = {'fans_number': 3,
                  'n_nom_rpm': 300,
                  'p_fan_nom_kw': 15,
                  'qair_nom_m3_per_h': 200,
                  't_air_in_nom_c': 20,
                  't_air_out_nom_c': 25,
                  't_fluid_in_nom_c': 50,
                  't_fluid_out_nom_c': 38,
                  'adiabatic_mode': True,
                  'phi_adiabatic_sat_percent': 100}
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer, **params)

        q_w = 200 / 3600 * 1.177 * 1007 * (25 - 20)
        mdot_water_kg_per_s = q_w / (4180 * (50 - 38))

        dc_controller.inputs = np.array([[mdot_water_kg_per_s, 50, 38, 20, 20]])
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 50
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_water_kg_per_s
        dc_controller.time_step(prosumer, "2020-01-01 00:00:00")
        dc_controller.control_step(prosumer)

        expected = [q_w / 1000, .327555633, 58.1405016, 38.7603344,
                    .0127564, 9.1619787, 34.7959426,
                    mdot_water_kg_per_s, 50., 38.]
        assert dc_controller.step_results == pytest.approx(np.array([expected]), .015)

    def test_controller_run_control_adiabatic_no_sat(self):
        """
        Test the Dry Cooler controller run_control method with nominal values in adiabatic mode
        with relative humidity after air pre-cooling < 100% -> higher power consumption
        """
        params = {'fans_number': 3,
                  'n_nom_rpm': 300,
                  'p_fan_nom_kw': 15,
                  'qair_nom_m3_per_h': 200,
                  't_air_in_nom_c': 20,
                  't_air_out_nom_c': 25,
                  't_fluid_in_nom_c': 50,
                  't_fluid_out_nom_c': 38,
                  'adiabatic_mode': True,
                  'phi_adiabatic_sat_percent': 95}
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer, **params)

        q_w = 200 / 3600 * 1.177 * 1007 * (25 - 20)
        mdot_water_kg_per_s = q_w / (4180 * (50 - 38))

        dc_controller.inputs = np.array([[mdot_water_kg_per_s, 50, 38, 20, 20]])
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 50
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_water_kg_per_s
        dc_controller.time_step(prosumer, "2020-01-01 00:00:00")
        dc_controller.control_step(prosumer)

        expected = [q_w / 1000, .36699935, 60.38635981, 40.2575732,
                    .0131884, 9.6682871, 34.461331,
                    mdot_water_kg_per_s, 50., 38.]
        assert dc_controller.step_results == pytest.approx(np.array([expected]), .015)

    def test_controller_run_control_adiabatic_outrange(self):
        """
        Test the Dry Cooler controller run_control method in adiabatic mode
        with demand way larger than nominal values -> reduced water mass flow rate
        """
        params = {'fans_number': 3,
                  'n_nom_rpm': 300,
                  'p_fan_nom_kw': 15,
                  'qair_nom_m3_per_h': 200,
                  't_air_in_nom_c': 20,
                  't_air_out_nom_c': 25,
                  't_fluid_in_nom_c': 50,
                  't_fluid_out_nom_c': 38,
                  'adiabatic_mode': True,
                  'phi_adiabatic_sat_percent': 100,
                  'min_delta_t_air_c': 5}
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer, **params)

        q_w = 2000 / 3600 * 1.177 * 1007 * (25 - 20)  # 10 times higher demand
        mdot_water_kg_per_s = q_w / (4180 * (50 - 38))

        dc_controller.inputs = np.array([[mdot_water_kg_per_s, 50, 38, 20, 20]])
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 50
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_water_kg_per_s
        dc_controller.time_step(prosumer, "2020-01-01 00:00:00")
        dc_controller.control_step(prosumer)

        expected = [0.49796684, 138.996498, 436.903009, 291.268673,
                    .098901, 9.161978, 14.161978,
                    mdot_water_kg_per_s, 50., 48.1851619]
        assert dc_controller.step_results == pytest.approx(np.array([expected]), .015)

    def test_controller_run_control_data(self):
        """
        Test the Dry Cooler controller run_control method with inputs different from the nominal values
        """
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer)

        dc_controller.inputs = np.array([[141 / 3.6, 53, 48, 10, np.nan]])
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 53
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 141 / 3.6
        dc_controller.time_step(prosumer, "2020-01-01 00:00:00")
        dc_controller.control_step(prosumer)

        # Q = [280586.083333333, (280586.083333333), (280586.083333333), (280586.083333333), (280586.083333333)]
        # N =  [(147.46), (144.54), (147.46), (144.10199999999998), (140.379)]
        # P_elec = [77.31378704, (72.81123695999999), (77.31378704000002), (72.15132041711996), (66.70228184045999)]
        # F = [(27916.4), (27363.6), (27916.4), (27280.679999999993), (26575.859999999997)]
        # P_elec_tot = (366.29241329757997)

        expected = [818.9229, 2.572381, 474.27876, 89788.117,
                    29.23532, 10., 37.8167,
                    39.16667, 53., 48.]
        assert dc_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_t_m_to_receive(self):
        """
        Test the Dry Cooler controller t_m_to_receive method
        """
        prosumer = create_empty_prosumer_container()
        dc_controller = _create_dry_cooler_controller(prosumer)

        q_demand_kw = 104.58385
        mdot_demand_kg_per_s = .5
        t_feed_demand_c = 80
        cp_kj_per_kgk = prosumer.fluid.get_heat_capacity(273.15 + t_feed_demand_c) / 1000
        t_return_demand_c = t_feed_demand_c - q_demand_kw / (mdot_demand_kg_per_s * cp_kj_per_kgk)
        t_air_c = 20

        dc_controller.inputs = np.array([[mdot_demand_kg_per_s, t_feed_demand_c, t_return_demand_c, t_air_c, np.nan]])

        assert dc_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c,
                                                                        t_return_demand_c,
                                                                        mdot_demand_kg_per_s),
                                                                       .001)

        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s
        assert dc_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c,
                                                                        t_return_demand_c,
                                                                        0.),
                                                                       .001)

        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s / 3
        assert dc_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c,
                                                                        t_return_demand_c,
                                                                        mdot_demand_kg_per_s * 2/3),
                                                                       .001)

        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c / 2
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s / 2
        assert dc_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c * 1.5,
                                                                        t_return_demand_c,
                                                                        mdot_demand_kg_per_s / 2),
                                                                       .001)

        dc_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c / 2
        dc_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s + 1
        assert dc_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c,
                                                                        t_return_demand_c,
                                                                        0.),
                                                                       .001)
