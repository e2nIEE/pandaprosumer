"""
Test the HeatStorageController functionality.
"""
import pytest
import numpy as np
import pandas as pd
from pandaprosumer import (
    create_empty_prosumer_container, 
    create_period, 
    create_controlled_heat_storage,
    create_heat_storage,
    FluidMixMapping
)
from pandaprosumer.controller.models.heat_storage import HeatStorageController


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="test_period",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestHeatStorageController:
    """
    Tests the HeatStorageController functionality
    """

    def test_controller_creation(self):
        """
        Test the creation of a heat storage controller
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)
        
        # Create controller (this will also create the heat storage element)
        controller_index = create_controlled_heat_storage(
            prosumer, 
            period=period, 
            level=0, 
            order=0,
            e_capacity_kwh=100.0,
            capacity_kg=1000.0,
            t_tank_init_c=50.0,
            min_temp_c=40.0,
            max_temp_c=80.0,
            init_soc=0.5, 
            t_tank_init_c=50.0
        )
        
        # Verify controller was created
        assert controller_index is not None
        controller = prosumer.controller.iloc[controller_index].object
        assert isinstance(controller, HeatStorageController)
        assert controller._soc == 0.5
        assert controller._temperature == 50.0

    def test_fluid_mix_mode_detection(self):
        """
        Test the _use_fluid_mix_mode method
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)
        
        # Test with capacity_kg set (should use fluid mix mode)
        controller_index = create_controlled_heat_storage(
            prosumer, 
            period=period, 
            level=0, 
            order=0,
            e_capacity_kwh=100.0,
            capacity_kg=1000.0,
            t_tank_init_c=50.0
        )
        
        controller = prosumer.controller.iloc[controller_index].object
        assert controller._use_fluid_mix_mode(prosumer) == True
        
        # Test without capacity_kg (should use power-only mode)
        prosumer2 = create_empty_prosumer_container()
        period2 = _default_period(prosumer2)
        controller_index2 = create_controlled_heat_storage(
            prosumer2, 
            period=period2, 
            level=0, 
            order=0,
            e_capacity_kwh=100.0
        )
        
        controller2 = prosumer2.controller.iloc[controller_index2].object
        assert controller2._use_fluid_mix_mode(prosumer2) == False

    def test_t_m_to_receive_init_with_demand(self):
        """
        Test the _t_m_to_receive_init method when there is demand
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)
        
        controller_index = create_controlled_heat_storage(
            prosumer, 
            period=period, 
            level=0, 
            order=0,
            e_capacity_kwh=100.0,
            capacity_kg=1000.0,
            t_tank_init_c=50.0,
            min_temp_c=40.0,
            max_temp_c=80.0,
            t_tank_init_c=50.0
        )
        
        controller = prosumer.controller.iloc[controller_index].object
        
        # Mock the t_m_to_deliver method to return demand
        controller.t_m_to_deliver = lambda x: (60.0, 45.0, [1.0])
        
        # Test with demand
        t_feed, t_return, mdot = controller._t_m_to_receive_init(prosumer)
        
        # Should return demand temperature and calculated mass flow
        assert t_feed == 60.0
        assert t_return == 40.0  # min_temp_c
        assert mdot >= 1.0  # Should be at least the demand mass flow

    def test_t_m_to_receive_init_without_demand(self):
        """
        Test the _t_m_to_receive_init method when there is no demand
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)
        
        controller_index = create_controlled_heat_storage(
            prosumer, 
            period=period, 
            level=0, 
            order=0,
            e_capacity_kwh=100.0,
            capacity_kg=1000.0,
            t_tank_init_c=50.0,
            min_temp_c=40.0,
            max_temp_c=80.0,
            t_tank_init_c=50.0
        )
        
        controller = prosumer.controller.iloc[controller_index].object
        
        # Mock the t_m_to_deliver method to return no demand 
        controller.t_m_to_deliver = lambda x: (0., 0., [0.])
        
        # Test without demand
        t_feed, t_return, mdot = controller._t_m_to_receive_init(prosumer)
        
        # Should return max/min temperatures
        assert t_feed == 80.0  # max_temp_c
        assert t_return == 40.0  # min_temp_c
        assert mdot >= 0.0

    def test_soc_from_temperature(self):
        """
        Test the _soc_from_temperature method
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)
        
        controller_index = create_controlled_heat_storage(
            prosumer, 
            period=period, 
            level=0, 
            order=0,
            e_capacity_kwh=100.0,
            capacity_kg=1000.0,
            t_tank_init_c=50.0,
            min_temp_c=40.0,
            max_temp_c=80.0,
            t_tank_init_c=50.0
        )
        
        controller = prosumer.controller.iloc[controller_index].object
        
        # Test SOC calculation
        controller._temperature = 40.0  # min temp
        soc = controller._soc_from_temperature(prosumer)
        assert soc == 0.0
        
        controller._temperature = 80.0  # max temp
        soc = controller._soc_from_temperature(prosumer)
        assert soc == 1.0
        
        controller._temperature = 60.0  # middle
        soc = controller._soc_from_temperature(prosumer)
        assert soc == 0.5

    def test_fluid_mix_mode_without_fluid(self):
        """
        Test that the controller works in fluid mix mode even without fluid definition
        """
        prosumer = create_empty_prosumer_container()
        period = _default_period(prosumer)
        
        # Create heat storage without fluid
        controller_index = create_controlled_heat_storage(
            prosumer, 
            period=period, 
            level=0, 
            order=0,
            e_capacity_kwh=100.0,
            capacity_kg=1000.0,
            t_tank_init_c=50.0,
            min_temp_c=40.0,
            max_temp_c=80.0,
            t_tank_init_c=50.0
        )
        
        controller = prosumer.controller.iloc[controller_index].object
        
        # Should still work without fluid (uses default heat capacity)
        assert controller._use_fluid_mix_mode(prosumer) == True
        
        # Test _t_m_to_receive_init without fluid
        controller.t_m_to_deliver = lambda x: (0., 0., [0.])
        
        t_feed, t_return, mdot = controller._t_m_to_receive_init(prosumer)
        
        # Should work with default values
        assert t_feed == 80.0
        assert t_return == 40.0
        assert isinstance(mdot, float)
        