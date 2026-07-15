import pytest
import numpy as np
from pandaprosumer import create_empty_prosumer_container, create_period, create_solar_thermal, create_controlled_solar_thermal

def _default_argument():
    return {}

def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")

class TestSolarThermal:
    """
    Tests the functionalities of a Solar Thermal element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a heat demand element in a prosumer container with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_solar_thermal(prosumer)
        assert hasattr(prosumer, "solar_thermal")
        assert len(prosumer.solar_thermal) == 1

        expected_columns = [
            "name", "in_service", "collector_area", "optical_efficiency",
            "thermal_losses", "second_thermal_losses", "incidence_angle",
            "flow_rate", "test_specific_heat", "use_specific_heat",
            "number_collectors", "series", "piping_length", "piping_diameter",
            "piping_thickness", "piping_conductivity", "collector_slope",
            "collector_azimut"
        ]

        expected_values = [
            None, True,  # name, in_service
            2.5, 0.77,  # collector_area, optical_efficiency
            3.0, 0.02, 0.9,  # thermal_losses, second_thermal_losses, incidence_angle
            72.0, 4.18, 4.18,  # flow_rate, test_specific_heat, use_specific_heat
            4.0, 1.0,  # number_collectors, series
            0.0, 0.028, 0.03, 0.04,  # piping_length, diameter, thickness, conductivity
            40.0, 0.0  # collector_slope, collector_azimut
        ]

        assert sorted(prosumer.solar_thermal.columns) == sorted(expected_columns)
        assert prosumer.solar_thermal.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        st_idx = create_solar_thermal(prosumer, name="foo", in_service=False, index=4, custom="test", **_default_argument())

        expected_columns = [
            "name", "in_service", "collector_area", "optical_efficiency",
            "thermal_losses", "second_thermal_losses", "incidence_angle",
            "flow_rate", "test_specific_heat", "use_specific_heat",
            "number_collectors", "series", "piping_length", "piping_diameter",
            "piping_thickness", "piping_conductivity", "collector_slope",
            "collector_azimut", "custom"
        ]

        expected_values = [
            "foo", False,
            2.5, 0.77,
            3.0, 0.02, 0.9,
            72.0, 4.18, 4.18,
            4.0, 1.0,
            0.0, 0.028, 0.03, 0.04,
            40.0, 0.0,
            "test"
        ]

        assert sorted(prosumer.solar_thermal.columns) == sorted(expected_columns)

        actual_values = prosumer.solar_thermal.loc[st_idx, expected_columns].values
        assert actual_values == pytest.approx(expected_values, nan_ok=True)

    def test_define_controller(self):
        """
        Test the creation of a heat demand controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_solar_thermal(prosumer, order=0, period=_default_period(prosumer), **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        """
        Check that the input and result columns of the solar thermal controller are the ones expected
        """
        prosumer = create_empty_prosumer_container()
        st_controller_idx = create_controlled_solar_thermal(
            prosumer,
            order=0,
            period=_default_period(prosumer),
            **_default_argument()
        )
        st_controller = prosumer.controller.iloc[st_controller_idx].object

        input_columns_expected = [
            "beam_solar_radiation_w_m2",
            "diffuse_solar_radiation_w_m2",
            "ground_solar_radiation_w_m2",
            "radiation_incidence_angle_deg",
            "ambient_temperature_C",
            "inlet_mass_flow_rate_kg_h",
            "inlet_temperature_C",
        ]

        result_columns_expected = [
            "outlet_temperature_C",
            "outlet_flow_rate_kg_h",
            "energy_gain_W",
        ]

        assert st_controller.input_columns == input_columns_expected
        assert st_controller.result_columns == result_columns_expected

    def test_control_step_no_radiation(self):
        pros = create_empty_prosumer_container()
        st_idx = create_controlled_solar_thermal(pros, order=0, period=_default_period(pros), **_default_argument())
        solar_thermal_controller = pros.controller.iloc[st_idx].object

        solar_thermal_controller.inputs = np.array([[
            0.0,  # beam_solar_radiation_w_m2
            0.0,  # diffuse_solar_radiation_w_m2
            0.0,  # ground_solar_radiation_w_m2
            0.0,  # radiation_incidence_angle_deg
            20.0,  # ambient_temperature_C
            0.0,  # inlet_mass_flow_rate_kg_h
            30.0  # inlet_temperature_C
        ]])

        solar_thermal_controller.time_step(pros, "2020-01-01 00:00:00")
        solar_thermal_controller.control_step(pros)

        result = solar_thermal_controller.step_results[0]
        assert result[0] == pytest.approx(30.0)  # outlet_temperature_C
        assert result[1] == pytest.approx(0.0)  # outlet_flow_rate_kg_h
        assert result[2] == pytest.approx(0.0)  # energy_gain_W
        assert solar_thermal_controller.is_converged(pros) is True

    def test_control_step_radiation_positive_gain(self):
        pros = create_empty_prosumer_container()
        st_idx = create_controlled_solar_thermal(
            pros,
            order=0,
            period=_default_period(pros),
            **_default_argument()
        )
        solar_thermal_controller = pros.controller.iloc[st_idx].object

        # Eingangsgrößen in der Reihenfolge von input_columns
        solar_thermal_controller.inputs = np.array([[
            441.55,  # beam_solar_radiation_w_m2
            153.68,  # diffuse_solar_radiation_w_m2
            11.37,  # ground_solar_radiation_w_m2
            38.06,  # radiation_incidence_angle_deg
            12.78,  # ambient_temperature_C
            576.0,  # inlet_mass_flow_rate_kg_h
            14.4155  # inlet_temperature_C
        ]])

        solar_thermal_controller.time_step(pros, "2020-01-01 01:00:00")
        solar_thermal_controller.control_step(pros)

        result = solar_thermal_controller.step_results[0]

        # Erwartete Ergebnisse mit Toleranz
        assert result[0] == pytest.approx(21.398026, rel=1e-6)  # outlet_temperature_C
        assert result[1] == pytest.approx(576.0, rel=1e-6)  # outlet_flow_rate_kg_h
        assert result[2] == pytest.approx(4669.913718, rel=1e-6)  # energy_gain_W

    def test_control_step_radiation_negative_gain(self):
        pros = create_empty_prosumer_container()
        st_idx = create_controlled_solar_thermal(
            pros,
            order=0,
            period=_default_period(pros),
            **_default_argument()
        )
        solar_thermal_controller = pros.controller.iloc[st_idx].object

        solar_thermal_controller.inputs = np.array([[
            50.0,  # beam_solar_radiation_w_m2 (very low)
            20.0,  # diffuse_solar_radiation_w_m2
            5.0,  # ground_solar_radiation_w_m2
            30.0,  # radiation_incidence_angle_deg
            10.0,  # ambient_temperature_C (cooler as inlet)
            100.0,  # inlet_mass_flow_rate_kg_h
            40.0  # inlet_temperature_C (clearly higher than ambient)
        ]])

        solar_thermal_controller.time_step(pros, "2020-01-01 01:00:00")
        solar_thermal_controller.control_step(pros)

        result = solar_thermal_controller.step_results[0]

        # Erwartete Ergebnisse mit Toleranz
        assert result[0] == pytest.approx(36.94391322621482, rel=1e-6)  # outlet_temperature_C
        assert result[1] == pytest.approx(100.0, rel=1e-6)  # outlet_flow_rate_kg_h
        assert result[2] == pytest.approx(-354.84563095616835, rel=1e-6)  # energy_gain_W
