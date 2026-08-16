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

    def model_optimization(self, prosumer, heat_demand, flex_demand, objective_mode="track_flex", update_internal_state=True):

        """
        objective_mode: "track_flex":
            Tracks the requested device-side flexibility:
                P_device =  flex_demand

        objective_mode: min grid consumption:
            Calculates the operating point that minimizes mall grid consumption
                P_grid = P_residual_mall - P_device
            P_residual_mall (mall el. load - pv generation) is constant for this timestep,
            minimizing P_grid is equivalent to maximizing:
                P_device = P_CHP - P_BHP

        objective_mode: max_grid_consumption:
            Calculates the operating point that maximizes mall grid consumption
                P_grid = P_residual_mall - P_device
            maximizing P_grid is equivalent to minimizing:
                P_device = P_CHP - P_BHP

    update_internal_state:
        True:
            Use for the final applied dispatch
            Updates internal CHP state

        False:
            Use for flexibility bounds calculation
            Does not update internal state, so baseline, min and max cases can be calculated from the previous state

        Returns:
        p_bhp, p_chp, feasible
        """

        # ── Basis-Modell aufbauen (Blöcke, Constraints) ──────────────────
        def build_base_model():
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

            # added:
            # CHP el. generation - BHP el. consumption
            # +ve -> CHP increases generation, reduces import and supports the grid
            # -ve -> BHP increases consumption, increases grid import
            m.p_device = pyo.Expression(expr=sum(el_terms))

            m.el_bal = pyo.Expression(expr=sum(el_terms) - m.flex_demand)

            return m

        # Added: helper function
        # packed the solver.solve inside helper
        def solve_model(model, stage):
            try:
                res = solver.solve(model, tee=False)
            except RuntimeError as exc:
                print(f"\nOptimization failed in {stage}.")
                print(f"Reason: {exc}")
                return None, False
            except Exception as exc:
                print(f"\nOptimization error in {stage}.")
                print(f"Reason: {exc}")
                return None, False

            feasible = (res.solver.status == SolverStatus.ok and res.solver.termination_condition
                        in (TerminationCondition.optimal, TerminationCondition.feasible))

            if not feasible:
                print(f"\nOptimization not feasible in {stage}.")
                print(f"Solver status: {res.solver.status}")
                print(f"Termination condition: {res.solver.termination_condition}")

            return res, feasible

        solver = pyo.SolverFactory('appsi_highs')
        EPS = 1e-4
        eps_soc = 0.0001# Toleranz für Constraint-Weitergabe
        EPS_CHP_OFF = 0.5  # [kW] – darunter gilt CHP als "aus"

        # ── Min-Downtime State ────────────────────────────────────────────
        if not hasattr(self, '_chp_downtime'):
            self._chp_downtime = {}

        m = build_base_model()

        # ── PRE-CONSTRAINT: Min-Downtime (nur wenn Counter > 0) ──────────
        for idx in m.chp_index:
            if self._chp_downtime.get(idx, 0) > 0:
                m.add_component(
                    f"chp_min_downtime_{idx}",
                    pyo.Constraint(expr=m.chp[idx].p_el == 0)
                )

        if objective_mode == "track_flex":
            # retained existing behaviour:
            # minimize |P_device - P_flex_target|
            m.t = pyo.Var(domain=pyo.NonNegativeReals)

            m.abs_pos = pyo.Constraint(expr=m.el_bal <= m.t)
            m.abs_neg = pyo.Constraint(expr=-m.el_bal <= m.t)

            m.obj = pyo.Objective(expr=m.t, sense=pyo.minimize)

        elif objective_mode == "min_grid_consumption":
            # P_grid = P_residual_mall - P_device
            # min P_grid = max P_device
            # pyomo minimizes, so minimize -P_device
            m.obj = pyo.Objective(expr=-m.p_device, sense=pyo.minimize)

        elif objective_mode == "max_grid_consumption":
            # P_grid = P_residual_mall - P_device
            # max P_grid = min P_device
            m.obj = pyo.Objective(expr=m.p_device, sense=pyo.minimize)

        else:
            raise ValueError("Unknown objective_mode")

        res1, feasible1 = solve_model(m, "stage 1 tracking objective {objective_mode}")
        # returns p_chp, p_bhp, feasible
        if not feasible1:
            return 0.0, 0.0, False

        # Lock 1st objective result
        if objective_mode == "track_flex":
            primary_opt = pyo.value(m.t)
            m.primary_lock = pyo.Constraint(expr=m.t <= primary_opt + EPS)

        else:
            primary_opt = pyo.value(m.p_device)

            if objective_mode == "min_grid_consumption":
                # Stage 1 for min grid consumption minimized -p_device, so it maximized p_device
                # Lock p_device close to its maximum value
                m.primary_lock = pyo.Constraint(expr=m.p_device >= primary_opt - EPS)

            elif objective_mode == "max_grid_consumption":
                # Stage 1 minimized p_device for max grid consumption
                # Lock p_device close to its minimum value.
                m.primary_lock = pyo.Constraint(expr=m.p_device <= primary_opt + EPS)

        m.obj.deactivate()

        # Stage 2: SOC-Abweichung vom Zielband minimieren

        SOC_TARGET = 0.5  # Mitte des Hysteresebands
        SOC_TOL = 0.1  # Abweichungen des Hyteresebands um Mitte

        m.soc_dev = pyo.Var(m.storage_index, domain=pyo.NonNegativeReals)

        m.soc_dev_pos = pyo.Constraint(
            m.storage_index,
            rule=lambda m, idx: m.soc_dev[idx] >= m.storage[idx].soc - (SOC_TARGET + SOC_TOL)
        )
        m.soc_dev_neg = pyo.Constraint(
            m.storage_index,
            rule=lambda m, idx: m.soc_dev[idx] >= (SOC_TARGET - SOC_TOL) - m.storage[idx].soc
        )

        m.obj2 = pyo.Objective(
            expr=sum(m.soc_dev[idx] for idx in m.storage_index),
            sense=pyo.minimize
        )

        res2, feasible2 = solve_model(m, "stage 2 SOC objective")
        if not feasible2:
            return 0.0, 0.0, False
        soc_dev_opt = sum(pyo.value(m.soc_dev[idx]) for idx in m.storage_index)

        # Abweichungen des SOC vom Zielband einfrieren
        m.soc_dev_lock = pyo.Constraint(
            expr=sum(m.soc_dev[idx] for idx in m.storage_index) <= soc_dev_opt + eps_soc
        )
        m.obj2.deactivate()

        # ── STUFE 3: CHP-Abweichung minimieren ──────────────────────────────────────

        m.chp_dev = pyo.Var(m.chp_index, domain=pyo.NonNegativeReals)
        m.chp_dev_pos = pyo.Constraint(
            m.chp_index,
            rule=lambda m, idx: m.chp_dev[idx] >= m.chp[idx].p_el - m.chp[idx].p_el_prev
        )
        m.chp_dev_neg = pyo.Constraint(
            m.chp_index,
            rule=lambda m, idx: m.chp_dev[idx] >= -(m.chp[idx].p_el - m.chp[idx].p_el_prev)
        )

        #m.obj2.deactivate()
        m.obj3 = pyo.Objective(
            expr=sum(m.chp_dev[idx] for idx in m.chp_index),
            sense=pyo.minimize
        )

        res3, feasible3 = solve_model(m, "stage 3 CHP movement objective")

        if not feasible3:
            return 0.0, 0.0, False

        # Extraction of results
        if len(m.bhp_index):
            p_bhp = pyo.value(next(m.bhp[idx].p_el for idx in m.bhp_index))
        else:
            p_bhp = 0.0

        if len(m.chp_index):
            p_chp = pyo.value(next(m.chp[idx].p_el for idx in m.chp_index))
        else:
            p_chp = 0.0

        p_device = p_chp - p_bhp

        self._last_optimization_result = {"objective_mode": objective_mode, "p_bhp_kw": p_bhp, "p_chp_kw": p_chp,
                                          "p_device_kw": p_device, "flex_demand_kw": flex_demand, "heat_demand_kw": heat_demand}

        # # ── Min-Downtime Counter aktualisieren (nach finalem Solve) ───────
        if update_internal_state:
            for idx in m.chp_index:
                p_el_now = pyo.value(m.chp[idx].p_el)
                p_el_prev = pyo.value(m.chp[idx].p_el_prev)

                if self._chp_downtime.get(idx, 0) > 0:
                    self._chp_downtime[idx] = max(
                        0,
                        self._chp_downtime[idx] - 1,
                    )

                elif p_el_now < EPS_CHP_OFF and p_el_prev >= EPS_CHP_OFF:
                    self._chp_downtime[idx] = 4

        return p_bhp, p_chp, True

    def calculate_flexibility_bounds(self, prosumer, heat_demand, flex_demand=0.0):

        p_bhp_base, p_chp_base, feasible_base = self.model_optimization(
                prosumer=prosumer,
                heat_demand=heat_demand,
                flex_demand=flex_demand,
                objective_mode="track_flex",
                update_internal_state=False,
            )

        p_bhp_support, p_chp_support, feasible_support = self.model_optimization(
                prosumer=prosumer,
                heat_demand=heat_demand,
                flex_demand=0.0,
                objective_mode="min_grid_consumption",
                update_internal_state=False,
            )

        p_bhp_absorb, p_chp_absorb, feasible_absorb = self.model_optimization(
                prosumer=prosumer,
                heat_demand=heat_demand,
                flex_demand=0.0,
                objective_mode="max_grid_consumption",
                update_internal_state=False,
            )

        feasible = feasible_base and feasible_support and feasible_absorb

        if not feasible:
            return {"feasible": False,
                    "p_bhp_base_kw": np.nan,
                    "p_chp_base_kw": np.nan,
                    "p_device_base_kw": np.nan,
                    "p_bhp_support_kw": np.nan,
                    "p_chp_support_kw": np.nan,
                    "p_device_max_support_kw": np.nan,
                    "p_bhp_absorb_kw": np.nan,
                    "p_chp_absorb_kw": np.nan,
                    "p_device_max_absorption_kw": np.nan,
                }

        p_device_base_kw = p_chp_base - p_bhp_base
        p_device_max_support_kw = p_chp_support - p_bhp_support
        p_device_max_absorption_kw = p_chp_absorb - p_bhp_absorb

        return {"feasible": True,
                "p_bhp_base_kw": p_bhp_base,
                "p_chp_base_kw": p_chp_base,
                "p_device_base_kw": p_device_base_kw,
                "p_bhp_support_kw": p_bhp_support,
                "p_chp_support_kw": p_chp_support,
                "p_device_max_support_kw": p_device_max_support_kw,
                "p_bhp_absorb_kw": p_bhp_absorb,
                "p_chp_absorb_kw": p_chp_absorb,
                "p_device_max_absorption_kw": p_device_max_absorption_kw
                }

        # # ── STUFE 1: Flex-Ziel ───────────────────────────────────────────
        # # baseline consumption tracking flex target
        # m.t = pyo.Var(domain=pyo.NonNegativeReals)
        # #m.abs_pos = pyo.Constraint(expr=m.el_bal <= m.t)
        # #m.abs_neg = pyo.Constraint(expr=-m.el_bal <= m.t)
        #
        # #m.obj = pyo.Objective(expr=m.t, sense=pyo.minimize)
        #
        # #res1 = solver.solve(m, tee=False)
        # #t_opt = pyo.value(m.t)
        #
        # # ── STUFE 2: SOC-Abweichungen minimieren ──────────────────────────────────────
        # # Flex-Ergebnis einfrieren
        # m.flex_lock = pyo.Constraint(expr=m.t <= t_opt + EPS)
        #
        # m.obj.deactivate()
        #
        # # Stage 2: SOC-Abweichung vom Zielband minimieren
        # SOC_TARGET = 0.5  # Mitte des Hysteresebands
        # SOC_TOL = 0.1  # Abweichungen des Hyteresebands um Mitte
        #
        # m.soc_dev = pyo.Var(m.storage_index, domain=pyo.NonNegativeReals)
        #
        # m.soc_dev_pos = pyo.Constraint(
        #     m.storage_index,
        #     rule=lambda m, idx: m.soc_dev[idx] >= m.storage[idx].soc - (SOC_TARGET + SOC_TOL)
        # )
        # m.soc_dev_neg = pyo.Constraint(
        #     m.storage_index,
        #     rule=lambda m, idx: m.soc_dev[idx] >= (SOC_TARGET - SOC_TOL) - m.storage[idx].soc
        # )
        #
        # m.obj2 = pyo.Objective(
        #     expr=sum(m.soc_dev[idx] for idx in m.storage_index),
        #     sense=pyo.minimize
        # )
        #
        # res2 = solver.solve(m)
        # soc_dev_opt = sum(pyo.value(m.soc_dev[idx]) for idx in m.storage_index)
        #
        # # Abweichungen des SOC vom Zielband einfrieren
        # m.soc_dev_lock = pyo.Constraint(
        #     expr=sum(m.soc_dev[idx] for idx in m.storage_index) <= soc_dev_opt + eps_soc
        # )
        # # ── STUFE 3: CHP-Abweichung minimieren ──────────────────────────────────────
        #
        # m.chp_dev = pyo.Var(m.chp_index, domain=pyo.NonNegativeReals)
        # m.chp_dev_pos = pyo.Constraint(
        #     m.chp_index,
        #     rule=lambda m, idx: m.chp_dev[idx] >= m.chp[idx].p_el - m.chp[idx].p_el_prev
        # )
        # m.chp_dev_neg = pyo.Constraint(
        #     m.chp_index,
        #     rule=lambda m, idx: m.chp_dev[idx] >= -(m.chp[idx].p_el - m.chp[idx].p_el_prev)
        # )
        #
        # m.obj2.deactivate()
        # m.obj3 = pyo.Objective(
        #     expr=sum(m.chp_dev[idx] for idx in m.chp_index),
        #     sense=pyo.minimize
        # )
        #
        # res3 = solver.solve(m, tee=False)
        #
        # # # ── Min-Downtime Counter aktualisieren (nach finalem Solve) ───────
        # for idx in m.chp_index:
        #     p_el_now = pyo.value(m.chp[idx].p_el)
        #     p_el_prev = pyo.value(m.chp[idx].p_el_prev)
        #
        #     if self._chp_downtime.get(idx, 0) > 0:
        #         # Sperre läuft ab
        #         self._chp_downtime[idx] = max(0, self._chp_downtime[idx] - 1)
        #     elif p_el_now < EPS_CHP_OFF and p_el_prev >= EPS_CHP_OFF:
        #         # CHP gerade ausgeschaltet → 1 Zeitschritt sperren
        #         self._chp_downtime[idx] = 4
        #
        #
        # feasible = (
        #         res3.solver.status == SolverStatus.ok
        #         and res3.solver.termination_condition in (
        #             TerminationCondition.optimal,
        #             TerminationCondition.feasible  # ← auch akzeptieren!
        #         )
        # )
        #
        # if feasible:
        #
        #     p_bhp = pyo.value(next(m.bhp[idx].p_el for idx in m.bhp_index))
        #     p_chp = pyo.value(next(m.chp[idx].p_el for idx in m.chp_index))
        #
        # else:
        #     # ── Fallback: Vorherigen Zustand fortschreiben ─────────────────
        #     p_bhp, p_chp = (0, 0)
        #
        # return p_bhp, p_chp, feasible

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
        if getattr(self, "collect_flex_bounds", False):
            bounds = self.calculate_flexibility_bounds(
                prosumer=prosumer,
                heat_demand=q_demand_kw,
                flex_demand=p_flex_kw,
            )

            if not hasattr(self, "_flex_bounds_log"):
                self._flex_bounds_log = {}

            self._flex_bounds_log[self.time] = bounds

        p_el_bhp_in, p_el_chp_out, feasible = self.model_optimization(prosumer=prosumer, heat_demand=q_demand_kw,
                                                                      flex_demand=p_flex_kw,
                                                                      objective_mode="track_flex",
                                                                      update_internal_state=True)

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

        # ── Vorherigen Zustand laden ──────────────────────────────────────
        ts_prev = self.time - pd.Timedelta(seconds=self.resol)

        if ts_prev in prosumer.controller_results:
            p_el_prev_val = float(prosumer.controller_results[ts_prev][index].get(f"p_el_out_kw", 0.0))
        else:
            p_el_prev_val = 0.0

        block.p_el_prev = pyo.Param(initialize=p_el_prev_val)

    def _add_storage(self, prosumer, block, index):
        """
        Fügt einen Wärmespeicher zum Optimierungsmodell hinzu.
        """
        ctrl = prosumer.controller.loc[index]["object"]
        storage_cap_kwh = ctrl.element_instance["q_capacity_kwh"].iloc[0]
        init_soc = ctrl.element_instance["init_soc"].iloc[0]
        resol = self.resol
        ts = self.time

        # previous timestep
        ts_prev = ts - pd.Timedelta(seconds=resol)
        if ts_prev in prosumer.controller_results:
            raw_soc_prev = prosumer.controller_results[ts_prev][index]["soc"]
        else:
            # first timestep → SOC = 0
            raw_soc_prev = init_soc
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

