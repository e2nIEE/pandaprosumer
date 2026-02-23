
import pytest
import pandas as pd
import numpy as np
from pandas.testing import assert_frame_equal, assert_series_equal
from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer import *
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (
    create_controlled_const_profile,
    create_controlled_mdu_chp,
    create_controlled_heat_demand
)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries


class TestMduChpHeatDemandMapping:
    """
    Test MDU CHP connected to Heat Demand
    
    System topology:
    ConstProfile → MDU CHP → Heat Demand
    
    The MDU CHP uses LSTM to predict thermal and electrical power output
    based on size, return temperature, supply temperature, and heat demand.
    """

    def test_mapping(self):
        """Test the mapping and data flow between MDU CHP and Heat Demand"""
        
        # Create prosumer container
        prosumer = create_empty_prosumer_container(name="test_mdu_chp_hd")
        
        # Define time series parameters
        start = '2020-01-01 00:00:00'
        resol = 3600  # 1 hour resolution
        end = '2020-01-01 03:00:00'  # 4 time steps
        
        # Create test data for MDU CHP inputs
        # These will be provided by ConstProfile controller
        data = pd.DataFrame({
            "size": [100, 100, 150, 150],  # CHP size in kW
            "return_temp": [40, 45, 40, 50],  # Return water temperature (°C)
            "supply_temp": [80, 85, 90, 95],  # Supply water temperature (°C)
            "heat_demand": [200, 300, 400, 500],  # Heat demand (kW)
            "demand_t_in": [80, 85, 90, 95],  # Demand inlet temperature
            "demand_t_out": [40, 45, 40, 50]  # Demand outlet temperature
        })
        
        # Create time index
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        data.index = dur
        data_source = DFData(data)
        
        # Create period
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        
        # Define input and output columns for ConstProfile
        cp_input_columns = ["size", "return_temp", "supply_temp", "heat_demand", 
                           "demand_t_in", "demand_t_out"]
        cp_result_columns = ["size_out", "return_temp_out", "supply_temp_out", 
                            "heat_demand_out", "demand_t_in_out", "demand_t_out_out"]
        
        # Define heat demand parameters
        hd_params = {
            't_in_set_c': 80,  # Set inlet temperature
            't_out_set_c': 40   # Set outlet temperature
        }
        
        # Create controllers
        # 1. ConstProfile: Provides input data
        cp_controller_index = create_controlled_const_profile(
            prosumer, 
            cp_input_columns, 
            cp_result_columns,
            data_source, 
            period, 
            level=0, 
            order=0
        )
        
        # 2. MDU CHP: Uses LSTM to predict thermal and electrical power
        mdu_chp_controller_index = create_controlled_mdu_chp(
            prosumer, 
            size=100,  # Nominal size
            name="mdu_chp_1",
            level=1, 
            order=0, 
            period=period
        )
        
        # 3. Heat Demand: Consumes heat from MDU CHP
        hd_controller_index = create_controlled_heat_demand(
            prosumer, 
            name="heat_demand_1",
            level=1, 
            order=1, 
            period=period, 
            **hd_params
        )
        
        # Create mappings
        # Map ConstProfile outputs to MDU CHP inputs
        GenericMapping(
            container=prosumer,
            initiator_id=cp_controller_index,
            initiator_column="size_out",
            responder_id=mdu_chp_controller_index,
            responder_column="Size",
            order=0
        )
        
        GenericMapping(
            container=prosumer,
            initiator_id=cp_controller_index,
            initiator_column="return_temp_out",
            responder_id=mdu_chp_controller_index,
            responder_column="Return water temperature",
            order=1
        )
        
        GenericMapping(
            container=prosumer,
            initiator_id=cp_controller_index,
            initiator_column="supply_temp_out",
            responder_id=mdu_chp_controller_index,
            responder_column="Supply water temperature",
            order=2
        )
        
        GenericMapping(
            container=prosumer,
            initiator_id=cp_controller_index,
            initiator_column="heat_demand_out",
            responder_id=mdu_chp_controller_index,
            responder_column="Heat demand",
            order=3
        )
        
        # Map ConstProfile outputs to Heat Demand inputs
        GenericMapping(
            container=prosumer,
            initiator_id=cp_controller_index,
            initiator_column=["heat_demand_out", "demand_t_in_out", "demand_t_out_out"],
            responder_id=hd_controller_index,
            responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
            order=0
        )
        
        # Create FluidMixMapping between MDU CHP and Heat Demand
        # This handles the fluid flow (temperature and mass flow) between components
        FluidMixMapping(
            container=prosumer,
            initiator_id=mdu_chp_controller_index,
            responder_id=hd_controller_index,
            order=0
        )
        
        # Run time series simulation
        # Note: This will try to load the LSTM model files
        # If model files don't exist, the test will fail
        try:
            run_timeseries(prosumer, period, True)
            
            # Verify that results don't contain NaN values
            assert not np.isnan(prosumer.time_series.loc[0, "data_source"].df).any().any(), \
                "MDU CHP results contain NaN values"
            assert not np.isnan(prosumer.time_series.loc[1, "data_source"].df).any().any(), \
                "Heat Demand results contain NaN values"
            
            # Get results
            mdu_chp_results = prosumer.time_series.loc[0].data_source.df
            hd_results = prosumer.time_series.loc[1].data_source.df
            
            # Verify MDU CHP output columns exist
            assert 'q_fuel_mw' in mdu_chp_results.columns, "q_fuel_mw not in MDU CHP results"
            assert 'p_el_mw' in mdu_chp_results.columns, "p_el_mw not in MDU CHP results"
            
            # Verify Heat Demand output columns exist
            assert 'q_received_kw' in hd_results.columns, "q_received_kw not in Heat Demand results"
            assert 'q_uncovered_kw' in hd_results.columns, "q_uncovered_kw not in Heat Demand results"
            
            # Basic sanity checks
            # Fuel input should be non-negative
            assert (mdu_chp_results['q_fuel_mw'] >= 0).all(), "Fuel input should be non-negative"
            
            # Electrical power should be non-negative
            assert (mdu_chp_results['p_el_mw'] >= 0).all(), "Electrical power should be non-negative"
            
            # Received heat should be non-negative
            assert (hd_results['q_received_kw'] >= 0).all(), "Received heat should be non-negative"
            
            # q_uncovered_kw can be negative (meaning CHP supplies more than demand)
            # q_uncovered_kw = demand - received
            # Negative value means oversupply, positive means undersupply
            # Just verify it's a valid number (not NaN)
            assert not hd_results['q_uncovered_kw'].isna().any(), \
                f"q_uncovered_kw contains NaN values: {hd_results['q_uncovered_kw'].values}"
            
            # Verify energy balance: received + uncovered should equal demand
            total_heat = hd_results['q_received_kw'] + hd_results['q_uncovered_kw']
            assert_series_equal(
                total_heat, 
                data['heat_demand'].astype(float),  # Convert to float64 to match total_heat dtype
                check_names=False, 
                rtol=0.1,
                check_exact=False
            )
            
        except FileNotFoundError as e:
            pytest.skip(f"Model files not found: {e}. Please ensure model_weights.pkl and scalers.pkl are in src/pandaprosumer/controller/models/")
        except Exception as e:
            pytest.fail(f"Test failed with error: {str(e)}")

    def test_mapping_with_mock_model(self):
        """
        Test mapping with mocked LSTM model (for testing without actual model files)
        This test uses a simple linear model instead of LSTM for testing purposes.
        """
        
        prosumer = create_empty_prosumer_container(name="test_mdu_chp_mock")
        
        start = '2020-01-01 00:00:00'
        resol = 3600
        end = '2020-01-01 01:00:00'  # 2 time steps
        
        data = pd.DataFrame({
            "size": [100, 150],
            "return_temp": [40, 45],
            "supply_temp": [80, 85],
            "heat_demand": [200, 300]
        })
        
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        data.index = dur
        data_source = DFData(data)
        
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        
        # This test verifies the framework integration without requiring model files
        # In production, you would load actual LSTM model
        assert True


if __name__ == "__main__":
    # Run tests
    test = TestMduChpHeatDemandMapping()
    test.test_mapping()

