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

    def test_mapping(self):
        prosumer = create_empty_prosumer_container(self)

        # Eingangszeitreihe für die SolarThermal-Anlage
        data = pd.DataFrame({
            "beam_solar_radiation_w_m2": [800, 200, 0, 0],
            "diffuse_solar_radiation_w_m2": [200, 50, 0, 0],
            "ground_solar_radiation_w_m2": [50, 10, 0, 0],
            "radiation_incidence_angle_deg": [30, 30, 30, 30],
            "ambient_temperature_C": [25, 20, 15, 10],
            "inlet_mass_flow_rate_kg_h": [100, 100, 100, 100],
            "inlet_temperature_C": [30, 30, 30, 30],
            "q_demand_kw": [10, 20, 30, 0]  # gewünschte Wärmelast
        })

        start = "2020-01-01 00:00:00"
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"{resol}s") - pd.Timedelta("1s")
        dur = pd.date_range(start, end, freq=f"{resol}s", tz="utc")
        period = create_period(prosumer, resol, start, end, "utc", "default")

        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ['Beam Solar Radiation [W/m2]',
                        'Diffuse Solar Radiation [W/m2]',
                        'Ground Solar Radiation [W/m2]',
                        'Radiation incidence angle [deg]',
                        'Ambient temperature [C]',
                        'Inlet temperature [C]',
                        'Inlet mass flow rate [kg/h]']
        cp_result_columns = [
            "beam_solar_radiation_cp",
            "diffuse_solar_radiation_cp",
            "ground_solar_radiation_cp",
            "radiation_incidence_angle_cp",
            "ambient_temperature_cp",
            "inlet_temperature_cp",
            "inlet_mass_flow_rate_cp"
        ]


        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              data_source,period, 0,0)
        # SolarThermal-Controller
        st_controller_idx = create_controlled_solar_thermal(
            prosumer,
            level=1,
            order=0,
            period=period,
            **_default_argument()
        )

        # HeatDemand-Controller
        hd_controller_idx = create_controlled_heat_demand(
            prosumer,
            level=1,
            order=1,
            t_in_set_c=30,
            t_out_set_c=25,
            period=period
        )

        GenericMapping(
            prosumer,
            initiator_id=cp_controller_index,
            initiator_column=["beam_solar_radiation_cp",
                              "diffuse_solar_radiation_cp",
                              "ground_solar_radiation_cp",
                              "radiation_incidence_angle_cp",
                              "ambient_temperature_cp",
                              "inlet_temperature_cp",
                              "inlet_mass_flow_rate_cp"],
            responder_id=st_controller_idx,
            responder_column=['beam_solar_radiation_w_m2',
                              'diffuse_solar_radiation_w_m2',
                              'ground_solar_radiation_w_m2',
                              'radiation_incidence_angle_deg',
                              'ambient_temperature_C',
                              'inlet_temperature_C',
                              'inlet_mass_flow_rate_kg_h',
                              ]
        )
        # Mapping: SolarThermal liefert Energie an HeatDemand
        GenericMapping(
            container=prosumer,
            initiator_id=st_controller_idx,
            initiator_column="energy_gain_W",
            responder_id=hd_controller_idx,
            responder_column="q_demand_kw",
            order=0
        )

        run_timeseries(prosumer, period, True)

        # Erwartete Ergebnisse (vereinfacht, nur Struktur)
        st_results = prosumer.time_series.loc[0].data_source.df
        hd_results = prosumer.time_series.loc[1].data_source.df

        # Sicherstellen, dass keine NaNs auftreten
        assert not st_results.isna().any().any()
        assert not hd_results.isna().any().any()

        # Konsistenzprüfung: die an HeatDemand übergebene Leistung entspricht der SolarThermal-Leistung
        assert_series_equal(
            hd_results.q_demand_kw,
            st_results.energy_gain_W / 1000.0,  # W → kW
            rtol=0.05,
            check_names=False
        )

        # Massenstrom bleibt erhalten
        assert hd_results.mdot_kg_per_s.values == pytest.approx(
            st_results.outlet_flow_rate_kg_h.values / 3600.0, rel=1e-3
        )