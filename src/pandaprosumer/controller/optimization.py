import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition
import os
import json

from .base import BasicProsumerController


class OptimizationController(BasicProsumerController):

    def __init__(self, prosumer, optimization_object, order, level, in_service=True, index=None, **kwargs):
        """
        Initializes the OptimizationController.

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

    def model_optimization(self, prosumer, heat_demand, flex_demand):
        m = pyo.ConcreteModel()

        # Parameter
        m.heat_demand = pyo.Param(initialize=heat_demand)
        m.flex_demand = pyo.Param(initialize=flex_demand)

        bhp_idx = []
        chp_idx = []
        storage_idx = []

        for idx, row in prosumer.controller.iterrows():
            if row["level"] != 2: #Todo: Make this an input (only consider Controllers of this level)
                continue
            cname = row["object"].__class__.__name__
            if cname == "BoosterHeatPumpController":
                bhp_idx.append(idx)
            elif cname == "IceChpController":
                chp_idx.append(idx)
            elif cname == "HeatStorageController":
                storage_idx.append(idx)

        m.bhp_index = pyo.Set(initialize=bhp_idx)
        m.chp_index = pyo.Set(initialize=chp_idx)
        m.storage_index = pyo.Set(initialize=storage_idx)

        m.bhp = pyo.Block(m.bhp_index)
        m.chp = pyo.Block(m.chp_index)
        m.storage = pyo.Block(m.storage_index)

        for idx in m.bhp_index:
            self._add_booster_heatpump(prosumer, m.bhp[idx], idx)

        for idx in m.chp_index:
            self._add_chp(prosumer, m.chp[idx], idx)

        for idx in m.storage_index:
            self._add_storage(prosumer, m.storage[idx], idx)

        # balances
        # m.heat_bal = pyo.Constraint(expr=m.q_th_bhp + m.q_th_chp + m.q_th_discharge - m.q_th_charge == m.heat_demand)
        # m.el_bal = pyo.Expression(expr=-m.p_el_bhp + m.p_el_chp - m.flex_demand)

        heat_terms = []
        for idx in m.bhp:
            heat_terms.append(m.bhp[idx].q_th)
        for idx in m.chp:
            heat_terms.append(m.chp[idx].q_th)
        for idx in m.storage:
            heat_terms.append(m.storage[idx].q_th_discharge)
            heat_terms.append(-m.storage[idx].q_th_charge)

        m.heat_bal = pyo.Constraint(expr=sum(heat_terms) == m.heat_demand)

        el_terms = []
        for idx in m.bhp:
            el_terms.append(-m.bhp[idx].p_el)
        for idx in m.chp:
            el_terms.append(m.chp[idx].p_el)

        m.el_bal = pyo.Expression(expr=sum(el_terms) - m.flex_demand)

        # charge_terms = [m.storage[idx].q_th_charge for idx in m.storage]

        charge_terms = []
        for idx in m.storage:
            block = m.storage[idx]
            charge_terms.append(
                block.q_th_charge
               # (2 * block.z_low_soc - 1) * block.q_th_charge
            )

        # m.obj = pyo.Objective(
        #     expr=m.el_bal ** 2 - sum(charge_terms),
        #     sense=pyo.minimize
        # )

        W_flex = 1_000.0  # sehr hoch
        W_store = 1.0  # deutlich kleiner

        m.t = pyo.Var(domain=pyo.NonNegativeReals)

        m.abs1 = pyo.Constraint(expr=m.el_bal <= m.t)
        m.abs2 = pyo.Constraint(expr=-m.el_bal <= m.t)


        m.obj = pyo.Objective(
            expr=W_flex * (m.t)
                 + W_store * sum(charge_terms),
            sense=pyo.minimize
        )

        # Solver
        solver = pyo.SolverFactory('glpk')
        results = solver.solve(m)#, strategy='OA', mip_solver='glpk', nlp_solver='ipopt')

        if (results.solver.status == SolverStatus.ok and
                results.solver.termination_condition == TerminationCondition.optimal):
            feasible = True
        else:
            feasible = False

        p_bhp = next(m.bhp[idx].p_el.value for idx in m.bhp)
        p_chp = next(m.chp[idx].p_el.value for idx in m.chp)
        return p_bhp, p_chp, feasible

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

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """

        if not hasattr(prosumer, "controller_results"):
            prosumer.controller_results = {} #Todo: Hier könnte man direkt die last_results speichern anstatt in einer extra Funktion

        q_demand_kw = self._q_demand_kw
        p_flex_kw = self._p_flex_kw

        p_el_bhp_in, p_el_chp_out, feasible = self.model_optimization(
            prosumer=prosumer,
            heat_demand=q_demand_kw,
            flex_demand=p_flex_kw,
           )

        if feasible:
            result = np.array([[p_el_bhp_in, #Todo: Other format for results to make them dynamic for the specific use case and allow more then one element of the same Controller
                       p_el_chp_out]])
        else:
            result = np.array([[np.nan,
                       np.nan]]) #Todo: Check this

        self.finalize(prosumer, result)
        self.applied = True

    def to_scalar(self, x):
        """Konvertiert beliebige numpy/pandas/pyomo Werte in einen float."""
        if isinstance(x, (list, tuple)):
            return float(x[0])
        if isinstance(x, np.ndarray):
            return float(x.flatten()[0])
        if hasattr(x, "iloc"):  # pandas Series
            return float(x.iloc[0])
        if hasattr(x, "values"):  # pandas DataFrame cell
            return float(x.values[0])
        return float(x)

    def _add_booster_heatpump(self, prosumer, block, index):

        cop_bhp = self._cop_bhp
        ctrl = prosumer.controller.loc[index]["object"]
        q_bhp_max = ctrl.element_instance["q_max_kw"].iloc[0]

        block.cop = pyo.Param(initialize=cop_bhp)
        block.q_th_max = pyo.Param(initialize=q_bhp_max)

        block.p_el = pyo.Var(domain=pyo.NonNegativeReals)  # BHP power consumption

        # Relation between thermal and electric ouput BHP
        block.q_th = pyo.Expression(expr=block.cop * block.p_el)

        # capacity bound for the BHP
        block.q_th_max_constr = pyo.Constraint(expr=block.q_th <= block.q_th_max)


    def _add_chp(self, prosumer, block, index):
        """
        Fügt eine CHP-Komponente zum Optimierungsmodell hinzu.
        """
        ctrl = prosumer.controller.loc[index]["object"]
        size_kw = ctrl.element_instance["size"].iloc[0]
        # select the chp_map for the optimization
        base_dir = os.path.dirname(__file__)
        path = os.path.join(
            base_dir,
            "..", "library", "chp_maps", "ice_chp_maps.json"
        )
        path = os.path.abspath(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chp_map = next(m for m in data["chp_ice_map"] if m["__chp_nominal_size_kw__"] == size_kw)

        # Statische Parameter aus dem Element
        nominal_size_chp = chp_map["__chp_nominal_size_kw__"]
        chp_max_heat_output = chp_map["heat_flow_recovered_kw"][0]
        load_min, load_max = chp_map["load_limits_percent"]

        # Elektrische Grenzen
        p_el_min_chp = (load_min / 100.0) * nominal_size_chp
        p_el_max_chp = (load_max / 100.0) * nominal_size_chp

        # Pyomo-Parameter
        block.p_el_min = pyo.Param(initialize=p_el_min_chp)
        block.p_el_max = pyo.Param(initialize=p_el_max_chp)
        block.q_th_max = pyo.Param(initialize=chp_max_heat_output)

        # Variablen
        block.p_el = pyo.Var(domain=pyo.NonNegativeReals)
        block.q_th = pyo.Var(domain=pyo.NonNegativeReals)
        block.y = pyo.Var(domain=pyo.Binary)

        # Lastgrenzen
        block.p_el_min_constr = pyo.Constraint(expr=block.p_el >= block.p_el_min * block.y)
        block.p_el_max_constr = pyo.Constraint(expr=block.p_el <= block.p_el_max * block.y)

        # Kennlinie fitten
        coeffs = self.fit_chp_relations(chp_map, degree=1)

        # Big-M
        M = chp_max_heat_output

        # Kennlinien-Constraints
        block.q_th_max_constr = pyo.Constraint(
            expr=block.q_th <= self.poly_expr(coeffs, block.p_el) + M * (1 - block.y)
        )
        block.q_th_min_constr = pyo.Constraint(
            expr=block.q_th >= self.poly_expr(coeffs, block.p_el) - M * (1 - block.y)
        )

        # Wenn aus → keine Wärme
        block.off_constr = pyo.Constraint(expr=block.q_th <= M * block.y)


    def _add_storage(self, prosumer, block, index):
        """
        Fügt einen Wärmespeicher zum Optimierungsmodell hinzu.
        """
        ctrl = prosumer.controller.loc[index]["object"]
        storage_cap_kwh = ctrl.element_instance["q_capacity_kwh"].iloc[0]
        resol = self.resol
        ts = self.time

        # previous timestep
        ts_prev = ts - pd.Timedelta(seconds=resol)
        if ts_prev in prosumer.controller_results:
            raw_soc_prev = prosumer.controller_results[ts_prev][index]["soc"]
        else:
            # first timestep → SOC = 0
            raw_soc_prev = 0.0

        soc_prev = self.to_scalar(raw_soc_prev)

        # Parameter
        block.Q_th_max = pyo.Param(initialize=storage_cap_kwh)
        block.soc_prev = pyo.Param(initialize=soc_prev)
        block.resol = pyo.Param(initialize=resol)

        # Variablen
        block.q_th_charge = pyo.Var(domain=pyo.NonNegativeReals)
        block.q_th_discharge = pyo.Var(domain=pyo.NonNegativeReals)
        block.soc = pyo.Var(bounds=(0, 1))

        block.y_charge = pyo.Var(domain=pyo.Binary)
        block.y_discharge = pyo.Var(domain=pyo.Binary)

        # Nicht gleichzeitig laden und entladen
        block.charge_discharge = pyo.Constraint(expr=block.y_charge + block.y_discharge <= 1)

        # Ladegrenzen
        block.charge_limit = pyo.Constraint(
            expr=block.q_th_charge <= block.Q_th_max * (1 - block.soc_prev) * block.resol / 3600 * block.y_charge
        )

        # Entladegrenzen
        block.discharge_limit = pyo.Constraint(
            expr=block.q_th_discharge <= block.Q_th_max * block.soc_prev * block.resol / 3600 * block.y_discharge
        )

        # SOC-Bilanz
        block.soc_balance = pyo.Constraint(
            expr=block.soc == block.soc_prev + (block.q_th_charge - block.q_th_discharge) * block.resol / 3600 / block.Q_th_max
        )

        block.z_low_soc = pyo.Var(domain=pyo.Binary)

        M = 1.0

        # Logik:
        # z_low_soc = 1  => soc <= 0.5
        # z_low_soc = 0  => soc >= 0.5
        block.soc_low_1 = pyo.Constraint(
            expr=block.soc <= 0.5 + M * (1 - block.z_low_soc)
        )

        block.soc_low_2 = pyo.Constraint(
            expr=block.soc >= 0.5 - M * block.z_low_soc
        )

