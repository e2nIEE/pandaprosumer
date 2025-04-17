import pytest

from pandaprosumer import HeatDemandControllerData
from pandaprosumer.create import (create_empty_prosumer_container, create_period,
create_ice_chp, create_booster_heat_pump, create_heat_storage, create_heat_demand)
import pandas as pd
import numpy as np
from pandas.testing import assert_frame_equal
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.controller.data_model import ConstProfileControllerData
from pandaprosumer.controller.data_model.ice_chp import IceChpControllerData
from pandaprosumer.controller.data_model import BoosterHeatPumpControllerData
from pandaprosumer.controller import HeatStorageControllerData
from pandaprosumer.controller import ConstProfileController, IceChpController, BoosterHeatPumpController, HeatDemandController, HeatStorageController
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries


class TestChpBhpStorageDemandMapping:

    def test_mapping(self):

        chp_size = 350
        chp_name = 'example_chp'
        altitude = 0
        fuel = 'ng'

        hp_type = "water-water1"
        hp_name = 'example_hp'

        q_capacity_kwh = 5000

        start = '2020-01-01 00:00:00'
        end = '2020-01-01 00:59:00'
        time_resolution = 15 * 60

        demand_data= pd.DataFrame({'cycle': [1, 1, 1, 1],
                      't_source_k': [278, 295, 295, 400],
                      'demand': [100, 100, 500, 500],
                      'mode': [1, 1, 1, 1],
                      't_intake_k': [273, 273, 273, 273]})

        dur = pd.date_range(start, end, freq="15min", tz='utc')
        demand_data.index = dur
        demand_input = DFData(demand_data)

        prosumer = create_empty_prosumer_container()

        period = create_period(prosumer, time_resolution, start, end, 'utc', 'default')

        chp_index = create_ice_chp(prosumer, chp_size, 'ng', altitude, name=chp_name)
        hp_index = create_booster_heat_pump(prosumer, hp_type, name=hp_name)
        heat_storage_index = create_heat_storage(prosumer, q_capacity_kwh=q_capacity_kwh, name='hst_controller')
        create_heat_demand(prosumer, scaling=1.0, name='heat_demand_controller')

        const_controller_data = ConstProfileControllerData(
            input_columns=['cycle', 't_source_k', 'demand', 'mode', 't_intake_k'],
            result_columns=["cycle_cp", 't_source_cp', "demand_cp", 'mode_cp', 't_intake_cp'],
            period_index=period
        )
        ice_chp_controller_data = IceChpControllerData(
            element_name='ice_chp',  # PM: copy of this here
            element_index=[chp_index],
            period_index=period
        )
        booster_heat_pump_controller_data = BoosterHeatPumpControllerData(
            element_name='booster_heat_pump',
            element_index=[hp_index],
            period_index=period
        )
        heat_demand_controller_data = HeatDemandControllerData(
            element_name='heat_demand',
            element_index=[0],
            period_index=period
        )
        heat_storage_controller_data = HeatStorageControllerData(
            element_name='heat_storage',
            element_index=[heat_storage_index],
            period_index=period
        )

        ConstProfileController(prosumer,
                               const_object=const_controller_data,
                               df_data=demand_input,
                               order=0,
                               level=0,
                               name='cp_ctrl')
        IceChpController(prosumer,
                         ice_chp_controller_data,
                         order=1,
                         level=0,
                         name='chp_ctrl')
        BoosterHeatPumpController(prosumer,
                                  booster_heat_pump_controller_data,
                                  order=2,
                                  level=0,
                                  name='bhp_ctr')
        HeatStorageController(prosumer,
                              heat_storage_controller_data,
                              order=3,
                              level=0,
                              name='hs_ctrl')
        HeatDemandController(prosumer,
                                   heat_demand_controller_data,
                                   order=4,
                                   level=0,
                                   name='kassel_ctrl')

        GenericMapping(
            prosumer,
            initiator_id=0,
            initiator_column="cycle_cp",
            responder_id=1,
            responder_column="cycle",
            order=0
        )
        GenericMapping(
            prosumer,
            initiator_id=0,
            initiator_column="t_intake_cp",
            responder_id=1,
            responder_column="t_intake_k",
            order=0
        )
        GenericMapping(
            prosumer,
            initiator_id=0,
            initiator_column="t_source_cp",
            responder_id=2,
            responder_column="t_source_k",
            order=0
        )
        GenericMapping(
            prosumer,
            initiator_id=0,
            initiator_column="mode_cp",
            responder_id=2,
            responder_column="mode",
            order=0
        )
        GenericMapping(
            prosumer,
            initiator_id=0,
            initiator_column="demand_cp",
            responder_id=4,
            responder_column="q_demand_kw",
            order=0
        )
        GenericMapping(
            prosumer,
            initiator_id=1,
            initiator_column="p_el_out_kw",
            responder_id=2,
            responder_column="p_received_kw",
            order=0
        )
        GenericMapping(
            prosumer,
            initiator_id=1,
            initiator_column="p_th_out_kw",
            responder_id=2,
            responder_column="q_received_kw",
            order=0
        )
        GenericMapping(
            prosumer,
            initiator_id=2,
            initiator_column="q_floor",
            responder_id=3,
            responder_column="q_received_kw",
            order=0
        )
        GenericMapping(
            prosumer,
            initiator_id=3,
            initiator_column="q_delivered_kw",
            responder_id=4,
            responder_column="q_received_kw",
            order=0
        )

        run_timeseries(prosumer, period)

        storage_data_res = {
            "soc": [0.0, 0.0, 0.0, 0.0],
            "q_delivered_kw": [6.85, 10.42, 10.42, 0.00]
        }

        chp_data_res = {
            'load': [100.0, 100.0, 100.0, 100.0],
            "p_in_kw": [875.0, 875.0, 875.0, 875.0],
            "p_el_out_kw": [350.0, 350.0, 350.0, 350.0],
            "p_th_out_kw": [305.78, 305.78, 305.78, 305.78],
            "p_rad_out_kw": [54.64, 54.64, 54.64, 54.64],
            "ice_chp_efficiency": [74.946286, 74.946286, 74.946286, 74.946286],
            "mdot_fuel_in_kg_per_s": [0.017117, 0.017117, 0.017117, 0.017117],
            "acc_m_fuel_in_kg": [15.404930, 30.809859, 46.214789, 61.619718],
            "acc_co2_equiv_kg": [50.75, 101.50, 152.25, 203.00],
            "acc_co2_inst_kg": [44.058099, 88.116197, 132.174296, 176.232394],
            "acc_nox_mg": [193725.0, 387450.0, 581175.0, 774900.0],
            "acc_time_ice_chp_oper_s": [900.0, 1800.0, 2700.0, 3600.0]
        }

        bhp_data_res = {
            "cop_floor": [3.965375, 5.210540, 5.210540, 0.000000],
            "cop_radiator": [3.590375, 5.260540, 5.260540, 0.000000],
            "p_el_floor": [350.0, 350.0, 350.0, 0.0],
            "p_el_radiator": [350.0, 350.0, 350.0, 0.0],
            "q_remain": [20093.15, 20089.58, 20489.58, 20500.0],
            "q_floor": [6.85, 10.42, 10.42, 0.00],
            "q_radiator": [6.85, 10.42, 10.42, 0.00]
        }

        chp_expected = pd.DataFrame(chp_data_res, index=dur)
        bhp_expected = pd.DataFrame(bhp_data_res, index=dur)
        storage_expected = pd.DataFrame(storage_data_res, index=dur)

        assert not np.isnan(prosumer.time_series.iloc[0].data_source.df).any().any()
        assert not np.isnan(prosumer.time_series.iloc[1].data_source.df).any().any()
        assert not np.isnan(prosumer.time_series.iloc[2].data_source.df).any().any()
        assert not np.isnan(prosumer.time_series.iloc[3].data_source.df).any().any()

        assert_frame_equal(prosumer.time_series.loc[0].data_source.df, chp_expected, check_dtype=False, rtol=0.01)
        assert_frame_equal(prosumer.time_series.loc[1].data_source.df, bhp_expected, check_dtype=False, rtol=0.01)
        assert_frame_equal(prosumer.time_series.loc[2].data_source.df, storage_expected, check_dtype=False, rtol=0.01)

        cop_floor = prosumer.time_series.loc[1].data_source.df.cop_floor
        cop_radiator = prosumer.time_series.loc[1].data_source.df.cop_radiator

        assert ((cop_floor >= 1.0) | (cop_floor==0.0)).all()
        assert ((cop_radiator >= 1.0) | (cop_radiator==0.0)).all()

        soc = prosumer.time_series.loc[2].data_source.df.soc

        assert ((1.0 >= soc) & (soc >= 0.0)).all()

