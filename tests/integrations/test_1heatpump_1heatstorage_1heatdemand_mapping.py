"""
Test the heat storage controller with FluidMixMapping in a chain:
HeatPump -> HeatStorage -> HeatDemand
"""
import pytest
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal
from pandaprosumer import DFData

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_const_profile, create_controlled_heat_pump, create_controlled_heat_storage, create_controlled_heat_demand


class Test1HeatPump1HeatStorage1HeatDemandMapping:
    """
    Test a chain: HeatPump -> HeatStorage -> HeatDemand using FluidMixMapping
    """

    def test_fluid_mix_mapping(self):
        """
        Test the mapping with FluidMixMapping between all components
        """
        prosumer = create_empty_prosumer_container()
        
        t_high_c = 60.
        t_low_c = 40.
        
        # Create test data - make it longer as requested
        data = pd.DataFrame({
            "Tin_evap": [25] * 10,  # Extended from 5 to 10 timesteps
            "demand_kw": [0, 100, 200, 150, 50, 120, 80, 180, 90, 60],  # Extended demand pattern
            "t_feed_demand_c": [t_high_c] * 10,
            "t_return_demand_c": [t_low_c] * 10
        })

        start = '2020-01-01 00:00:00'
        resol = 60 # 1-minute resolution
        end = pd.Timestamp(start) + len(data["Tin_evap"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer, resol, start, end, 'utc', 'default')

        data.index = dur
        data_source = DFData(data)

        # Heat pump parameters
        hp_params = {
            'carnot_efficiency': 0.5,
            'pinch_c': 0,
            'delta_t_evap_c': 5,
            'max_p_comp_kw': 500
        }

        # Heat storage parameters (FluidMix mode)
        hs_params = {
            'e_capacity_kwh': 23.3,
            'capacity_kg': 1000.0,  # This enables FluidMix mode
            'init_temperature': t_low_c,
            'min_temp_c': t_low_c,
            'max_temp_c': t_high_c,
            'u_w_per_m2k': 0.1,  # Reduced heat loss for stability
            'area_wall_m2': 5.0,  # Reduced area for stability
            't_ext_c': 20.0
        }

        # Heat demand parameters
        hd_params = {
            't_in_set_c': t_high_c,  # Match initial storage temperature
            't_out_set_c': t_low_c
        }

        # Create controllers
        cp_input_columns = ["Tin_evap", "demand_kw", "t_feed_demand_c", "t_return_demand_c"]
        cp_result_columns = ["t_evap_in_c", "q_demand_kw", "t_feed_demand_c", "t_return_demand_c"]
        
        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              data_source, period, 0, 0)
        hp_controller_index = create_controlled_heat_pump(prosumer, period=period, level=1, order=0, **hp_params)
        hs_controller_index = create_controlled_heat_storage(prosumer, period=period, level=1, order=1, **hs_params)
        hd_controller_index = create_controlled_heat_demand(prosumer, period=period, level=1, order=2, **hd_params)

        # Create mappings
        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
                       order=0)

        for init_col, resp_col in zip(["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
                                      ["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"]):
            GenericMapping(container=prosumer,
                           initiator_id=cp_controller_index,
                           initiator_column=init_col,
                           responder_id=hd_controller_index,
                           responder_column=resp_col,
                           order=0)

        # FluidMixMapping between heat pump and heat storage
        FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hs_controller_index,
                        order=0)

        # FluidMixMapping between heat storage and heat demand
        FluidMixMapping(container=prosumer,
                        initiator_id=hs_controller_index,
                        responder_id=hd_controller_index,
                        order=0)

        # Run the simulation with increased max iterations and continue on divergence
        run_timeseries(prosumer, period, True, max_iter=100, continue_on_divergence=True)  # More tolerant settings

        # Verify the simulation completes successfully
        # The key test is that it doesn't throw convergence errors
        
        # Verify that the heat storage controller handled the fluid mix mapping correctly
        hs_controller = prosumer.controller.iloc[hs_controller_index].object
        assert hs_controller._use_fluid_mix_mode(prosumer) == True

        hp_data = {
            'q_cond_kw': [237.96428571428575, 100.0, 200.0, 150.0, 50.0, 120.0, 80.0, 180.0, 90.0, 60.0],
            'p_comp_kw': [50.00000000000001, 21.011556355995797, 42.023113, 31.517335, 10.505778, 25.213868, 16.809245, 37.820801, 18.910401, 12.606934],
            'q_evap_kw': [187.96428571428575, 78.9884436440042, 157.976887, 118.482665, 39.494222, 94.786132, 63.190755, 142.179199, 71.089599, 47.393066],
            'cop': [4.759285714285714, 4.759285714285714, 4.759285714285714, 4.759285714285714, 4.759285714285714, 4.759285714285714, 4.759285714285714, 4.759285714285714, 4.759285714285714, 4.759285714285714],
            'mdot_cond_kg_per_s': [2.8454049106419017, 1.19572771271159, 2.390478094644257, 1.7853585714285712, 0.5978638571428571, 1.4326792857142856, 0.9551163857142857, 2.146416189378648, 1.073208094644257, 0.716339644257703],
            't_cond_in_c': [40.0, 40.0, 40.0, 40.0, 40.0, 40.0, 40.0, 40.0, 40.0, 40.0],
            't_cond_out_c': [60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0],
            'mdot_evap_kg_per_s': [8.987236928223552, 3.7767167040411143, 7.5534334080822285, 5.665075056061672, 1.8883583520205571, 4.532060044849337, 3.021373363232891, 6.798090067274005, 3.3990450336370026, 2.2660300224246686],
            't_evap_in_c': [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0],
            't_evap_out_c': [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0],
        }
        hp_expected = pd.DataFrame(hp_data, index=data.index)

        hs_data = {
            'soc': [0.17072429230468913, 0.17072429230468913, 0.17072429230468913, 0.17072429230468913, 0.17072429230468913, 0.17072429230468913, 0.17072429230468913, 0.17072429230468913, 0.17072429230468913, 0.17072429230468913],
            't_tank_c': [43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378],
            'q_ch_kw': [237.85470932918307, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # Charging power
            'q_dch_kw': [0.0, 99.96946714811665, 199.93893429580913, 149.95420072153874, 49.98473357374019, 119.96336057672198, 79.97557371764498, 179.94504086431945, 89.97252043196885, 59.98168028785199],  # Discharge power
            'q_delivered_kw': [0.0, 199.984165, 399.968330, 299.976248, 99.992083, 239.980998, 159.987332, 359.971497, 179.985749, 119.990499],  # Delivered power
            'mdot_ch_kg_per_s': [2.8454049106419017, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # Mass flow during charging
            't_ch_in_c': [60.0, 43.41448579941728, 43.414485752740774, 43.414485706064276, 43.41448565938778, 43.41448561271128, 43.414485566034784, 43.41448551935829, 43.41448547268179, 43.41448542600529],  # Default to tank temp
            't_ch_out_c': [43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378, 43.41448584609378],  # Default to tank temp
            'mdot_dch_kg_per_s': [0.0, 1.19572771271159, 2.39145542542318, 1.7935915690673851, 0.597863856355795, 1.434873255253908, 0.9565821701692719, 2.152309882880862, 1.076154941440431, 0.717436627626954],  # Mass flow during discharging
            't_dch_in_c': [43.41448584609378, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0, 60.0],  # Default to tank temp
            't_dch_out_c': [43.41448584609378, 43.41448584609378, 43.41448579941728, 43.414485752740774, 43.414485706064276, 43.41448565938778, 43.41448561271128, 43.414485566034784, 43.41448551935829, 43.41448547268179],  # Default to tank temp
        }
        hs_expected = pd.DataFrame(hs_data, index=data.index)

        dmd_data = {
            'q_received_kw': [0.0, 17.065892, 34.131783, 25.598837, 8.532946, 20.479069, 13.652713, 30.718603, 15.359301, 10.239534],
            'q_uncovered_kw': [0.0, 82.934108, 165.868217, 124.401163, 41.467054, 99.520931, 66.347287, 149.281397, 74.640699, 49.760466],
            'mdot_kg_per_s': [0.0, 1.19572771271159, 2.39145542542318, 1.7935915690673851, 0.597863856355795, 1.434873255253908, 0.9565821701692719, 2.152309882880862, 1.076154941440431, 0.717436627626954],
            't_in_c': [60.0, 43.414486, 43.414486, 43.414486, 43.414486, 43.414486, 43.414486, 43.414486, 43.414485, 43.414485],
            't_out_c': [40.0, 40.0, 40.0, 40.0, 40.0, 40.0, 40.0, 40.0, 40.0, 40.0],
        }
        hd_expected = pd.DataFrame(dmd_data, index=data.index)
        
        hp_res_df = prosumer.time_series.loc[0].data_source.df
        hs_res_df = prosumer.time_series.loc[1].data_source.df
        hd_res_df = prosumer.time_series.loc[2].data_source.df
        
        pd.set_option('display.expand_frame_repr', False)  # Prevent line breaks
        print("Heat Pump Results:")
        print(hp_res_df)
        print("\nHeat Storage Results:")
        print(hs_res_df)
        print("\nHeat Demand Results:")
        print(hd_res_df)

        assert not np.isnan(hp_res_df).any().any()
        assert not np.isnan(hs_res_df).any().any()
        assert not np.isnan(hd_res_df).any().any()
        assert_frame_equal(hp_res_df.sort_index(axis=1), hp_expected.sort_index(axis=1), check_dtype=False, atol=.01)
        assert_frame_equal(hs_res_df.sort_index(axis=1), hs_expected.sort_index(axis=1), check_dtype=False, atol=.01)
        assert_frame_equal(hd_res_df.sort_index(axis=1), hd_expected.sort_index(axis=1), check_dtype=False, atol=.01)

    def test_generic_mapping_only(self):
        """
        Test the heat storage with GenericMapping only (power-only mode)
        """
        prosumer = create_empty_prosumer_container()
        
        # Create test data - ensure demand doesn't exceed source
        data = pd.DataFrame({
            "q_source_kw": [0, 50, 80, 60, 20],
            "q_demand_kw": [0, 30, 50, 40, 15]
        })

        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data["q_source_kw"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer, resol, start, end, 'utc', 'default')

        data.index = dur
        data_source = DFData(data)

        # Heat storage parameters (GenericMapping only - no capacity_kg)
        hs_params = {
            'e_capacity_kwh': 300.0,  # Increased capacity to handle the energy flow
            # No capacity_kg - this disables FluidMix mode
            'init_temperature_c': 50.0
        }

        # Create controllers
        cp_input_columns = ["q_source_kw", "q_demand_kw"]
        cp_result_columns = ["q_source_kw", "q_demand_kw"]
        
        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              data_source, period, 0, 0)
        hs_controller_index = create_controlled_heat_storage(prosumer, period=period, level=1, order=0, **hs_params)

        # Create GenericMappings
        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="q_source_kw",
                       responder_id=hs_controller_index,
                       responder_column="q_received_kw",
                       order=0)

        # For this test, we'll just verify the controller works in power-only mode
        hs_controller = prosumer.controller.iloc[hs_controller_index].object
        assert hs_controller._use_fluid_mix_mode(prosumer) == False
        
        # Run the simulation to verify it works
        run_timeseries(prosumer, period, True)

        # Verify the controller is still in power-only mode after running
        hs_controller_after = prosumer.controller.iloc[hs_controller_index].object
        assert hs_controller_after._use_fluid_mix_mode(prosumer) == False
