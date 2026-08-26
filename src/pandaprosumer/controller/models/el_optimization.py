import json
import os

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

from pandaprosumer.controller.base import BasicProsumerController


class ElectricalOptimizationController(BasicProsumerController):
    """
    Electrical optimization controller for CHP and battery dispatch

    Power balance:
        p_grid = p_demand - p_pv - p_chp - p_battery

        p_battery = p_discharge - p_charge

    Target:
        no external request:
            p_target = p_demand - p_pv

        positive external request:
            p_target = p_baseline - p_flex

        direct target:
            p_target = p_grid_target

    Objective:
        minimize:
            target tracking error
            + contractual-limit violation
            + device preference cost

    Positive battery power means discharge.
    Negative battery power means charge.
    """

    def __init__(self, prosumer, optimization_object, order, level, in_service=True, index=None, solver_name="appsi_highs",
                 p_large_requested_threshold_kw=500.0, sustained_request_timesteps=4, request_tolerance_kw=1e-6, weight_target=1e5, weight_contract=1e7, **kwargs):
        """
        Initialize the electrical optimization controller

        :param prosumer: The prosumer object
        :param optimizationp_object: The optimization object
        :param order: The order of the controller
        :param level: The level of the controller
        :param in_service: The in-service status of the controller
        :param index: The index of the controller
        :param kwargs: Additional keyword arguments

        Optimization parameters:
            solver_name: Pyomo solver
            p_large_requested_threshold_kw: Large-request threshold [kW]
            sustained_request_timesteps: Sustained-request duration [number of steps]
            request_tolerance_kw: Request detection tolerance [kW]
            weight_target: Target-tracking penalty
            weight_contract: Contract-violation penalty
        """
        super().__init__(prosumer, optimization_object, order=order, level=level, in_service=in_service, index=index, **kwargs)

        self.solver_name = solver_name
        self.p_large_requested_threshold_kw = float(p_large_requested_threshold_kw)
        self.sustained_request_timesteps = int(sustained_request_timesteps)
        self.request_tolerance_kw = float(request_tolerance_kw)
        self.weight_target = float(weight_target)
        self.weight_contract = float(weight_contract)

        self.active_request_steps = 0
        self.active_request_steps_backup = 0

        self.electricity_price_eur_per_mwh = 100.0
        self.gas_price_eur_per_mwh = 40.0

    # Inputs
    @property
    def _p_el_demand_kw(self):
        try:
            return self._get_input("p_el_demand_kw")
        except (KeyError, AttributeError):
            return 0.0

    @property
    def _p_pv_in_kw(self):
        try:
            return self._get_input("p_pv_in_kw")
        except (KeyError, AttributeError):
            return 0.0

    @property
    def _p_contract_kw(self):
        try:
            return self._get_input("p_contract_kw")
        except (KeyError, AttributeError):
            return np.inf

    @property
    def _p_flex_kw(self):
        try:
            return self._get_input("p_flex_kw")
        except (KeyError, AttributeError):
            return 0.0

    @property
    def _p_grid_target_kw(self):
        try:
            return self._get_input("p_grid_target_kw")
        except (KeyError, AttributeError):
            return np.nan

    @property
    def _electricity_price_eur_per_mwh(self):
        try:
            return self._get_input("electricity_price_eur_per_mwh")
        except (KeyError, AttributeError):
            return self.electricity_price_eur_per_mwh

    @property
    def _gas_price_eur_per_mwh(self):
        try:
            return self._get_input("gas_price_eur_per_mwh")
        except (KeyError, AttributeError):
            return self.gas_price_eur_per_mwh

    def to_scalar(self, value, default=0.0):
        """
        Convert a mapped scalar-like input to float.
        """
        if value is None:
            return float(default)

        if isinstance(value, np.ndarray):
            if value.size == 0:
                return float(default)
            value = value.flat[0]

        elif hasattr(value, "iloc"):
            if len(value) == 0:
                return float(default)
            value = value.iloc[0]

        elif isinstance(value, (list, tuple)):
            if len(value) == 0:
                return float(default)
            value = value[0]

        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    # Main optimization
    def model_optimization(self, prosumer, p_el_demand_kw, p_pv_in_kw, p_contract_kw, p_flex_kw, p_grid_target_kw,
                           electricity_price_eur_per_mwh, gas_price_eur_per_mwh):
        """
        Build and solve one electrical dispatch problem
        """

        # Determine the grid target: uncontrolled net grid import is calculated
        p_grid_baseline_kw = (p_el_demand_kw - p_pv_in_kw)

        below_limit = (not np.isfinite(p_contract_kw)) or (p_grid_baseline_kw < p_contract_kw)

        # Desired grid import that the optimizer should track
        direct_target_available = np.isfinite(p_grid_target_kw)

        # if external request for a grid target is significantly greater than an infinitesimally small number greater than 0
        request_active = (abs(p_flex_kw) > self.request_tolerance_kw)

        # Target 1: if a direct grid target is provided
        if direct_target_available:
            target_source = "direct_grid_target"
            p_target_kw = p_grid_target_kw

        #Target 2: if not, then check if an external flex request is provided, if so then the target is baseline grid import + flex request
        # p flex = -ve, increase grid import
        # p_flex = +ve, reduce grid import
        elif request_active:
            target_source = "external_flex_request"
            p_target_kw = (p_grid_baseline_kw - p_flex_kw)

        #target 3: if neither direct target nor flex request is available, then the target becomes the uncontrolled grid import
        else:
            target_source = "baseline_operation"
            p_target_kw = p_grid_baseline_kw

            if below_limit and np.isfinite(p_contract_kw):
                # Laden bis Vertragslimit erlauben, kein target_error für Laden
                p_target_kw = p_contract_kw
            else:
                p_target_kw = p_grid_baseline_kw

        # counter for tracking consecutive timesteps with an external flexibility request, if the request active = 0, then the counter becomes 0 for the next time step (next 15 min)
        if request_active:
            next_active_request_steps = (self.active_request_steps + 1)
        else:
            next_active_request_steps = 0

        # classify a flex request by large and small, so that later a choice between use of CHP or battery can be made
        request_is_large = (abs(p_flex_kw) >= self.p_large_requested_threshold_kw)
        # This classification influences whether the optimizer prefers:
        # 1. battery response for short requests (OR)
        # 2. CHP startup for large or sustained requests
        request_is_sustained = (next_active_request_steps >= self.sustained_request_timesteps)

        # Build base model
        model = pyo.ConcreteModel()

        chp_indices = []
        battery_indices = []

        for index, row in prosumer.controller.iterrows():
            controller_name = (row["object"].__class__.__name__)

            if controller_name == "IceChpController":
                chp_indices.append(index)

            elif controller_name == "BatteryStorageController":
                battery_indices.append(index)

        model.chp_index = pyo.Set(initialize=chp_indices)
        model.battery_index = pyo.Set(initialize=battery_indices)

        model.chp = pyo.Block( model.chp_index)
        model.battery = pyo.Block(model.battery_index)

        for index in model.chp_index:
            self._add_chp(prosumer, model.chp[index], index)

        for index in model.battery_index:
            self._add_battery(prosumer, model.battery[index], index)

        # Grid power balance
        model.p_grid_kw = pyo.Expression(expr=(p_el_demand_kw - p_pv_in_kw - sum(model.chp[index].p_el for index in model.chp_index)
                                               - sum(model.battery[index].p_signed for index in model.battery_index))
                                         )

        # Absolute deviation between actual grid import and the target, minimize the deviation of grid import from target P
        #Term 1: delta |P_grid - P_target_requested_kw|
        model.target_error = pyo.Var(domain=pyo.NonNegativeReals)

        model.target_error_positive = pyo.Constraint(expr=(model.p_grid_kw - p_target_kw <= model.target_error))
        model.target_error_negative = pyo.Constraint(expr=(p_target_kw - model.p_grid_kw <= model.target_error))

        # contractual limit
        model.contract_violation = pyo.Var(domain=pyo.NonNegativeReals)

        # Term 2: P_grid <= P_contractual + Contractual_violation
        if np.isfinite(p_contract_kw):
            model.contract_limit = pyo.Constraint(expr=(model.p_grid_kw <= p_contract_kw + model.contract_violation))
        else:
            model.contract_violation_zero = pyo.Constraint(expr=model.contract_violation == 0.0)

        model.p_grid_import_kw = pyo.Var(domain=pyo.NonNegativeReals)
        model.grid_import_lb = pyo.Constraint(
            expr=model.p_grid_import_kw >= model.p_grid_kw
        )

        # Term 3: Device preference objective based on 3 factors
        # 1. Previous CHP state (ON) - to ensure continuous operation instead of frequent change of state
        # 2. Previous CHP state (OFF) - P_request_kw is greater than requested threshold, request is large or sustained -> CHP is preferred
        #                             - P_request_kw is smaller than requested threshold, request is short -> prefer battery discharge    
        
        previous_chp_state = sum(model.chp[index].p_previous for index in model.chp_index)

        previous_chp_state_on = (pyo.value(previous_chp_state) > 1e-6)

        chp_output = sum(model.chp[index].p_el for index in model.chp_index)
        chp_startup = sum(model.chp[index].startup for index in model.chp_index)

        # Absolute change from the previous CHP operating point
        model.chp_deviation = pyo.Var(domain=pyo.NonNegativeReals)

        model.chp_deviation_positive = pyo.Constraint(expr=(model.chp_deviation >= chp_output - previous_chp_state))
        model.chp_deviation_negative = pyo.Constraint(expr=(model.chp_deviation >= previous_chp_state - chp_output))

        battery_discharge = sum(model.battery[index].p_discharge for index in model.battery_index)
        battery_charge = sum(model.battery[index].p_charge for index in model.battery_index)

        # When active, battery is only charged with electricity from the grid
        model.charge_from_grid_only = pyo.Constraint(
            expr=model.p_grid_import_kw >= battery_charge
        )

        # penalty sum = p_el_out _kw|(t-1) + battery disch + battery charge
        if previous_chp_state_on:
            preference_cost = (0.2 * model.chp_deviation + 8.0 * battery_discharge + 1.0 * battery_charge)

        elif request_is_large or request_is_sustained:
            preference_cost = (5.0 * chp_startup + 0.2 * model.chp_deviation + 6.0 * battery_discharge + 1.0 * battery_charge)

        else:
            preference_cost = (500.0 * chp_startup + 5.0 * model.chp_deviation + 0.5 * battery_discharge + 1.0 * battery_charge)


        # Energiekosten-Term
        # Gaskosten BHKW: Gasverbrauch = p_el / eta_el  →  Kosten = gas_price / eta_el * p_el
        # chp_gas_cost = sum(
        #     (gas_price_eur_per_mwh / 0.36) * model.chp[i].p_el  # eta_chp hardcoded 0.36
        #     for i in model.chp_index
        # )
        # grid_import_cost = electricity_price_eur_per_mwh * model.p_grid_import_kw
        #
        # weight_energy_cost = 5
        # if below_limit:
        #     battery_charge_credit = electricity_price_eur_per_mwh * battery_charge
        #     energy_cost = weight_energy_cost * (grid_import_cost + chp_gas_cost - battery_charge_credit)
        #     preference_cost = preference_cost - 2 * battery_charge
        # else:
        #     energy_cost = weight_energy_cost * (grid_import_cost + chp_gas_cost)


        # Objective function
        model.objective = pyo.Objective(expr=(self.weight_target * model.target_error
                                              + self.weight_contract * model.contract_violation
                                              + preference_cost
                                              # + energy_cost
                                              ), sense=pyo.minimize)
        # Solve
        solver = pyo.SolverFactory(self.solver_name)
        if not solver.available(False):
            raise RuntimeError(f"Solver '{self.solver_name}' is unavailable")

        solver_result = solver.solve(model, tee=False)

        feasible = (solver_result.solver.status
                    in (SolverStatus.ok, SolverStatus.warning)
                    and solver_result.solver.termination_condition
                    in (TerminationCondition.optimal, TerminationCondition.feasible))

        # Extract results
        if feasible:
            p_el_chp_kw = sum(float(pyo.value(model.chp[index].p_el)) for index in model.chp_index)
            p_battery_charge_kw = sum(float(pyo.value(model.battery[index].p_charge)) for index in model.battery_index)
            p_battery_discharge_kw = sum(float(pyo.value(model.battery[index].p_discharge)) for index in model.battery_index)
            p_battery_kw = (p_battery_discharge_kw - p_battery_charge_kw)
            p_grid_dispatch_kw = float(pyo.value(model.p_grid_kw))
            contract_violation_kw = float(pyo.value(model.contract_violation))
            battery_soc = float(np.mean([float(pyo.value(model.battery[index].soc)) for index in model.battery_index]))
            # --- Ladeaufteilung (Heuristik) ---
            # CHP-Überschuss = CHP-Erzeugung minus Nettolast (ohne Batterie)
            chp_surplus_kw = max(0.0, p_el_chp_kw - p_grid_baseline_kw)
            p_charge_from_chp_kw = min(chp_surplus_kw, p_battery_charge_kw)
            p_charge_from_grid_kw = p_battery_charge_kw - p_charge_from_chp_kw
            dominant_charge_source = (
                "chp" if p_charge_from_chp_kw > p_charge_from_grid_kw else
                "grid" if p_charge_from_grid_kw > p_charge_from_chp_kw else
                "equal"
            )

            # --- Stromkosten [EUR/h] ---
            # Netzstrom gesamt
            cost_grid_total_eur_per_h = max(0.0, p_grid_dispatch_kw) * electricity_price_eur_per_mwh / 1000
            # Netzstrom für Batterieladung
            cost_charge_from_grid_eur_per_h = electricity_price_eur_per_mwh / 1000
            # CHP-Strom für Batterieladung (Gaskosten-Anteil)
            cost_charge_from_chp_eur_per_h = (gas_price_eur_per_mwh / 0.36) / 1000


        else:
            p_el_chp_kw = 0.0
            p_battery_charge_kw = 0.0
            p_battery_discharge_kw = 0.0
            p_battery_kw = 0.0
            p_grid_dispatch_kw = p_grid_baseline_kw
            contract_violation_kw = max(0.0, p_grid_dispatch_kw - p_contract_kw)
            battery_soc = np.nan
            p_charge_from_chp_kw = 0.0
            p_charge_from_grid_kw = 0.0
            dominant_charge_source = "none"
            cost_grid_total_eur_per_h = 0.0
            cost_charge_from_grid_eur_per_h = 0.0
            cost_charge_from_chp_eur_per_h = 0.0

        optimized_results = {
            "feasible": bool(feasible),
            "target_source": target_source,
            "external_request_active": request_active,
            "request_is_large": request_is_large,
            "request_is_sustained": request_is_sustained,
            "active_request_steps": next_active_request_steps,
            "p_el_demand_kw": p_el_demand_kw,
            "p_pv_in_kw": p_pv_in_kw,
            "p_contract_kw": p_contract_kw,
            "p_flex_request_kw": p_flex_kw,
            "p_grid_target_input_kw": p_grid_target_kw,
            "p_grid_baseline_kw": p_grid_baseline_kw,
            "p_grid_target_kw": p_target_kw,
            "p_grid_dispatch_kw": p_grid_dispatch_kw,
            "grid_target_error_kw": abs(p_grid_dispatch_kw - p_target_kw),
            "contract_violation_kw": contract_violation_kw,
            "flex_activated_kw": (p_grid_baseline_kw - p_grid_dispatch_kw),
            "dispatch_p_battery_kw": p_battery_kw,
            "dispatch_p_battery_charge_kw": p_battery_charge_kw,
            "dispatch_p_battery_discharge_kw": p_battery_discharge_kw,
            "dispatch_battery_soc": battery_soc,
            "dispatch_p_el_chp_kw": p_el_chp_kw,
            # Ladeaufteilung
            "dispatch_p_battery_charge_from_grid_kw": p_charge_from_grid_kw,
            "dispatch_p_battery_charge_from_chp_kw": p_charge_from_chp_kw,
            "dominant_charge_source": dominant_charge_source,

            # Stromkosten [EUR/h]
            "cost_grid_total_eur_per_h": cost_grid_total_eur_per_h,
            "cost_charge_from_grid_eur_per_h": cost_charge_from_grid_eur_per_h,
            "cost_charge_from_chp_eur_per_h": cost_charge_from_chp_eur_per_h,

            "solver_status": str(solver_result.solver.status),
            "termination_condition": str(solver_result.solver.termination_condition)
        }

        return p_battery_kw, p_el_chp_kw, optimized_results, next_active_request_steps

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)

        if not hasattr(prosumer, "controller_results"):
            prosumer.controller_results = {}

        p_el_demand_kw = self.to_scalar(self._p_el_demand_kw, default=0.0)
        p_pv_in_kw = self.to_scalar(self._p_pv_in_kw, default=0.0)
        p_contract_kw = self.to_scalar(self._p_contract_kw, default=np.inf)
        p_flex_kw = self.to_scalar(self._p_flex_kw, default=0.0)
        p_grid_target_kw = self.to_scalar(self._p_grid_target_kw, default=np.nan)
        electricity_price = self.to_scalar(self._electricity_price_eur_per_mwh,
                                           default=self.electricity_price_eur_per_mwh)
        gas_price = self.to_scalar(self._gas_price_eur_per_mwh,
                                   default=self.gas_price_eur_per_mwh)

        p_battery_kw, p_el_chp_kw, optimized_results, next_active_request_steps = \
            self.model_optimization(
                prosumer=prosumer,
                p_el_demand_kw=p_el_demand_kw,
                p_pv_in_kw=p_pv_in_kw,
                p_contract_kw=p_contract_kw,
                p_flex_kw=p_flex_kw,
                p_grid_target_kw=p_grid_target_kw,
                electricity_price_eur_per_mwh=electricity_price,  # neu
                gas_price_eur_per_mwh=gas_price,  # neu
            )

        # p_battery_kw, p_el_chp_kw, optimized_results, next_active_request_steps = self.model_optimization(
        #     prosumer=prosumer,
        #     p_el_demand_kw=p_el_demand_kw,
        #     p_pv_in_kw=p_pv_in_kw,
        #     p_contract_kw=p_contract_kw,
        #     p_flex_kw=p_flex_kw,
        #     p_grid_target_kw=p_grid_target_kw
        # )

        self.last_result = optimized_results

        if not hasattr(prosumer, "optimizer_controller_results"):
            prosumer.optimizer_controller_results = {}

        prosumer.optimizer_controller_results[self.time] = optimized_results
        result = np.array([[p_battery_kw, p_el_chp_kw]], dtype=float)
        self.finalize(prosumer, result)
        self.active_request_steps = next_active_request_steps
        self.applied = True

    def time_step(self, prosumer, time):
        """
        Initialize the controller state for a new timestep.
        """
        super().time_step(prosumer, time)

        self.time = time
        self.applied = False

        if prosumer.rerun:
            self.active_request_steps = self.active_request_steps_backup
        else:
            self.active_request_steps_backup = self.active_request_steps

    def is_converged(self, container):
        return self.applied

    # CHP model
    def _add_chp(self, prosumer, block, index):
        """
        Add the existing CHP to the electrical optimization model.
        """
        ctrl = prosumer.controller.loc[index]["object"]
        size_kw = ctrl.element_instance["size"].iloc[0]

        base_dir = os.path.dirname(__file__)
        path = os.path.abspath(os.path.join(base_dir, "..", "..", "library", "chp_maps", "ice_chp_maps.json"))

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chp_map = next(m for m in data["chp_ice_map"] if m["__chp_nominal_size_kw__"] == size_kw)

        nominal_size_chp = chp_map["__chp_nominal_size_kw__"]
        load_min, load_max = chp_map["load_limits_percent"]

        p_el_min_chp = load_min / 100.0 * nominal_size_chp
        p_el_max_chp = load_max / 100.0 * nominal_size_chp

        ts_prev = self.time - pd.Timedelta(seconds=self.resol)

        if hasattr(prosumer, "controller_results") and ts_prev in prosumer.controller_results:
            p_el_previous = self.to_scalar(prosumer.controller_results[ts_prev].get(index, {}).get("p_el_out_kw", 0.0))
        else:
            p_el_previous = 0.0

        block.p_el_min = pyo.Param(initialize=p_el_min_chp)
        block.p_el_max = pyo.Param(initialize=p_el_max_chp)
        block.p_previous = pyo.Param(initialize=p_el_previous)

        block.p_el = pyo.Var(domain=pyo.NonNegativeReals)
        block.y = pyo.Var(domain=pyo.Binary)
        block.startup = pyo.Var(domain=pyo.Binary)

        block.minimum_power = pyo.Constraint(expr=block.p_el >= block.p_el_min * block.y)
        block.maximum_power = pyo.Constraint(expr=block.p_el <= block.p_el_max * block.y)
        block.startup_constraint = pyo.Constraint(expr=block.startup >= block.y - int(p_el_previous > 1e-6))

    # Battery model
    def _add_battery(self, prosumer, block, index):
        """
        Add the existing battery to the Pyomo optimization model.
        """
        ctrl = prosumer.controller.loc[index]["object"]
        element = ctrl.element_instance

        # Battery parameters
        capacity_kwh = float(element["e_capacity_kwh"].iloc[0])
        eta_charge = float(element["eta_charge"].iloc[0])
        eta_discharge = float(element["eta_discharge"].iloc[0])
        soc_min = float(element["soc_min"].iloc[0])
        soc_max = float(element["soc_max"].iloc[0])
        self_discharge_per_hour = float(element["self_discharge_per_hour"].iloc[0])

        dt_hours = self.resol / 3600.0
        soc_previous = float(ctrl.soc)

        # Available battery power based on power and SOC limits
        p_charge_available_kw, p_discharge_available_kw = ctrl.available_power_kw(prosumer)

        # SOC after self-discharge
        soc_after_loss = soc_previous * max(0.0, 1.0 - self_discharge_per_hour * dt_hours)

        # Variables
        block.p_charge = pyo.Var(domain=pyo.NonNegativeReals)
        block.p_discharge = pyo.Var(domain=pyo.NonNegativeReals)
        block.soc = pyo.Var(bounds=(soc_min, soc_max))
        block.y_charge = pyo.Var(domain=pyo.Binary)
        block.y_discharge = pyo.Var(domain=pyo.Binary)

        #avoid charge and discharge simultaneously
        block.charge_discharge = pyo.Constraint(expr=block.y_charge + block.y_discharge <= 1)

        # Charging and discharging limits
        block.charge_limit = pyo.Constraint(expr=block.p_charge <= p_charge_available_kw * block.y_charge)
        block.discharge_limit = pyo.Constraint(expr=block.p_discharge <= p_discharge_available_kw * block.y_discharge)

        # SOC balance
        block.soc_balance = pyo.Constraint(expr=block.soc == soc_after_loss
                                                + (eta_charge * block.p_charge - block.p_discharge / eta_discharge) * dt_hours / capacity_kwh)

        # Signed battery power: positive = discharge, negative = charge
        block.p_signed = pyo.Expression(expr=block.p_discharge - block.p_charge)
