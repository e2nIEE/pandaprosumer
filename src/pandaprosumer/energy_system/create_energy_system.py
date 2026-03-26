# Copyright (c) 2025 by Fraunhofer Institute for Energy Economics
# and Energy System Technology (IEE), Kassel. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.

try:
    import pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)
logger.setLevel(level=logging.WARNING)

import os
import pandas as pd
from pandapipes import pandapipesNet
from pandapower import pandapowerNet
from pandapower.timeseries.output_writer import OutputWriter
from pandaprosumer.energy_system import EnergySystem
from pandaprosumer.energy_system import get_default_energy_system_structure

try:
    import pandaplan.core.pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)
logger.setLevel(level=logging.WARNING)


def create_empty_energy_system(name="my_energy_system"):
    """
    This function initializes the energy system datastructure.

    :param name: Name for the energy system
    :type name: string (default "my_energy_system")
    :return: EnergySystem with empty tables
    :rtype: EnergySystem

    :Example:
        >>> mn = create_empty_energy_system("my_first_energy_system")

    """
    energy_system = EnergySystem(get_default_energy_system_structure(), name=name)
    return energy_system


def add_pandaprosumer_to_energy_system(energy_system, pandaprosumer, pandaprosumer_name='my_prosumer', overwrite=False):
    """
    Add a pandaprosumer to the energy system structure.

    :param energy_system: energy system to which a pandaprosumer will be added
    :type energy_system: pandaprosumer.EnergySystem
    :param net: pandaprosumer that will be added to the energy system
    :type net: pandaprosumerContainer
    :param net_name: unique name for the added pandaprosumer
    :type net_name: str
    :default: 'my_prosumer'
    :param overwrite: whether a pandaprosumer should be overwritten if it has the same pandaprosumer_name
    :type overwrite: bool
    :return: pandaprosumer reference is added inplace to the energy system (in energy system['nets'])
    :rtype: None
    """

    if not overwrite and 'prosumer' in energy_system and pandaprosumer_name in energy_system['prosumer']:
        logger.warning("A prosumer with the name %s exists already in the energy system. If you want to "
                       "overwrite it, set 'overwrite' to True." % pandaprosumer_name)
        return
    elif not 'prosumer' in energy_system:
        energy_system.update({'prosumer': dict()})

    energy_system['prosumer'].update({pandaprosumer_name: pandaprosumer})


def add_net_to_energy_system(energy_system, net, net_name='my_network', overwrite=False, 
                           output_path=None, output_file_type='.csv', csv_separator=",",
                           time_steps=None):
    """
    Add a pandapipes or pandapower net to the energy system structure.

    :param energy_system: energy system to which a pandapipes/pandapower net will be added
    :type energy_system: pandaprosumer.EnergySystem
    :param net: pandapipes or pandapower net that will be added to the energy system
    :type net: pandapowerNet or pandapipesNet
    :param net_name: unique name for the added net, e.g. 'power', 'gas', or 'power_net1'
    :type net_name: str
    :default: 'my_network'
    :param overwrite: whether a net should be overwritten if it has the same net_name
    :type overwrite: bool
    :param output_path: path where output files should be written (optional)
    :type output_path: str or None
    :param output_file_type: file type for output (default: '.csv')
    :type output_file_type: str
    :param csv_separator: separator for CSV files (default: ',')
    :type csv_separator: str
    :param time_steps: time steps for OutputWriter (optional)
    :type time_steps: pandas.DatetimeIndex or None
    :return: net reference is added inplace to the energy system (in energy_system['nets'])
    :rtype: None
    """
    if net_name in energy_system['nets'] and not overwrite:
        logger.warning("A net with the name %s exists already in the energy system. If you want to "
                       "overwrite it, set 'overwrite' to True." % net_name)
    else:
        energy_system['nets'][net_name] = net
        
        # Initialize OutputWriter if output_path is provided
        if output_path is not None:
            _initialize_network_output_writer(net, output_path, output_file_type, csv_separator, time_steps)


def _initialize_network_output_writer(net, output_path, output_file_type, csv_separator, time_steps):
    """
    Initialize OutputWriter for a network and configure log variables based on available elements.
    
    :param net: pandapower or pandapipes network
    :param output_path: path where output files should be written
    :param output_file_type: file type for output
    :param csv_separator: separator for CSV files
    :param time_steps: time steps for OutputWriter
    """
    try:
        # Create output directory if it doesn't exist
        if not os.path.exists(output_path):
            os.makedirs(output_path)
        
        # Determine network type and configure log variables
        if hasattr(net, 'bus'):  # pandapower network
            log_variables = _get_pandapower_log_variables(net)
        else:  # pandapipes network
            log_variables = _get_pandapipes_log_variables(net)
        
        # Initialize OutputWriter
        OutputWriter(
            net,
            time_steps,
            output_path=output_path,
            output_file_type=output_file_type,
            csv_separator=csv_separator,
            log_variables=log_variables
        )
        
        logger.info(f"OutputWriter initialized for network at {output_path}")
        
    except Exception as e:
        logger.warning(f"Failed to initialize OutputWriter for network: {str(e)}")


def _get_pandapower_log_variables(net):
    """
    Get log variables for pandapower network, checking if elements exist.
    """
    log_variables = []
    
    # Check and add bus variables
    if hasattr(net, 'bus') and len(net.bus) > 0:
        log_variables.extend([
            ('res_bus', 'vm_pu'),
            ('res_bus', 'va_degree')
        ])
    
    # Check and add line variables
    if hasattr(net, 'line') and len(net.line) > 0:
        log_variables.extend([
            ('res_line', 'loading_percent'),
            ('res_line', 'i_ka')
        ])
    
    return log_variables


def _get_pandapipes_log_variables(net):
    """
    Get log variables for pandapipes network, checking if elements exist.
    """
    log_variables = []
    
    # Check and add junction variables
    if hasattr(net, 'junction') and len(net.junction) > 0:
        log_variables.extend([
            ('res_junction', 'p_bar'),
            ('res_junction', 't_k')
        ])
    
    # Check and add pipe variables
    if hasattr(net, 'pipe') and len(net.pipe) > 0:
        log_variables.append(('res_pipe', 'mdot_from_kg_per_s'))
    
    # Check and add heat consumer variables
    if hasattr(net, 'heat_consumer') and len(net.heat_consumer) > 0:
        log_variables.extend([
            ('res_heat_consumer', 'mdot_from_kg_per_s'),
            ('res_heat_consumer', 'qext_w'),
            ('res_heat_consumer', 't_from_k'),
            ('res_heat_consumer', 't_to_k'),
            ('res_heat_consumer', 't_outlet_k')
        ])
    
    # Check and add circ pump pressure variables
    if hasattr(net, 'circ_pump_pressure') and len(net.circ_pump_pressure) > 0:
        log_variables.extend([
            ('res_circ_pump_pressure', 'mdot_from_kg_per_s'),
            ('res_circ_pump_pressure', 't_from_k'),
            ('res_circ_pump_pressure', 't_to_k'),
            ('res_circ_pump_pressure', 't_outlet_k'),
            ('res_circ_pump_pressure', 'p_from_bar'),
            ('res_circ_pump_pressure', 'p_to_bar')
        ])
    
    # Check and add flow control variables
    if hasattr(net, 'flow_control') and len(net.flow_control) > 0:
        log_variables.extend([
            ('res_flow_control', 'mdot_from_kg_per_s'),
            ('res_flow_control', 't_from_k'),
            ('res_flow_control', 't_to_k'),
            ('res_flow_control', 't_outlet_k')
        ])
    
    return log_variables
