from pandapower.control import control_initialization, control_implementation, control_finalization, \
    get_controller_order, check_final_convergence
try:
    import pandaplan.core.pplog as pplog
except:
    import logging as pplog

logger = pplog.getLogger(__name__)


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

def _evaluate_net(net, levelorder, ctrl_variables, **kwargs):
    run_funct = ctrl_variables['run']
    errors = ctrl_variables['errors']
    try:
        run_funct(net, **kwargs)  # run can be runpp, runopf or whatever
    except errors as err:
        net._ppc = None
        if ctrl_variables['continue_on_divergence']:
            # give a chance to controllers to "repair" the control step if load flow
            # didn't converge
            # either implement this in a controller that is likely to cause the error,
            # or define a special "load flow police" controller for your use case
            _control_repair(levelorder)
            # this will raise the error if repair_control did't work
            # it means that repair control has only 1 try
            try:
                run_funct(net, **kwargs)
            except errors:
                pass
        else:
            raise err
    ctrl_variables['converged'] = net['converged'] or net.get('OPF_converged', False)
    return ctrl_variables

def control_implementation(net, controller_order, ctrl_variables, max_iter,
                           evaluate_net_fct=_evaluate_net, **kwargs):

    run_count=0
    # run each controller step in given controller order
    _,controller_order = get_controller_order(net,net.controller)
    n = len(controller_order)
    for i in range(n):
        levelorder = controller_order[i]
        _reset_convergence(levelorder)
        # converged gives status about convergence of a controller. Is initialized as False
        ctrl_converged = False
        # run_count is 0 before entering the loop. Is incremented in each controller loop
        converged = ctrl_variables['converged']
        run_count = 0
        while not ctrl_converged and run_count <= max_iter and converged:
            ctrl_converged = _control_step(levelorder, run_count)
            _,controller_order = get_controller_order(net,net.controller)
            # call to run function (usually runpp) after each controller was called
            # this function is called at least once per level
            if not ctrl_converged:
                run_count += 1
                ctrl_variables = evaluate_net_fct(net, levelorder, ctrl_variables, **kwargs)
            # raises controller not converged
        if ctrl_variables['check_each_level']:
            check_final_convergence(run_count, max_iter, ctrl_variables['converged'])
            # is required if you only want to check if in the last level everything is converged
        check_final_convergence(run_count, max_iter, ctrl_variables['converged'])


def _reset_convergence(levelorder):
    for ctrl, net in levelorder:
        ctrl.level_reset(net)

def _control_step(levelorder, run_count):
    # keep track of stopping criteria
    converged = True
    logger.debug("Controller Iteration #%i" % run_count)
    # run each controller until all are converged
    for ctrl, net in levelorder:
        # call control step while controller ist not converged yet
        if not ctrl.is_converged(net):
            ctrl.control_step(net)
            converged = False
    return converged

def _control_repair(levelorder):
    for ctrl, net in levelorder:
        ctrl.repair_control(net)