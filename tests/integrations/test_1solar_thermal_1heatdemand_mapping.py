import pytest
from pandaprosumer import *
from pandas.testing import assert_frame_equal, assert_series_equal
from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping

def _default_argument():
    return {}

class Test1SolarThermal1HeatDemandMapping:
    """
    In this example, a Solar Thermal controller is mapped to a Heat Demand
    """

    def test_generic_mapping(self):

        data = pd.DataFrame({
            "Beam Solar Radiation [W/m2]": [800, 200, 0, 0],
            "Diffuse Solar Radiation [W/m2]": [200, 50, 0, 0],
            "Ground Solar Radiation [W/m2]": [50, 10, 0, 0],
            "Radiation incidence angle [deg]": [30, 30, 30, 30],
            "Ambient temperature [C]": [25, 20, 15, 10],
            "Inlet mass flow rate [kg/h]": [100, 100, 100, 100],
            "Inlet temperature [C]": [30, 30, 30, 30],
            "q_demand_kw": [10, 20, 30, 0]  # gewünschte Wärmelast
        })

        start = "2020-01-01 00:00:00"
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"{resol}s") - pd.Timedelta("1s")
        dur = pd.date_range(start, end, freq=f"{resol}s", tz="utc")

        data.index = dur
        data_source = DFData(data)

        input_params = ['Beam Solar Radiation [W/m2]',
                        'Diffuse Solar Radiation [W/m2]',
                        'Ground Solar Radiation [W/m2]',
                        'Radiation incidence angle [deg]',
                        'Ambient temperature [C]',
                        'Inlet temperature [C]',
                        'Inlet mass flow rate [kg/h]',
                        'q_demand_kw']
        result_params = [
            "beam_solar_radiation_cp",
            "diffuse_solar_radiation_cp",
            "ground_solar_radiation_cp",
            "radiation_incidence_angle_cp",
            "ambient_temperature_cp",
            "inlet_temperature_cp",
            "inlet_mass_flow_rate_cp",
            "q_demand_kw_cp"
        ]

        prosumer = create_empty_prosumer_container()

        period = create_period(prosumer, resol, start, end, "utc", "default")

        cp_index = create_controlled_const_profile(
            prosumer, input_params, result_params, data_source, period)

        st_index = create_controlled_solar_thermal(prosumer, name="solar_thermal_plant", level=1, order=0)

        # HeatDemand-Controller
        hd_index = create_controlled_heat_demand(
            prosumer,
            level=1,
            order=1,
            t_in_set_c=30,
            t_out_set_c=25,
        )

        GenericMapping(
            prosumer,
            initiator_id=cp_index,
            initiator_column=["beam_solar_radiation_cp",
                              "diffuse_solar_radiation_cp",
                              "ground_solar_radiation_cp",
                              "radiation_incidence_angle_cp",
                              "ambient_temperature_cp",
                              "inlet_temperature_cp",
                              "inlet_mass_flow_rate_cp"],
            responder_id=st_index,
            responder_column=['beam_solar_radiation_w_m2',
                              'diffuse_solar_radiation_w_m2',
                              'ground_solar_radiation_w_m2',
                              'radiation_incidence_angle_deg',
                              'ambient_temperature_C',
                              'inlet_temperature_C',
                              'inlet_mass_flow_rate_kg_h',
                              ]
        )

        GenericMapping(
            container=prosumer,
            initiator_id=cp_index,
            initiator_column="q_demand_kw_cp",
            responder_id=hd_index,
            responder_column="q_demand_kw",
        )

        GenericMapping(
            container=prosumer,
            initiator_id=st_index,
            initiator_column="energy_gain_W",
            responder_id=hd_index,
            responder_column="q_received_kw",
            order=0,
            conversion_function=lambda x: x / 1000,
        )

        run_timeseries(prosumer)

        df = prosumer.time_series.data_source.iloc[1].df

        # Einzelwerte prüfen
        assert df.loc["2020-01-01 00:00:00+00:00", "q_received_kw"] == pytest.approx(6.550240, rel=1e-6)
        assert df.loc["2020-01-01 01:00:00+00:00", "q_uncovered_kw"] == pytest.approx(18.590205, rel=1e-6)
        assert df.loc["2020-01-01 02:00:00+00:00", "q_received_kw"] == pytest.approx(-0.388631, rel=1e-6)
        assert df.loc["2020-01-01 03:00:00+00:00", "t_out_c"] == 0.0

        # Ganze Spalte prüfen
        expected_q_received = [6.550240, 1.409795, -0.388631, -0.530509]
        assert df["q_received_kw"].tolist() == pytest.approx(expected_q_received, rel=1e-6)

        # Komplettes DataFrame prüfen
        expected = pd.DataFrame({
            "q_received_kw": [6.550240, 1.409795, -0.388631, -0.530509],
            "q_uncovered_kw": [3.449760, 18.590205, 30.388631, 0.530509],
            "mdot_kg_per_s": [0.0, 0.0, 0.0, 0.0],
            "t_in_c": [0.0, 0.0, 0.0, 0.0],
            "t_out_c": [0.0, 0.0, 0.0, 0.0]
        }, index=df.index)

        pd.testing.assert_frame_equal(df, expected, rtol=1e-6)

    def test_fluidmix_mapping(self):
        data = pd.DataFrame({
            "Beam Solar Radiation [W/m2]": [800, 200, 0, 0],
            "Diffuse Solar Radiation [W/m2]": [200, 50, 0, 0],
            "Ground Solar Radiation [W/m2]": [50, 10, 0, 0],
            "Radiation incidence angle [deg]": [30, 30, 30, 30],
            "Ambient temperature [C]": [25, 20, 15, 10],
            "Inlet mass flow rate [kg/h]": [100, 100, 100, 100],
            "Inlet temperature [C]": [30, 30, 30, 30],
            "q_demand_kw": [10, 20, 30, 0]  # gewünschte Wärmelast
        })

        start = "2020-01-01 00:00:00"
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"{resol}s") - pd.Timedelta("1s")
        dur = pd.date_range(start, end, freq=f"{resol}s", tz="utc")

        data.index = dur
        data_source = DFData(data)

        input_params = ['Beam Solar Radiation [W/m2]',
                        'Diffuse Solar Radiation [W/m2]',
                        'Ground Solar Radiation [W/m2]',
                        'Radiation incidence angle [deg]',
                        'Ambient temperature [C]',
                        'Inlet temperature [C]',
                        'Inlet mass flow rate [kg/h]',
                        'q_demand_kw']
        result_params = [
            "beam_solar_radiation_cp",
            "diffuse_solar_radiation_cp",
            "ground_solar_radiation_cp",
            "radiation_incidence_angle_cp",
            "ambient_temperature_cp",
            "inlet_temperature_cp",
            "inlet_mass_flow_rate_cp",
            "q_demand_kw_cp"
        ]

        prosumer = create_empty_prosumer_container()

        period = create_period(prosumer, resol, start, end, "utc", "default")

        cp_index = create_controlled_const_profile(
            prosumer, input_params, result_params, data_source, period)

        st_index = create_controlled_solar_thermal(prosumer, name="solar_thermal_plant", level=1, order=0)

        # HeatDemand-Controller
        hd_index = create_controlled_heat_demand(
            prosumer,
            level=1,
            order=1,
            t_in_set_c=30,
            t_out_set_c=25,
        )

        GenericMapping(
            prosumer,
            initiator_id=cp_index,
            initiator_column=["beam_solar_radiation_cp",
                              "diffuse_solar_radiation_cp",
                              "ground_solar_radiation_cp",
                              "radiation_incidence_angle_cp",
                              "ambient_temperature_cp",
                              "inlet_temperature_cp",
                              "inlet_mass_flow_rate_cp"],
            responder_id=st_index,
            responder_column=['beam_solar_radiation_w_m2',
                              'diffuse_solar_radiation_w_m2',
                              'ground_solar_radiation_w_m2',
                              'radiation_incidence_angle_deg',
                              'ambient_temperature_C',
                              'inlet_temperature_C',
                              'inlet_mass_flow_rate_kg_h',
                              ]
        )

        GenericMapping(
            container=prosumer,
            initiator_id=cp_index,
            initiator_column="q_demand_kw_cp",
            responder_id=hd_index,
            responder_column="q_demand_kw",
        )

        FluidMixMapping(prosumer,
                        initiator_id=st_index,
                        responder_id=hd_index,
                        order=0)

        run_timeseries(prosumer)
        df = prosumer.time_series.data_source.iloc[1].df

        # Einzelwerte prüfen
        assert df.loc["2020-01-01 00:00:00+00:00", "q_received_kw"] == pytest.approx(7.136952, rel=1e-3)
        assert df.loc["2020-01-01 01:00:00+00:00", "t_out_c"] == 25.0

        # Ganze Spalte prüfen
        expected_q_received = [7.136952, 1.990310, 0.191985, 0.050065]
        assert df["q_received_kw"].tolist() == pytest.approx(expected_q_received, rel=1e-3)

        # Komplettes DataFrame prüfen
        expected = pd.DataFrame({
            "q_received_kw": [7.136952, 1.990310, 0.191985, 0.050065],
            "q_uncovered_kw": [2.863048, 18.009690, 29.808015, -0.050065],
            "mdot_kg_per_s": [0.027778, 0.027778, 0.027778, 0.027778],
            "t_in_c": [86.413554, 42.141779, 26.652939, 25.431024],
            "t_out_c": [25.0, 25.0, 25.0, 25.0]
        }, index=df.index)

        pd.testing.assert_frame_equal(df, expected, rtol=1e-3)
