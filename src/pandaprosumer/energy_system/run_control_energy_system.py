# Copyright (c) 2020-2022 by Fraunhofer Institute for Energy Economics
# and Energy System Technology (IEE), Kassel. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.

import numpy as np
import pandas as pd

import pandaprosumer2 as ppros
from pandapipes.multinet.control.run_control_multinet import prepare_ctrl_variables_for_net, _evaluate_multinet, \
    net_initialization_multinet
from pandapower.control.run_control import control_initialization, \
    control_finalization, \
    control_implementation, get_controller_order, NetCalculationNotConverged
from pandaprosumer2.run_control import prepare_run_ctrl as prepare_run_ctrl_ppros
from pandaprosumer2.pandaprosumer_container import pandaprosumerContainer, get_default_prosumer_container_structure


try:
    import pandaplan.core.pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)


def run_control(energy_system, ctrl_variables=None, max_iter=30, **kwargs):
    """
    Main function to call an energy system with controllers.

    Function is running control loops for the controllers specified in net.controller
    Runs controller until each one converged or max_iter is hit.

    1. Call initialize_control() on each controller
    2. Calculate an inital run (if it is enabled, i.e. setting the initial_run variable to True)
    3. Repeats the following steps in ascending order of controller_order until total convergence of all
       controllers for each level:
       a) Evaluate individual convergence for all controllers in the level
       b) Call control_step() for all controllers in the level on diverged controllers
       c) Fire run function (or optionally another function like run_pf or whatever you defined)
    4. Call finalize_control() on each controller

    :param energy_system: energy system with energy system controllers, distinct controllers, several pandapipes/pandapower nets and pandaprosumer
    :type energy_system: pandaprosumer2.EnergySystem
    :param ctrl_variables: contains all relevant information and boundaries required for a successful control run. To \
           define ctrl_variables yourself, following entries for each net/prosumer are required:\n
           - level (list): gives a list of levels to be investigated \n
           - controller_order (list): nested list of tuples given the correct order of the
             different controllers within one level\
           - run (funct, e.g. pandapower.runpp, pandapipes.pipeflow): function to be used to
             conduct a loadflow/pipeflow \n; not required for prosumer
           - initial_run (boolean): Is a initial_run for a net required or not\n; not required for prosumer
           - continue_on_divergence (boolean): What to do if loadflow/pipeflow is not converging, fires control_repair; not required for prosumer
    :type ctrl_variables: dict, default: None
    :param max_iter: number of iterations for each controller to converge
    :type max_iter: int, default: 30
    :param kwargs: additional keyword arguments handed to each run function
    :type kwargs: dict
    :return: runs an entire control loop
    :rtype: None
    """
    ctrl_variables = prepare_run_ctrl(energy_system, ctrl_variables)

    controller_order = ctrl_variables['controller_order']

    # initialize each controller prior to the first power flow
    control_initialization(controller_order)

    # initial run (takes time, but is not needed for every kind of controller)
    ctrl_variables = net_initialization_multinet(energy_system, ctrl_variables, **kwargs)

    # run each controller step in given controller order
    control_implementation(energy_system, controller_order, ctrl_variables, max_iter,
                           evaluate_net_fct=_evaluate_multinet, **kwargs)

    # call finalize function of each controller
    control_finalization(controller_order)


def get_controller_order_energy_system(energy_system):
    """
    Defining the controller order per level.

    Takes the order and level columns from each controller.
    If levels are specified, the levels and orders are executed in ascending order.

    :param energy_system: energy system with energy system controllers, distinct controllers, several pandapipes/pandapower nets and pandaprosumer
    :type energy_system: pandaprosumer2.EnergySystem
    :return: nested list of tuples given the correct order of the controllers, respectively for each level
    :rtype: list
    """

    comp_list = []
    controller_list = []

    if hasattr(energy_system, "controller") and len(energy_system.controller[energy_system.controller.in_service]) != 0:
        # if no controllers are in the net, we have no levels and no order lists
        energy_system_controller = [energy_system] * len(energy_system.controller)
        comp_list += energy_system_controller
        controller_list += [energy_system.controller.values]

    for net_name in energy_system['nets'].keys():
        net = energy_system['nets'][net_name]
        if not (hasattr(net, 'controller') and len(net.controller[net.controller.in_service]) != 0):
            # if no controllers are in the net, we have no levels and no order lists
            continue
        nets = [net] * len(net.controller)
        comp_list += nets
        controller_list += [net.controller.values]

    for pros_name in energy_system['prosumer'].keys():
        prosumer = energy_system['prosumer'][pros_name]
        if not (hasattr(prosumer, 'controller') and len(prosumer.controller[prosumer.controller.in_service]) != 0):
            # if no controllers are in the net, we have no levels and no order lists
            continue
        prosumers = [prosumer] * len(prosumer.controller.values)
        controller = prosumer.controller.copy()
        controller['initial_run'] = False
        controller['recycle'] = False
        comp_list += prosumers
        controller_list += [controller.values]

    if not len(controller_list):
        # if no controllers are in the net, we have no levels and no order lists
        return [0], [[]]
    else:
        controller_list = pd.DataFrame(np.concatenate(controller_list), columns=energy_system.controller.columns)
        controller_list = controller_list.astype(energy_system.controller.dtypes)
        return get_controller_order(comp_list, controller_list)


def prepare_ctrl_variables_for_prosumer(energy_system, prosumer_name, ctrl_variables, **kwargs):
    if prosumer_name not in ctrl_variables['prosumer'].keys():
        ctrl_variables['prosumer'][prosumer_name] = {}
    prosumer = energy_system['prosumer'][prosumer_name]
    if isinstance(prosumer, pandaprosumerContainer):
        ctrl_variables_net = prepare_run_ctrl_ppros(prosumer, None, **kwargs)
    else:
        raise ValueError('The given prosumer needs to be a pandaprosumer container')

    ctrl_variables['prosumer'][prosumer_name]['errors'] = ctrl_variables['prosumer'][prosumer_name].get("errors", ctrl_variables_net['errors'])


def prepare_run_ctrl(energy_system, ctrl_variables, **kwargs):
    """
    Prepares run control functions.

    Internal variables needed:
        - level (list): gives a list of levels to be investigated
        - controller_order (list): nested list of tuples given the correct order of the different controllers
        within one level
        - run (funct, e.g. pandapower.runpp, pandapipes.pipeflow): function to be used to conduct a loadflow/pipeflow; not required for prosumer
        - initial_run (boolean): Is a initial_run for a net required or not; not required for prosumer
        - continue_on_divergence (boolean): What to do if loadflow/pipeflow is not converging, fires control_repair; not required for prosumer

    You don't need to define it for each component. If one component is not defined, the default settings are used.

    :param energy_system: energy system with energy system controllers, distinct controllers, several pandapipes/pandapower nets and pandaprosumer
    :type energy_system: pandaprosumer2.EnergySystem
    :param ctrl_variables: contains all relevant information and boundaries required for a successful control run.
    :type ctrl_variables: dict, default: None
    :return: adapted ctrl_variables for all components with all required boundary information
    :rtype: dict
    """

    # sort controller_order by order if not already done
    if ctrl_variables is None:
        ctrl_variables = {'nets': dict(), 'prosumer': dict()}

    for net_name in energy_system['nets'].keys():
        prepare_ctrl_variables_for_net(energy_system, net_name, ctrl_variables, **kwargs)

    for pros in energy_system['prosumer'].keys():
        prepare_ctrl_variables_for_prosumer(energy_system, pros, ctrl_variables, **kwargs)

    if ('check_each_level') in kwargs:
        check = kwargs.pop('check_each_level')
        ctrl_variables['check_each_level'] = check
    else:
        ctrl_variables['check_each_level'] = True

    ctrl_variables['errors'] = (NetCalculationNotConverged,)

    ctrl_variables['level'], ctrl_variables['controller_order'] = get_controller_order_energy_system(energy_system)

    return ctrl_variables
