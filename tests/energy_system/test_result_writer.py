import os
import tempfile
import pandas as pd
import pandapower
import pandapipes

from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.create_controlled import create_controlled_const_profile
from pandaprosumer.energy_system import create_empty_energy_system, add_net_to_energy_system, \
    add_pandaprosumer_to_energy_system
from pandaprosumer.energy_system.energy_system import save_energy_system_results
from pandaprosumer.pandaprosumer_container import save_prosumer_results
from pandaprosumer.create import create_empty_prosumer_container
from tests.data_sources import define_and_get_period_and_data_source


def _create_simple_pipes_network():
    """Create a simple pandapipes network for testing."""
    net = pandapipes.create_empty_network(fluid="water", name='test_pipes_net')
    t_amb_k = 293
    pandapipes.set_user_pf_options(net, ambient_temperature=t_amb_k, mode='bidirectional')

    # Create junctions
    j0 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 1))
    j1 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(2, 1))

    # Create pipe
    pandapipes.create_pipes_from_parameters(net, from_junctions=[j0], to_junctions=[j1], length_km=0.1,
                                            diameter_m=0.05, u_w_per_m2k=10, text_k=t_amb_k)
    return net


def _create_simple_power_network():
    """Create a simple pandapower network for testing."""
    net = pandapower.create_empty_network(name='test_power_net')
    b1 = pandapower.create_bus(net, vn_kv=20.)
    b2 = pandapower.create_bus(net, vn_kv=20.)
    pandapower.create_line(net, from_bus=b1, to_bus=b2, length_km=2.5, std_type="NAYY 4x50 SE")
    pandapower.create_ext_grid(net, bus=b1)
    pandapower.create_load(net, bus=b2, p_mw=0.1)
    return net


def _create_simple_prosumer_with_timeseries():
    """Create a simple prosumer with mock time series data for testing."""
    import pandas as pd
    from unittest.mock import Mock
    
    prosumer = create_empty_prosumer_container(name='test_prosumer', check_order=False)
    
    # Create a mock period
    period_df = pd.DataFrame([{
        'name': 'test_period',
        'start': '2023-01-01',
        'end': '2023-01-02',
        'resolution_s': 3600,
        'timezone': 'UTC'
    }])
    prosumer.period = period_df
    
    # Create mock time series data
    test_df = pd.DataFrame({
        'p_comp_kw': [100, 200, 300],
        'q_cond_kw': [250, 300, 350]
    }, index=pd.date_range("2023-01-01", periods=3, freq="1h"))
    
    # Create a mock time series entry
    mock_ts_entry = Mock()
    mock_ts_entry.element = "heat_pump"
    mock_ts_entry.element_index = 0
    mock_ts_entry.name = "hp_results"
    mock_ts_entry.data_source = Mock()
    mock_ts_entry.data_source.df = test_df
    
    # Add the mock time series entry to the prosumer
    new_row = pd.DataFrame([{
        'name': 'hp_results',
        'element': 'heat_pump',
        'element_index': 0,
        'period_index': 0,
        'data_source': mock_ts_entry.data_source
    }])
    
    if len(prosumer.time_series) == 0:
        prosumer.time_series = new_row
    else:
        prosumer.time_series = pd.concat([prosumer.time_series, new_row], ignore_index=True)
    
    return prosumer


def _create_energy_system_with_output_writers(nets, prosumers, temp_dir, name="test_energy_system"):
    """Create energy system with OutputWriter initialization."""
    energy_system = create_empty_energy_system(name=name)
    sample_prosumer_period = prosumers[0].period
    
    # Create time steps for OutputWriter
    time_steps = pd.date_range(
        sample_prosumer_period.iloc[0]["start"], 
        sample_prosumer_period.iloc[0]["end"],
        freq='%ss' % int(sample_prosumer_period.iloc[0]["resolution_s"]),
        tz=sample_prosumer_period.iloc[0]["timezone"]
    )
    
    # Add networks with OutputWriter
    for net in nets:
        net_output_path = os.path.join(temp_dir, "networks", net.__class__.__name__.lower(), net.name)
        add_net_to_energy_system(
            energy_system, 
            net, 
            net_name=net.name,
            output_path=net_output_path,
            time_steps=time_steps
        )
    
    # Add prosumers
    for prosumer in prosumers:
        add_pandaprosumer_to_energy_system(energy_system, prosumer, pandaprosumer_name=prosumer.name)
    
    return energy_system


class TestResultWriter:
    """
    Test the result writer functions for prosumers and energy systems.
    """

    def test_save_prosumer_results(self):
        """Test saving prosumer results to files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a simple prosumer with mock time series data
            prosumer = _create_simple_prosumer_with_timeseries()
            
            # Save prosumer results
            save_prosumer_results(prosumer, temp_dir)
            
            # Check if results were saved
            expected_path = os.path.join(temp_dir, "prosumers", prosumer.name)
            assert os.path.exists(expected_path), f"Prosumer results directory not created: {expected_path}"
            
            # Check if time series files were created
            time_series_files = []
            for root, dirs, files in os.walk(expected_path):
                for file in files:
                    if file.endswith('.csv'):
                        time_series_files.append(file)
            
            assert len(time_series_files) > 0, "No time series CSV files found"

    def test_save_energy_system_results(self):
        """Test saving energy system results."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create networks and prosumers
            net_pipes = _create_simple_pipes_network()
            net_power = _create_simple_power_network()
            prosumer = _create_simple_prosumer_with_timeseries()
            
            # Create energy system with OutputWriter
            energy_system = _create_energy_system_with_output_writers(
                [net_pipes, net_power], 
                [prosumer], 
                temp_dir
            )
            
            # Save energy system results
            sample_period = {'start': '2023-01-01', 'end': '2023-01-02', 'resolution_s': 3600, 'timezone': 'UTC'}
            save_energy_system_results(energy_system, temp_dir, sample_period)
            
            # Check if prosumer results were saved
            prosumer_path = os.path.join(temp_dir, "prosumers", prosumer.name)
            assert os.path.exists(prosumer_path), "Prosumer results not saved"
            
            # Check if network output directories were created
            pipes_path = os.path.join(temp_dir, "networks", "pandapipesnet", net_pipes.name)
            power_path = os.path.join(temp_dir, "networks", "pandapowernet", net_power.name)
            
            assert os.path.exists(pipes_path), "Pandapipes network output directory not created"
            assert os.path.exists(power_path), "Pandapower network output directory not created"

    def test_output_writer_element_validation(self):
        """Test that OutputWriter only logs variables for existing elements."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a pandapower network with only buses (no lines)
            net_power = pandapower.create_empty_network(name='test_power_simple')
            pandapower.create_bus(net_power, vn_kv=20.)
            
            # Create a pandapipes network with only junctions (no other elements)
            net_pipes = pandapipes.create_empty_network(fluid="water", name='test_pipes_simple')
            pandapipes.create_junction(net_pipes, pn_bar=10, tfluid_k=350)
            
            # Create time steps
            time_steps = pd.date_range("2023-01-01", "2023-01-02", freq='1h', tz='UTC')
            
            # Add networks with OutputWriter - should not fail even with minimal elements
            energy_system = create_empty_energy_system()
            
            power_output_path = os.path.join(temp_dir, "networks", "pandapower", net_power.name)
            pipes_output_path = os.path.join(temp_dir, "networks", "pandapipes", net_pipes.name)
            
            add_net_to_energy_system(
                energy_system, 
                net_power, 
                net_name=net_power.name,
                output_path=power_output_path,
                time_steps=time_steps
            )
            
            add_net_to_energy_system(
                energy_system, 
                net_pipes, 
                net_name=net_pipes.name,
                output_path=pipes_output_path,
                time_steps=time_steps
            )
            
            # Verify that OutputWriter was initialized without errors
            assert os.path.exists(power_output_path), "Pandapower OutputWriter directory not created"
            assert os.path.exists(pipes_output_path), "Pandapipes OutputWriter directory not created"

    def test_backward_compatibility(self):
        """Test that add_net_to_energy_system works without OutputWriter parameters."""
        # Create a simple network
        net = _create_simple_power_network()
        energy_system = create_empty_energy_system()
        
        # Add network without OutputWriter parameters (backward compatibility)
        add_net_to_energy_system(energy_system, net, net_name=net.name)
        
        # Verify network was added
        assert net.name in energy_system['nets'], "Network not added to energy system"
        assert energy_system['nets'][net.name] is net, "Wrong network reference stored"

    def test_log_variables_for_different_network_types(self):
        """Test that appropriate log variables are selected for different network types."""
        from pandaprosumer.energy_system.create_energy_system import _get_pandapower_log_variables, _get_pandapipes_log_variables
        
        # Test pandapower network with buses and lines
        net_power_full = pandapower.create_empty_network()
        pandapower.create_bus(net_power_full, vn_kv=20.)
        pandapower.create_bus(net_power_full, vn_kv=20.)
        pandapower.create_line(net_power_full, from_bus=0, to_bus=1, length_km=1, std_type="NAYY 4x50 SE")
        
        power_vars = _get_pandapower_log_variables(net_power_full)
        assert len(power_vars) == 4, f"Expected 4 pandapower variables, got {len(power_vars)}"
        assert any('res_bus' in var for var in power_vars), "No bus variables found"
        assert any('res_line' in var for var in power_vars), "No line variables found"
        
        # Test pandapower network with only buses
        net_power_buses = pandapower.create_empty_network()
        pandapower.create_bus(net_power_buses, vn_kv=20.)
        
        power_vars_buses = _get_pandapower_log_variables(net_power_buses)
        assert len(power_vars_buses) == 2, f"Expected 2 pandapower bus variables, got {len(power_vars_buses)}"
        assert any('res_bus' in var for var in power_vars_buses), "No bus variables found"
        assert not any('res_line' in var for var in power_vars_buses), "Unexpected line variables found"
        
        # Test pandapipes network with various elements
        net_pipes_full = pandapipes.create_empty_network(fluid="water")
        j0 = pandapipes.create_junction(net_pipes_full, pn_bar=10, tfluid_k=350)
        j1 = pandapipes.create_junction(net_pipes_full, pn_bar=10, tfluid_k=340)
        pandapipes.create_heat_consumer(net_pipes_full, from_junction=j0, to_junction=j1, 
                                       qext_w=1000, controlled_mdot_kg_per_s=0.5)
        pandapipes.create_circ_pump_const_pressure(net_pipes_full, return_junction=j1, flow_junction=j0,
                                                   p_flow_bar=10, plift_bar=5, t_flow_k=340)
        
        pipes_vars = _get_pandapipes_log_variables(net_pipes_full)
        expected_pipes_vars = 13  # junction(2) + heat_consumer(5) + circ_pump_pressure(6)
        assert len(pipes_vars) == expected_pipes_vars, f"Expected {expected_pipes_vars} pandapipes variables, got {len(pipes_vars)}"
