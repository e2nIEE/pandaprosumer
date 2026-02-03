import pytest
import numpy as np

from pandaprosumer import *
from pandaprosumer.create import (
    create_empty_prosumer_container,
    create_period,
    create_pv_production,
)
from pandaprosumer.controller import PvProductionController
from pandaprosumer.controller.data_model import PvProductionComponentData


def _default_argument():
    return {}


def _default_period(prosumer):
    return create_period(
        prosumer,
        3600,
        name="foo",
        start="2020-01-01 00:00:00",
        end="2020-01-01 11:59:59",
        timezone="utc"
    )


class TestPV:
    """
    Tests the functionalities of the PV element and controller
    """
    def test_define_element(self):
        """
        Test the creation of a PV element with default parameter values
        (except latitude / longitude, which are mandatory).
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 3600)

        pv_idx = create_pv_production(
            prosumer,
            latitude=40.0,
            longitude=5.0
        )

        assert hasattr(prosumer, "pv_production")
        assert len(prosumer.pv_production) == 1
        assert pv_idx == 0

        expected_columns = [
            "name",
            "in_service",
            "latitude",
            "longitude",
            "raddatabase",
            "surface_tilt",
            "surface_azimuth",
            "peakpower",
            "loss",
            "usehorizon",
            "userhorizon",
            "pvtechchoice",
            "mountingplace",
            "trackingtype",
            "optimal_surface_tilt",
            "optimalangles",
            "outputformat",
            "url",
            "map_variables",
            "timeout"
        ]

        expected_values = [
            f"pv_production_{pv_idx}",
            True,  # in_service
            40.0,  # latitude
            5.0,   # longitude
            "PVGIS-ERA5",  # raddatabase
            40.0,  # surface_tilt
            0.0,   # surface_azimuth
            1.0,   # peakpower [kW]
            0.0,   # loss
            True,  # usehorizon
            None,  # userhorizon
            "crystSi",  # pvtechchoice
            "free",  # mountingplace
            0,  # trackingtype
            False,  # optimal_surface_tilt
            False,  # optimalangles
            "json",  # outputformat
            "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc?",  # url
            True,  # map_variables
            30.0   # timeout
        ]

        assert sorted(prosumer.pv_production.columns) == sorted(expected_columns)
        actual_values = prosumer.pv_production.iloc[0][expected_columns].values
        assert actual_values == pytest.approx(expected_values, nan_ok=True)


    def test_define_element_param(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        pv_idx = create_pv_production(
            prosumer,
            latitude=40.0,
            longitude=5.0,
            peakpower=2.5,
            loss=10.0,
            name="foo",
            in_service=False,
            index=4,
            custom="test"
        )

        expected_columns = [
            "name",
            "in_service",
            "latitude",
            "longitude",
            "raddatabase",
            "surface_tilt",
            "surface_azimuth",
            "peakpower",
            "loss",
            "usehorizon",
            "userhorizon",
            "pvtechchoice",
            "mountingplace",
            "trackingtype",
            "optimal_surface_tilt",
            "optimalangles",
            "outputformat",
            "url",
            "map_variables",
            "timeout",
            "custom"
        ]

        expected_values = [
            "foo",          # name
            False,          # in_service
            40.0,           # latitude
            5.0,            # longitude
            "PVGIS-ERA5",   # raddatabase (default)
            40.0,           # surface_tilt (default)
            0.0,            # surface_azimuth (default)
            2.5,            # peakpower
            10.0,           # loss
            True,           # usehorizon (default)
            None,           # userhorizon (default)
            "crystSi",      # pvtechchoice (default)
            "free",         # mountingplace (default)
            0,              # trackingtype (default)
            False,          # optimal_surface_tilt (default)
            False,          # optimalangles (default)
            "json",         # outputformat (default)
            "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc?",  # url (default)
            True,           # map_variables (default)
            30.0,           # timeout (default)
            "test"          # custom
        ]

        assert sorted(prosumer.pv_production.columns) == sorted(expected_columns)
        actual_values = prosumer.pv_production.loc[pv_idx, expected_columns].values
        assert actual_values == pytest.approx(expected_values, nan_ok=True)


    def test_define_controller(self):
        """
        Test the creation of a PV controller in a prosumer container.
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)

        pv_idx = create_pv_production(
            prosumer,
            latitude=40.0,
            longitude=5.0,
            peakpower=2.0  # 2 kW
        )

        pv_data = PvProductionComponentData(
            element_index=[pv_idx],
            period_index=period
        )

        PvProductionController(
            prosumer,
            pv_production_object=pv_data,
            order=0,
            level=0,
            data_source=None
        )

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1


    def test_controller_columns(self):
        """
        Check that the input and result columns of the PV controller
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)

        pv_controller_idx = create_controlled_pv_production(
            prosumer,
            latitude=40.0,
            longitude=5.0,
            peakpower=5.0,
            order=0,
            period=period,
            **_default_argument()
        )

        pv_controller = prosumer.controller.loc[pv_controller_idx].object

        input_columns_expected = [
            "p_w",
            "poa_direct_w_m2",
            "poa_sky_diffuse_w_m2",
            "poa_ground_diffuse_w_m2",
            "solar_elevation_deg",
            "temp_air_c",
            "wind_speed_m_s",
            "solar_rad_reconstr_bool"
        ]

        result_columns_expected = [
            "p_w",
            "poa_direct_w_m2",
            "poa_sky_diffuse_w_m2",
            "poa_ground_diffuse_w_m2",
            "solar_elevation_deg",
            "temp_air_c",
            "wind_speed_m_s",
            "solar_rad_reconstr_bool"
        ]

        assert pv_controller.input_columns == input_columns_expected
        assert pv_controller.result_columns == result_columns_expected


    def _make_pv_controller(self, peakpower_kw=5.0):
        """Helper to create one PV controller and return (prosumer, controller)."""
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)

        pv_idx = create_pv_production(
            prosumer,
            latitude=40.0,
            longitude=5.0,
            peakpower=peakpower_kw
        )

        pv_data = PvProductionComponentData(
            element_index=[pv_idx],
            period_index=period
        )

        PvProductionController(
            prosumer,
            pv_production_object=pv_data,
            order=0,
            level=0,
            data_source=None
        )

        ctrl_idx = prosumer.controller.index[-1]
        ctrl = prosumer.controller.loc[ctrl_idx].object

        return prosumer, ctrl

    def test_control_step_inputs(self):
        """
        No clipping, no horizon effects: result should equal inputs.
        """
        pros, pv_ctrl = self._make_pv_controller(peakpower_kw=5.0)

        inputs = np.array([[
            1000.0,   # p_w [W]
            700.0,    # poa_direct_w_m2
            200.0,    # poa_sky_diffuse_w_m2
            100.0,    # poa_ground_diffuse_w_m2
            30.0,     # solar_elevation_deg (> 0)
            15.0,     # temp_air_c
            3.0,      # wind_speed_m_s
            1.0       # solar_rad_reconstr_bool
        ]])

        pv_ctrl.inputs = inputs
        pv_ctrl.time_step(pros, "2020-01-01 08:00:00")
        pv_ctrl.control_step(pros)

        result = pv_ctrl.step_results[0]
        assert result == pytest.approx(inputs[0], rel=1e-9)
        assert pv_ctrl.is_converged(pros) is True


    def test_control_step_negative_power(self):
        """
        Negative p_w should be clamped to 0 W.
        """
        pros, pv_ctrl = self._make_pv_controller(peakpower_kw=5.0)

        inputs = np.array([[
            -500.0,
            0.0,
            0.0,
            0.0,
            20.0,
            10.0,
            2.0,
            1.0
        ]])

        pv_ctrl.inputs = inputs
        pv_ctrl.time_step(pros, "2020-01-01 10:00:00")
        pv_ctrl.control_step(pros)

        result = pv_ctrl.step_results[0]
        i_p_w = pv_ctrl.input_columns.index("p_w")

        assert result[i_p_w] == pytest.approx(0.0)

        expected = inputs[0].copy()
        expected[0] = 0.0
        assert result == pytest.approx(expected, rel=1e-9)

    def test_control_step_above_peak(self):
        pros, pv_ctrl = self._make_pv_controller(peakpower_kw=2.0)  # 2 kW

        inputs = np.array([[
            5000.0,
            800.0,
            200.0,
            100.0,
            45.0,
            20.0,
            1.0,
            1.0
        ]])

        pv_ctrl.inputs = inputs
        pv_ctrl.time_step(pros, "2020-01-01 01:00:00")
        pv_ctrl.control_step(pros)

        result = pv_ctrl.step_results[0]
        i_p_w = pv_ctrl.input_columns.index("p_w")

        assert result[i_p_w] == pytest.approx(2000.0)

        expected = inputs[0].copy()
        expected[0] = 2000.0
        assert result == pytest.approx(expected, rel=1e-9)

    def test_control_step_below_horizon(self):
        """
        If solar_elevation_deg < 0, PV power should be forced to 0 W.
        """
        pros, pv_ctrl = self._make_pv_controller(peakpower_kw=5.0)

        inputs = np.array([[
            800.0,
            100.0,
            50.0,
            20.0,
            -5.0,
            12.0,
            2.0,
            1.0
        ]])

        pv_ctrl.inputs = inputs
        pv_ctrl.time_step(pros, "2020-01-01 04:00:00")
        pv_ctrl.control_step(pros)

        result = pv_ctrl.step_results[0]
        i_p_w = pv_ctrl.input_columns.index("p_w")

        assert result[i_p_w] == pytest.approx(0.0)
        expected = inputs[0].copy()
        expected[0] = 0.0
        assert result == pytest.approx(expected, rel=1e-9)
