import pytest
from pandas.testing import assert_frame_equal
from pandaprosumer import *
from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping


class TestPvHeatDemandIntegration:

    def test_pv_heat_demand_mapping(self):
        """
        Integration test:

        - ConstProfileController reads a combined PV + heat-demand profile.
        - SenergyNetsPvProductionController receives PV inputs via GenericMapping
          and produces a PV time series
        - HeatDemandController receives:
            • q_demand_kw   from ConstProfileController
            • q_received_kw from the PV controller
        - uses GenericMapping
        """

        pv_power_kw = np.array([0.0, 0.5, 1.0, 0.5])
        poa_direct = np.array([0.0, 350.0, 700.0, 350.0])
        poa_sky_diffuse = np.array([0.0, 100.0, 200.0, 100.0])
        poa_ground_diffuse = np.array([0.0, 50.0, 100.0, 50.0])
        solar_elevation = np.array([0.0, 20.0, 40.0, 20.0])
        temp_air_c = np.array([5.0, 6.0, 7.0, 6.0])
        wind_speed = np.array([2.0, 2.0, 2.0, 2.0])
        solar_rad_reconstr_bool = np.ones_like(pv_power_kw, dtype=int)

        heat_demand_kw = np.array([2.0, 4.0, 6.0, 4.0])

        data = pd.DataFrame(
            {
                "PV Power [kW]": pv_power_kw,
                "POA Direct [W/m2]": poa_direct,
                "POA Sky Diffuse [W/m2]": poa_sky_diffuse,
                "POA Ground Diffuse [W/m2]": poa_ground_diffuse,
                "Solar Elevation [deg]": solar_elevation,
                "Ambient Temperature [C]": temp_air_c,
                "Wind Speed [m/s]": wind_speed,
                "Solar Rad Reconstructed [-]": solar_rad_reconstr_bool,
                "q_demand_kw": heat_demand_kw,
            }
        )

        start = "2020-01-01 00:00:00"
        resol = 900  # 15 min
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"{resol}s") - pd.Timedelta("1s")
        dur = pd.date_range(start, end, freq=f"{resol}s", tz="utc")

        data.index = dur
        data_source = DFData(data)

        input_params = [
            "PV Power [kW]",
            "POA Direct [W/m2]",
            "POA Sky Diffuse [W/m2]",
            "POA Ground Diffuse [W/m2]",
            "Solar Elevation [deg]",
            "Ambient Temperature [C]",
            "Wind Speed [m/s]",
            "Solar Rad Reconstructed [-]",
            "q_demand_kw",
        ]

        result_params = [
            "p_w_cp",
            "poa_direct_w_m2_cp",
            "poa_sky_diffuse_w_m2_cp",
            "poa_ground_diffuse_w_m2_cp",
            "solar_elevation_deg_cp",
            "temp_air_c_cp",
            "wind_speed_m_s_cp",
            "solar_rad_reconstr_bool_cp",
            "q_demand_kw_cp",
        ]

        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, resol, start, end, "utc", "default")

        cp_index = create_controlled_const_profile(prosumer, input_params, result_params, data_source, period)


        pv_index = create_controlled_pv_production(prosumer, latitude=40.0, longitude=0.0, peakpower=5.0, loss=10.0, name="pv_rooftop_1", level=1, order=0, period=period)

        hd_index = create_controlled_heat_demand(
            prosumer,
            level=1,
            order=1,
            t_in_set_c=30,
            t_out_set_c=25
        )

        GenericMapping(
            prosumer,
            initiator_id=cp_index,
            initiator_column=[
                "p_w_cp",
                "poa_direct_w_m2_cp",
                "poa_sky_diffuse_w_m2_cp",
                "poa_ground_diffuse_w_m2_cp",
                "solar_elevation_deg_cp",
                "temp_air_c_cp",
                "wind_speed_m_s_cp",
                "solar_rad_reconstr_bool_cp",
            ],
            responder_id=pv_index,
            responder_column=[
                "p_w",
                "poa_direct_w_m2",
                "poa_sky_diffuse_w_m2",
                "poa_ground_diffuse_w_m2",
                "solar_elevation_deg",
                "temp_air_c",
                "wind_speed_m_s",
                "solar_rad_reconstr_bool"
            ]
        )

        GenericMapping(
            container=prosumer,
            initiator_id=cp_index,
            initiator_column="q_demand_kw_cp",
            responder_id=hd_index,
            responder_column="q_demand_kw"
        )

        GenericMapping(
            container=prosumer,
            initiator_id=pv_index,
            initiator_column="p_w",
            responder_id=hd_index,
            responder_column="q_received_kw",
            order=0
        )

        run_timeseries(prosumer)

        assert len(prosumer.time_series) == 2

        for i in range(len(prosumer.time_series)):
            df = prosumer.time_series.data_source.iloc[i].df
            assert not np.isnan(df).any().any(), f"NaNs found in time_series {i}"

        pv_expected = pd.DataFrame(
            index=dur,
            data={
                "p_w": pv_power_kw,
                "poa_direct_w_m2": poa_direct,
                "poa_sky_diffuse_w_m2": poa_sky_diffuse,
                "poa_ground_diffuse_w_m2": poa_ground_diffuse,
                "solar_elevation_deg": solar_elevation,
                "temp_air_c": temp_air_c,
                "wind_speed_m_s": wind_speed,
                "solar_rad_reconstr_bool": solar_rad_reconstr_bool,
            },
        )

        pv_ts_df = prosumer.time_series.data_source.iloc[0].df

        assert_frame_equal(
            pv_ts_df[pv_expected.columns],
            pv_expected,
            check_dtype=False,
            rtol=1e-3,
        )

        heat_ts_df = prosumer.time_series.data_source.iloc[1].df
        assert {"q_received_kw", "q_uncovered_kw"}.issubset(heat_ts_df.columns)

        assert np.allclose(
            heat_ts_df["q_received_kw"].values,
            pv_power_kw,
            rtol=1e-3,
        )

        assert np.allclose(
            heat_ts_df["q_received_kw"].values
            + heat_ts_df["q_uncovered_kw"].values,
            heat_demand_kw,
            rtol=1e-3,
        )
