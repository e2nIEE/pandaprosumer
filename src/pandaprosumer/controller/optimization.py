import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

from .base import BasicProsumerController


class OptimizationController(BasicProsumerController):

    def __init__(self, prosumer, optimization_object, order, level, in_service=True, index=None, **kwargs):
        """
        Initializes the HeatPumpController.

        :param prosumer: The prosumer object
        :param optimizationp_object: The optimization object
        :param order: The order of the controller
        :param level: The level of the controller
        :param in_service: The in-service status of the controller
        :param index: The index of the controller
        :param kwargs: Additional keyword arguments
        """
        super().__init__(prosumer, optimization_object, order=order, level=level, in_service=in_service, index=index, **kwargs)

    @property
    def _q_demand_kw(self):
        try:
            return self._get_input("q_demand_kw")
        except (KeyError, AttributeError):
            return None

    @property
    def _p_flex_kw(self):
        try:
            return self._get_input("p_flex_kw")
        except (KeyError, AttributeError):
            return None

    @property
    def _p_pv_in_kw(self):
        try:
            return self._get_input("p_pv_in_kw")
        except (KeyError, AttributeError):
            return None

    @property
    def _cop_bhp(self):
        try:
            return self._get_input("cop_bhp")
        except (KeyError, AttributeError):
            return None

    def fit_chp_relations(self, chp_map, degree=1):

        p_el = np.array(chp_map["power_el_kw"], dtype=float)
        q_th = np.array(chp_map["heat_flow_recovered_kw"], dtype=float)

        # Sort by electrical output
        idx = np.argsort(p_el)
        p_el, q_th = p_el[idx], q_th[idx]

        # Build Vandermonde matrix for polynomial fitting
        X = np.vander(p_el, N=degree + 1, increasing=True)

        # Least Squares Fit: q_th = f(p_el)
        coefficients, *_ = np.linalg.lstsq(X, q_th, rcond=None)

        return coefficients.tolist()

    def model_optimization(self, heat_demand, flex_demand, cop_bhp, soc, chp_map,
                           resol, storage_cap, q_bhp_max=700):
        m = pyo.ConcreteModel()

        # Parameter
        m.heat_demand = pyo.Param(initialize=heat_demand)
        m.flex_demand = pyo.Param(initialize=flex_demand)
        m.cop_bhp = pyo.Param(initialize=cop_bhp)
        m.q_th_bhp_max = pyo.Param(initialize=q_bhp_max)
        m.soc = pyo.Param(initialize=soc)
        m.storage_cap = pyo.Param(initialize=storage_cap)
        m.resol = pyo.Param(initialize=resol)

        # decision variables for electrical input (BHP) and output (CHP)
        m.p_el_bhp = pyo.Var(domain=pyo.NonNegativeReals)  # BHP power consumption
        m.p_el_chp = pyo.Var(domain=pyo.NonNegativeReals)  # CHP power generation

        # binary Variable for chp. To turn the chp of ig´f the load is out of bounds
        m.y_chp = pyo.Var(domain=pyo.Binary)

        nominal_size_chp = chp_map["__chp_nominal_size_kw__"]
        chp_max_heat_output = chp_map["heat_flow_recovered_kw"][0]
        load_min, load_max = chp_map["load_limits_percent"]

        # Convert to absolute electrical bounds
        p_el_min_chp = (load_min / 100.0) * nominal_size_chp
        p_el_max_chp = (load_max / 100.0) * nominal_size_chp

        # Bound Constraints CHP
        m.p_el_chp_min = pyo.Constraint(expr=m.p_el_chp >= p_el_min_chp * m.y_chp)
        m.p_el_chp_max = pyo.Constraint(expr=m.p_el_chp <= p_el_max_chp * m.y_chp)

        # variables thermal output
        m.q_th_bhp = pyo.Var(domain=pyo.NonNegativeReals)
        m.q_th_chp = pyo.Var(domain=pyo.NonNegativeReals)

        ## Relation between thermal and electric ouput CHP
        # coefficient of the fit curve of thermal and electric output of the CHP
        fit = self.fit_chp_relations(chp_map, degree=1)
        coeff_HE = fit

        M_chp = chp_max_heat_output  # Big-M
        #  Link q_th_chp to polynomial of p_el_chp only if CHP is on (y_chp = 1), relaxed otherwise
        m.q_th_chp_upper = pyo.Constraint(
            expr=m.q_th_chp <= self.poly_expr(coeff_HE, m.p_el_chp) + M_chp * (1 - m.y_chp)
        )
        m.q_th_chp_lower = pyo.Constraint(
            expr=m.q_th_chp >= self.poly_expr(coeff_HE, m.p_el_chp) - M_chp * (1 - m.y_chp)
        )

        # If the CHP is off (y=0) no thermal output is allowed.
        m.q_th_chp_off = pyo.Constraint(expr=m.q_th_chp <= M_chp * m.y_chp)

        # Relation between thermal and electric ouput BHP
        m.q_th_bhp = pyo.Expression(expr=m.cop_bhp * m.p_el_bhp)

        # capacity bound for the BHP
        m.hp_cap = pyo.Constraint(expr=m.q_th_bhp <= m.q_th_bhp_max)

        # stoage variables
        m.q_th_charge = pyo.Var(domain=pyo.NonNegativeReals)
        m.q_th_discharge = pyo.Var(domain=pyo.NonNegativeReals)

        # Binary-vriables storage
        m.y_charge = pyo.Var(domain=pyo.Binary)
        m.y_discharge = pyo.Var(domain=pyo.Binary)

        # allows to only charge or discharge the storage. Not both at the same time.
        m.charge_discharge = pyo.Constraint(expr=m.y_discharge + m.y_charge <= 1)

        # bounds for charging or discharging the storge dependend on the soc
        m.q_th_charge_max = pyo.Constraint(
            expr=m.q_th_charge <= m.storage_cap * (1 - m.soc) * m.resol / 3600 * m.y_charge)
        m.q_th_discharge_max = pyo.Constraint(
            expr=m.q_th_discharge <= m.storage_cap * m.soc * m.resol / 3600 * m.y_discharge)

        # balances
        m.heat_bal = pyo.Constraint(expr=m.q_th_bhp + m.q_th_chp + m.q_th_discharge - m.q_th_charge == m.heat_demand)
        m.el_bal = pyo.Expression(expr=-m.p_el_bhp + m.p_el_chp - m.flex_demand)

        # objective to minimize the electric power consumption of the whole system.
        m.obj = pyo.Objective(
            expr=m.el_bal ** 2 - m.q_th_charge,
            sense=pyo.minimize
        )

        # Solver
        solver = pyo.SolverFactory('mindtpy')
        results = solver.solve(m, strategy='OA', mip_solver='glpk', nlp_solver='ipopt')

        if (results.solver.status == SolverStatus.ok and
                results.solver.termination_condition == TerminationCondition.optimal):
            feasible = True
        else:
            feasible = False

        return pyo.value(m.p_el_bhp), pyo.value(m.p_el_chp), feasible

    def poly_expr(self, coeffs, x):
        return sum(coeffs[i] * (x ** i) for i in range(len(coeffs)))

    def q_to_receive_kw(self, prosumer):
        """
        Calculates the heat to receive in kW.

        :param prosumer: The prosumer object
        :return: Heat to receive in kW
        """
        q_to_receive_kw = 100 #Todo: Find a solution, BHP needs this as an input, but we only need the cop
        return q_to_receive_kw

    def initialize_control(self, container):
        """Some controller require extended initialization in respect to the
        current state of the net (or their view of it). This method is being
        called after an initial loadflow but BEFORE any control strategies are
        being applied.

        This method may be interesting if you are aiming for a global
        controller or if it has to be aware of its initial state.

        Parameters
        ----------
        container : _type_
            _description_


        """
        super().initialize_control(container)

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if not hasattr(prosumer, "controller_results"):
            prosumer.controller_results = {} #Todo: Hier könnte man direkt die last_results speichern anstatt in einer extra Funktion

        q_demand_kw = self._q_demand_kw
        p_flex_kw = self._p_flex_kw
        p_pv_in_kw = self._p_pv_in_kw
        cop_bhp = self._cop_bhp

        resol = self.resol
        storage_cap_kwh = self._get_element_param(prosumer, "storage_capacity_kwh")
        q_bhp_max = self._get_element_param(prosumer, "q_bhp_max")
        chp_map = self._get_element_param(prosumer, "chp_map")

        ts = self.time

        # previous timestep
        ts_prev = ts - pd.Timedelta(seconds=resol)
        # Results for the timestep
        results_timestep = prosumer.controller_results

        storage_idx = prosumer.controller[
            prosumer.controller["object"].apply(lambda c: c.__class__.__name__ == "HeatStorageController")
        ].index[0]

        if ts_prev in results_timestep:
            soc = results_timestep[ts_prev][storage_idx]["soc"]
        else:
            # first timestep → SOC = 0
            soc = 0.0

        p_el_bhp_in, p_el_chp_out, feasible = self.model_optimization(
            heat_demand=q_demand_kw,
            flex_demand=p_flex_kw,
            cop_bhp=cop_bhp,
            soc=soc,
            chp_map=chp_map,
            q_bhp_max=q_bhp_max,
            storage_cap=storage_cap_kwh,
            resol=resol,
        )

        if feasible:
            result = np.array([[p_el_bhp_in,
                       p_el_chp_out]])
        else:
            result = np.array([[np.nan,
                       np.nan]])

        self.finalize(prosumer, result)
        self.applied = True

