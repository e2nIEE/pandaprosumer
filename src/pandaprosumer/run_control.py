from pandapower.control import control_initialization, control_implementation, control_finalization, \
    get_controller_order


def run_control(prosumer, ctrl_variables=None, max_iter=30, **kwargs):
    """
    Main function to call a prosumer with controllers
    Function is running control loops for the controllers specified in prosumer.controller

    INPUT:
   **prosumer** - prosumer with controllers included in prosumer.controller

    OPTIONAL:
       **ctrl_variables** (dict, None) - variables needed internally to calculate the power flow. See prepare_run_ctrl()
       **max_iter** (int, 30) - The maximum number of iterations for controller to converge

    KWARGS:
        **continue_on_divergence** (bool, False) - if run_funct is not converging control_repair is fired
                                                   (only relevant if ctrl_varibales is None, otherwise it needs
                                                   to be defined in ctrl_variables anyway)
        **check_each_level** (bool, True) - if each level shall be checked if the controllers are converged or not
                                           (only relevant if ctrl_varibales is None, otherwise it needs
                                           to be defined in ctrl_variables anyway)

    Runs controller until each one converged or max_iter is hit.

    1. Call initialize_control() on each controller
    2. Calculate an inital power flow (if it is enabled, i.e. setting the initial_run veriable to True)
    3. Repeats the following steps in ascending order of controller_order until total convergence of all
       controllers for each level:
        a) Evaluate individual convergence for all controllers in the level
        b) Call control_step() for all controllers in the level on diverged controllers
        c) Calculate power flow (or optionally another function like runopf or whatever you defined)
    4. Call finalize_control() on each controller

    """
    ctrl_variables = prepare_run_ctrl(prosumer, ctrl_variables)

    controller_order = ctrl_variables["controller_order"]

    # initialize each controller prior to the first power flow
    control_initialization(controller_order)

    # run each controller step in given controller order
    control_implementation(prosumer, controller_order, ctrl_variables, max_iter, **kwargs)

    # call finalize function of each controller
    control_finalization(controller_order)


def ctrl_variables_default(prosumer):
    ctrl_variables = dict()
    if not hasattr(prosumer, "controller") or len(prosumer.controller[prosumer.controller.in_service]) == 0:
        ctrl_variables["level"], ctrl_variables["controller_order"] = [0], [[]]
    else:
        ctrl_variables["level"], ctrl_variables["controller_order"] = \
            get_controller_order(prosumer, prosumer.controller)
    ctrl_variables['check_each_level'] = True
    ctrl_variables["errors"] = ()
    ctrl_variables['converged'] = True
    return ctrl_variables


def prepare_run_ctrl(prosumer, ctrl_variables=None, **kwargs):
    """
    Prepares run control functions. Internal variables needed:

    **controller_order** (list) - Order in which controllers in prosumer.controller will be called

    """
    # sort controller_order by order if not already done

    ctrl_var = ctrl_variables

    if ctrl_variables is None:
        ctrl_variables = ctrl_variables_default(prosumer)

    if ('check_each_level') in kwargs and (ctrl_var is None or 'check_each_level' not in ctrl_var.keys()):
        check = kwargs.pop('check_each_level')
        ctrl_variables['check_each_level'] = check

    return ctrl_variables
