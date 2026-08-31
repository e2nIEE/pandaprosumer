from pathlib import Path
import contextlib
import io
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import pandapower as pp
from pandapower.networks import lv_schutterwald
from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_heat_demand,
                                             create_controlled_booster_heat_pump, create_controlled_ice_chp,
                                             create_controlled_heat_storage, create_controlled_battery_storage)
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries

import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition
from pandaprosumer.controller.optimization import OptimizationController
from pandaprosumer.controller.data_model.optimization import OptimizationControllerData
from pandaprosumer.create import create_optimization
from pandaprosumer.controller.models.battery_storage import BatteryStorageController

# ============================================================
# 1. Data preparation
# ============================================================
frequency = "60min"
time_resolution = 3600

project_root = (Path.cwd().parent if Path.cwd().name in ["tutorials", "tutorials_extended"]
                else Path.cwd())

ses_data_file = project_root / "tutorials_extended" / "data" / "ses_data.xlsx"
heat_data_file = project_root / "tutorials_extended" / "data" / "aleja_heat_demand_model_data.xlsx"

ses_data = pd.read_excel(ses_data_file)
ses_data.columns = ses_data.columns.str.strip()
ses_data = ses_data.set_index("Timestamp").sort_index()
required_cols = ["P el sc [kW]", "P pv [kW]"]

for col in required_cols:
    ses_data[col] = (ses_data[col].astype(str).str.replace(",", ".", regex=False))
    ses_data[col] = pd.to_numeric(ses_data[col], errors="coerce")

ses_data = ses_data.dropna(subset=required_cols)
ses_data_1h = ses_data[required_cols].resample("60min").mean().dropna()

start_timestamp = ses_data_1h.index.min()
end_timestamp = start_timestamp + pd.Timedelta(days=8) - pd.Timedelta(hours=1)
ses_data_1h = ses_data_1h.loc[start_timestamp:end_timestamp]

start = ses_data_1h.index.min().strftime("%Y-%m-%d %H:%M:%S")
end = ses_data_1h.index.max().strftime("%Y-%m-%d %H:%M:%S")

p_el_sc_kw = ses_data_1h["P el sc [kW]"].astype(float).to_numpy()
p_pv_kw = ses_data_1h["P pv [kW]"].astype(float).to_numpy()
residual_mall_load_kw = p_el_sc_kw - p_pv_kw

n_steps = len(residual_mall_load_kw)
baseline_flex_target_kw = np.zeros(n_steps)

time_series_data = pd.read_excel(heat_data_file)
if len(time_series_data) < n_steps:
    repeat_factor = int(np.ceil(n_steps / len(time_series_data)))
    time_series_data = pd.concat([time_series_data] * repeat_factor, ignore_index=True)
time_series_data = time_series_data.iloc[:n_steps].copy()
dur = pd.date_range(start=start, periods=n_steps, freq=frequency, tz="utc")
time_series_data.index = dur
time_series_data["flex_demand_kw"] = baseline_flex_target_kw
time_series_data["t_sink_k"] = 350
time_series_data["cycle"] = 1

print("\n SES mall data at 1-hour resolution")
print(f"Start: {start}")
print(f"End: {end}")
print(f"Number of timesteps: {n_steps}")
print(f"P_el_sc min/max: {p_el_sc_kw.min():.3f} / {p_el_sc_kw.max():.3f} kW")
print(f"P_pv min/max: {p_pv_kw.min():.3f} / {p_pv_kw.max():.3f} kW")
print(f"Residual mall load min/max: {residual_mall_load_kw.min():.3f} / {residual_mall_load_kw.max():.3f} kW")

assert len(time_series_data) == n_steps
assert len(baseline_flex_target_kw) == n_steps
assert len(residual_mall_load_kw) == n_steps

# ============================================================
# 2. Monkeypatch battery result column order (upstream bug fix)
# ============================================================
def _battery_finalize_results_fixed(self, prosumer):
    e_capacity_kwh = float(self._get_element_param(prosumer, "e_capacity_kwh"))
    e_stored_kwh = self._soc * e_capacity_kwh

    result = np.array([
        pd.Series(self._soc),
        pd.Series(self.p_storage_kw),
        pd.Series(self.p_charge_kw),
        pd.Series(self.p_discharge_kw),
        pd.Series(self.p_charge_available_kw),
        pd.Series(self.p_discharge_available_kw),
        pd.Series(e_stored_kwh),
        pd.Series(self.p_request_unmet_kw),
    ])

    self.last_result = {
        "soc": self._soc,
        "p_storage_kw": self.p_storage_kw,
        "p_charge_kw": self.p_charge_kw,
        "p_discharge_kw": self.p_discharge_kw,
        "p_charge_available_kw": self.p_charge_available_kw,
        "p_discharge_available_kw": self.p_discharge_available_kw,
        "e_stored_kwh": e_stored_kwh,
        "p_request_unmet_kw": self.p_request_unmet_kw,
    }
    self.finalize(prosumer, result.T)

BatteryStorageController._finalize_results = _battery_finalize_results_fixed

# ============================================================
# 3. Custom OptimizationController with battery support
# ============================================================
class OptimizationControllerWithBattery(OptimizationController):
    def _add_battery(self, prosumer, block, index):
        ctrl = prosumer.controller.loc[index]["object"]
        e_capacity_kwh = float(ctrl.element_instance["e_capacity_kwh"].iloc[0])
        p_charge_max_kw = float(ctrl.element_instance["p_charge_max_kw"].iloc[0])
        p_discharge_max_kw = float(ctrl.element_instance["p_discharge_max_kw"].iloc[0])
        eta_charge = float(ctrl.element_instance["eta_charge"].iloc[0])
        eta_discharge = float(ctrl.element_instance["eta_discharge"].iloc[0])
        soc_min = float(ctrl.element_instance["soc_min"].iloc[0])
        soc_max = float(ctrl.element_instance["soc_max"].iloc[0])
        self_discharge_per_hour = float(ctrl.element_instance["self_discharge_per_hour"].iloc[0])

        resol = self.resol
        dt_h = resol / 3600.0
        ts_prev = self.time - pd.Timedelta(seconds=resol)

        if ts_prev in prosumer.controller_results:
            raw_soc_prev = prosumer.controller_results[ts_prev][index]["soc"]
            soc_prev = self.to_scalar(raw_soc_prev)
        else:
            soc_prev = float(getattr(ctrl, "_soc", 0.5))

        soc_prev_after_loss = min(max(soc_prev * max(0.0, 1.0 - self_discharge_per_hour * dt_h), soc_min), soc_max)

        block.soc_prev = pyo.Param(initialize=soc_prev_after_loss)
        block.e_capacity_kwh = pyo.Param(initialize=e_capacity_kwh)
        block.resol = pyo.Param(initialize=resol)

        block.p_charge = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0, p_charge_max_kw))
        block.p_discharge = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0, p_discharge_max_kw))
        block.soc = pyo.Var(bounds=(soc_min, soc_max))
        block.y_charge = pyo.Var(domain=pyo.Binary)
        block.y_discharge = pyo.Var(domain=pyo.Binary)

        block.charge_discharge_excl = pyo.Constraint(expr=block.y_charge + block.y_discharge <= 1)
        block.charge_on = pyo.Constraint(expr=block.p_charge <= p_charge_max_kw * block.y_charge)
        block.discharge_on = pyo.Constraint(expr=block.p_discharge <= p_discharge_max_kw * block.y_discharge)

        block.soc_balance = pyo.Constraint(
            expr=block.soc == block.soc_prev
            + eta_charge * block.p_charge * block.resol / 3600 / block.e_capacity_kwh
            - block.p_discharge * block.resol / 3600 / (eta_discharge * block.e_capacity_kwh)
        )

        block.p_el = pyo.Expression(expr=block.p_discharge - block.p_charge)

    def model_optimization(self, prosumer, heat_demand, flex_demand, objective_mode="track_flex", update_internal_state=True):
        def build_base_model():
            m = pyo.ConcreteModel()
            m.heat_demand = pyo.Param(initialize=heat_demand)
            m.flex_demand = pyo.Param(initialize=flex_demand)

            bhp_idx, chp_idx, storage_idx, battery_idx = [], [], [], []
            for idx, row in prosumer.controller.iterrows():
                if row["level"] != 2:
                    continue
                cname = row["object"].__class__.__name__
                if cname == "BoosterHeatPumpController":
                    bhp_idx.append(idx)
                elif cname == "IceChpController":
                    chp_idx.append(idx)
                elif cname == "HeatStorageController":
                    storage_idx.append(idx)
                elif cname == "BatteryStorageController":
                    battery_idx.append(idx)

            m.bhp_index = pyo.Set(initialize=bhp_idx)
            m.chp_index = pyo.Set(initialize=chp_idx)
            m.storage_index = pyo.Set(initialize=storage_idx)
            m.battery_index = pyo.Set(initialize=battery_idx)

            m.bhp = pyo.Block(m.bhp_index)
            m.chp = pyo.Block(m.chp_index)
            m.storage = pyo.Block(m.storage_index)
            m.battery = pyo.Block(m.battery_index)

            for idx in m.bhp_index:
                self._add_booster_heatpump(prosumer, m.bhp[idx], idx)
            for idx in m.chp_index:
                self._add_chp(prosumer, m.chp[idx], idx)
            for idx in m.storage_index:
                self._add_storage(prosumer, m.storage[idx], idx)
            for idx in m.battery_index:
                self._add_battery(prosumer, m.battery[idx], idx)

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
            for idx in m.battery:
                el_terms.append(m.battery[idx].p_el)

            m.p_device = pyo.Expression(expr=sum(el_terms))
            m.el_bal = pyo.Expression(expr=sum(el_terms) - m.flex_demand)
            return m

        def solve_model(model, stage):
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    res = solver.solve(model, tee=False)
            except Exception as exc:
                print(f"\nOptimization error in {stage}: {exc}")
                return None, False
            feasible = (res.solver.status == SolverStatus.ok and res.solver.termination_condition
                        in (TerminationCondition.optimal, TerminationCondition.feasible))
            if not feasible:
                print(f"\nOptimization not feasible in {stage}. Status: {res.solver.status}, "
                      f"Termination: {res.solver.termination_condition}")
            return res, feasible

        solver = pyo.SolverFactory('appsi_highs')
        solver.options["log_to_console"] = False
        EPS = 1e-4
        eps_soc = 0.0001
        EPS_CHP_OFF = 0.5

        if not hasattr(self, '_chp_downtime'):
            self._chp_downtime = {}

        m = build_base_model()

        for idx in m.chp_index:
            if self._chp_downtime.get(idx, 0) > 0:
                m.add_component(f"chp_min_downtime_{idx}", pyo.Constraint(expr=m.chp[idx].p_el == 0))

        # Stage 1: track flex / min or max grid consumption
        if objective_mode == "track_flex":
            m.t = pyo.Var(domain=pyo.NonNegativeReals)
            m.abs_pos = pyo.Constraint(expr=m.el_bal <= m.t)
            m.abs_neg = pyo.Constraint(expr=-m.el_bal <= m.t)
            m.obj = pyo.Objective(expr=m.t, sense=pyo.minimize)
        elif objective_mode == "min_grid_consumption":
            m.obj = pyo.Objective(expr=-m.p_device, sense=pyo.minimize)
        elif objective_mode == "max_grid_consumption":
            m.obj = pyo.Objective(expr=m.p_device, sense=pyo.minimize)
        else:
            raise ValueError("Unknown objective_mode")

        res1, feasible1 = solve_model(m, f"stage 1 tracking objective {objective_mode}")
        if not feasible1:
            return 0.0, 0.0, 0.0, False

        if objective_mode == "track_flex":
            primary_opt = pyo.value(m.t)
            m.primary_lock = pyo.Constraint(expr=m.t <= primary_opt + EPS)
        else:
            primary_opt = pyo.value(m.p_device)
            if objective_mode == "min_grid_consumption":
                m.primary_lock = pyo.Constraint(expr=m.p_device >= primary_opt - EPS)
            else:
                m.primary_lock = pyo.Constraint(expr=m.p_device <= primary_opt + EPS)

        m.obj.deactivate()

        # Stage 2: keep heat storage AND battery SOC near their target bands
        SOC_TARGET, SOC_TOL = 0.5, 0.1

        m.soc_dev = pyo.Var(m.storage_index, domain=pyo.NonNegativeReals)
        m.soc_dev_pos = pyo.Constraint(m.storage_index, rule=lambda m, idx: m.soc_dev[idx] >= m.storage[idx].soc - (SOC_TARGET + SOC_TOL))
        m.soc_dev_neg = pyo.Constraint(m.storage_index, rule=lambda m, idx: m.soc_dev[idx] >= (SOC_TARGET - SOC_TOL) - m.storage[idx].soc)

        m.battery_soc_dev = pyo.Var(m.battery_index, domain=pyo.NonNegativeReals)
        m.battery_soc_dev_pos = pyo.Constraint(m.battery_index, rule=lambda m, idx: m.battery_soc_dev[idx] >= m.battery[idx].soc - (SOC_TARGET + SOC_TOL))
        m.battery_soc_dev_neg = pyo.Constraint(m.battery_index, rule=lambda m, idx: m.battery_soc_dev[idx] >= (SOC_TARGET - SOC_TOL) - m.battery[idx].soc)

        m.obj2 = pyo.Objective(
            expr=sum(m.soc_dev[idx] for idx in m.storage_index) + sum(m.battery_soc_dev[idx] for idx in m.battery_index),
            sense=pyo.minimize,
        )

        res2, feasible2 = solve_model(m, "stage 2 SOC objective")
        if not feasible2:
            return 0.0, 0.0, 0.0, False
        soc_dev_opt = (sum(pyo.value(m.soc_dev[idx]) for idx in m.storage_index)
                       + sum(pyo.value(m.battery_soc_dev[idx]) for idx in m.battery_index))

        m.soc_dev_lock = pyo.Constraint(
            expr=sum(m.soc_dev[idx] for idx in m.storage_index) + sum(m.battery_soc_dev[idx] for idx in m.battery_index)
            <= soc_dev_opt + eps_soc
        )
        m.obj2.deactivate()

        # Stage 3: minimize CHP movement (battery deliberately excluded)
        m.chp_dev = pyo.Var(m.chp_index, domain=pyo.NonNegativeReals)
        m.chp_dev_pos = pyo.Constraint(m.chp_index, rule=lambda m, idx: m.chp_dev[idx] >= m.chp[idx].p_el - m.chp[idx].p_el_prev)
        m.chp_dev_neg = pyo.Constraint(m.chp_index, rule=lambda m, idx: m.chp_dev[idx] >= -(m.chp[idx].p_el - m.chp[idx].p_el_prev))
        m.obj3 = pyo.Objective(expr=sum(m.chp_dev[idx] for idx in m.chp_index), sense=pyo.minimize)

        res3, feasible3 = solve_model(m, "stage 3 CHP movement objective")
        if not feasible3:
            return 0.0, 0.0, 0.0, False

        p_bhp = pyo.value(next(m.bhp[idx].p_el for idx in m.bhp_index)) if len(m.bhp_index) else 0.0
        p_chp = pyo.value(next(m.chp[idx].p_el for idx in m.chp_index)) if len(m.chp_index) else 0.0
        p_battery = pyo.value(next(m.battery[idx].p_el for idx in m.battery_index)) if len(m.battery_index) else 0.0

        p_device = p_chp - p_bhp + p_battery

        self._last_optimization_result = {
            "objective_mode": objective_mode, "p_bhp_kw": p_bhp, "p_chp_kw": p_chp,
            "p_battery_kw": p_battery, "p_device_kw": p_device,
            "flex_demand_kw": flex_demand, "heat_demand_kw": heat_demand,
        }

        if update_internal_state:
            for idx in m.chp_index:
                p_el_now = pyo.value(m.chp[idx].p_el)
                p_el_prev = pyo.value(m.chp[idx].p_el_prev)
                if self._chp_downtime.get(idx, 0) > 0:
                    self._chp_downtime[idx] = max(0, self._chp_downtime[idx] - 1)
                elif p_el_now < EPS_CHP_OFF and p_el_prev >= EPS_CHP_OFF:
                    self._chp_downtime[idx] = 4

        return p_bhp, p_chp, p_battery, True

    def calculate_flexibility_bounds(self, prosumer, heat_demand, flex_demand=0.0):
        p_bhp_base, p_chp_base, p_batt_base, feasible_base = self.model_optimization(
            prosumer, heat_demand, flex_demand, objective_mode="track_flex", update_internal_state=False)
        p_bhp_support, p_chp_support, p_batt_support, feasible_support = self.model_optimization(
            prosumer, heat_demand, 0.0, objective_mode="min_grid_consumption", update_internal_state=False)
        p_bhp_absorb, p_chp_absorb, p_batt_absorb, feasible_absorb = self.model_optimization(
            prosumer, heat_demand, 0.0, objective_mode="max_grid_consumption", update_internal_state=False)

        feasible = feasible_base and feasible_support and feasible_absorb
        if not feasible:
            return {"feasible": False, "p_device_base_kw": np.nan,
                    "p_device_max_support_kw": np.nan, "p_device_max_absorption_kw": np.nan}

        return {
            "feasible": True,
            "p_device_base_kw": p_chp_base - p_bhp_base + p_batt_base,
            "p_device_max_support_kw": p_chp_support - p_bhp_support + p_batt_support,
            "p_device_max_absorption_kw": p_chp_absorb - p_bhp_absorb + p_batt_absorb,
        }

    def control_step(self, prosumer):
        if not hasattr(prosumer, "controller_results"):
            prosumer.controller_results = {}

        q_demand_kw = self._q_demand_kw
        p_flex_kw = self._p_flex_kw

        if getattr(self, "collect_flex_bounds", False):
            bounds = self.calculate_flexibility_bounds(prosumer, heat_demand=q_demand_kw, flex_demand=p_flex_kw)
            if not hasattr(self, "_flex_bounds_log"):
                self._flex_bounds_log = {}
            self._flex_bounds_log[self.time] = bounds

        p_el_bhp_in, p_el_chp_out, p_el_battery_out, feasible = self.model_optimization(
            prosumer, heat_demand=q_demand_kw, flex_demand=p_flex_kw,
            objective_mode="track_flex", update_internal_state=True)
        print(f"[{self.time}] flex={p_flex_kw:8.2f} kW | q_dem={q_demand_kw:8.2f} kW | "
              f"BHP={p_el_bhp_in:8.2f} kW | CHP={p_el_chp_out:8.2f} kW | Batt={p_el_battery_out:8.2f} kW | "
              f"feasible={feasible}")

        if feasible:
            result = np.array([[p_el_bhp_in, p_el_chp_out, p_el_battery_out]])
        else:
            result = np.array([[np.nan, np.nan, np.nan]])

        self.finalize(prosumer, result)
        self.applied = True


def create_controlled_optimization_with_battery(prosumer, index=None, in_service=True, name=None,
                                                level=0, order=0, period=0, **kwargs):
    optimization_index = create_optimization(prosumer, in_service, name, index, **kwargs)
    optimization_controller_data = OptimizationControllerData(
        element_name='optimization',
        element_index=[optimization_index],
        period_index=period,
        result_columns=["p_el_bhp_in", "p_el_chp_out", "p_el_battery_out"],
    )
    controller = OptimizationControllerWithBattery(
        prosumer, optimization_controller_data, order=order, level=level, name=name,
    )
    return controller.index

# ============================================================
# 4. Prosumer model builder
# ============================================================
def build_mall_prosumer(time_series_data_base, flex_target_kw, start,
                        end, time_resolution, frequency, collect_bounds=False, tz="utc"):

    prosumer = create_empty_prosumer_container(check_order=False)

    time_series_data_mall = time_series_data_base.copy()
    time_series_data_mall["flex_demand_kw"] = np.asarray(flex_target_kw)
    time_series_data_mall["t_sink_k"] = 350
    time_series_data_mall["cycle"] = 1
    time_series_data_mall.index = pd.date_range(start=start, end=end, freq=frequency, tz=tz)

    time_series_input = DFData(time_series_data_mall)
    period = create_period(prosumer, time_resolution, start, end, 'utc', 'default')

    input_params = ['mode', 't_source_k', 'q_demand_kw', 'cycle', 't_intake_k',
                    "flex_demand_kw", "p_el_bhp", "p_el_chp", "t_amb_k", "t_sink_k"]
    result_params = ['mode_cp', 't_source_cp_k', 'q_demand_cp_kw', 'cycle_cp', 't_intake_cp_k',
                     "flex_demand_cp_kw", "p_el_bhp_cp", "p_el_chp_cp", "t_amb_k_cp", "t_sink_k_cp"]

    cp_index = create_controlled_const_profile(
        prosumer, input_params, result_params, time_series_input, period, level=0)

    bhp_type = 'water-water2'
    bhp_name = 'example_bhp'
    max_thermal_power_kw = 800

    bhp_index = create_controlled_booster_heat_pump(prosumer,
                                                    hp_type=bhp_type,
                                                    name=bhp_name,
                                                    q_max_kw=max_thermal_power_kw,
                                                    level=2,
                                                    order=0)

    bhp_index_cop_calc = create_controlled_booster_heat_pump(prosumer,
                                                             hp_type=bhp_type,
                                                             name=bhp_name,
                                                             q_max_kw=max_thermal_power_kw,
                                                             level=1,
                                                             order=0)

    name = 'example_chp'
    size_kw = 350
    fuel = 'ng'
    altitude_m = 0

    ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=2, order=1)

    q_capacity_kwh = 50000
    heat_storage_index = create_controlled_heat_storage(prosumer, q_capacity_kwh, init_soc=0.0, level=2, order=2)

    heat_demand_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=2, order=3)

    # Battery storage (level=2 so it is seen by the optimizer)
    battery_index = create_controlled_battery_storage(
        prosumer,
        e_capacity_kwh=300,        # kWh
        p_charge_max_kw=150,       # kW
        p_discharge_max_kw=150,    # kW
        eta_charge=0.95,
        eta_discharge=0.95,
        soc_min=0.1,
        soc_max=0.9,
        self_discharge_per_hour=0.001,
        init_soc=0.5,
        name="mall_battery",
        level=2,
        order=4,
    )

    optimization_index = create_controlled_optimization_with_battery(prosumer, level=1, order=1)

    # Mappings
    GenericMapping(prosumer,
                   initiator_id=cp_index,
                   initiator_column=["t_source_cp_k", "mode_cp", "p_el_bhp_cp", "t_amb_k_cp", "t_sink_k_cp"],
                   responder_id=bhp_index,
                   responder_column=["t_source_k", "mode", "p_received_kw", "t_amb_k", "t_sink_k"])

    GenericMapping(prosumer,
                   initiator_id=cp_index,
                   initiator_column=["cycle_cp", "t_intake_cp_k", "p_el_chp_cp"],
                   responder_id=ice_chp_index,
                   responder_column=["cycle", "t_intake_k", "p_requested_kw"])

    GenericMapping(prosumer,
                   initiator_id=cp_index,
                   initiator_column="q_demand_cp_kw",
                   responder_id=heat_demand_index,
                   responder_column="q_demand_kw")

    GenericMapping(prosumer,
                   initiator_id=bhp_index,
                   initiator_column="q_floor",
                   responder_id=heat_storage_index,
                   responder_column="q_received_kw")

    GenericMapping(prosumer,
                   initiator_id=ice_chp_index,
                   initiator_column="p_th_out_kw",
                   responder_id=heat_storage_index,
                   responder_column="q_received_kw")

    GenericMapping(prosumer,
                   initiator_id=heat_storage_index,
                   initiator_column="q_delivered_kw",
                   responder_id=heat_demand_index,
                   responder_column="q_received_kw")

    GenericMapping(prosumer,
                   initiator_id=cp_index,
                   initiator_column=["t_source_cp_k", "mode_cp", "p_el_bhp_cp", "t_amb_k_cp", "t_sink_k_cp"],
                   responder_id=bhp_index_cop_calc,
                   responder_column=["t_source_k", "mode", "p_received_kw", "t_amb_k", "t_sink_k"])

    GenericMapping(prosumer,
                   initiator_id=cp_index,
                   initiator_column=["q_demand_cp_kw", "flex_demand_cp_kw"],
                   responder_id=optimization_index,
                   responder_column=["q_demand_kw", "p_flex_kw"])

    GenericMapping(prosumer,
                   initiator_id=bhp_index_cop_calc,
                   initiator_column=["cop_floor"],
                   responder_id=optimization_index,
                   responder_column=["cop_bhp"])

    GenericMapping(prosumer,
                   initiator_id=optimization_index,
                   initiator_column=["p_el_bhp_in"],
                   responder_id=bhp_index,
                   responder_column=["p_received_kw"])

    GenericMapping(prosumer,
                   initiator_id=optimization_index,
                   initiator_column=["p_el_chp_out"],
                   responder_id=ice_chp_index,
                   responder_column=["p_requested_kw"])

    # NEW: mapping from optimizer to battery
    GenericMapping(prosumer,
                   initiator_id=optimization_index,
                   initiator_column=["p_el_battery_out"],
                   responder_id=battery_index,
                   responder_column=["p_requested_kw"])

    optimization_controller = prosumer.controller.loc[optimization_index, "object"]
    optimization_controller.collect_flex_bounds = collect_bounds
    optimization_controller._flex_bounds_log = {}

    return prosumer, period, optimization_controller

# ============================================================
# 5. Run simulation and extract results
# ============================================================
def run_mall_case_with_bounds(time_series_data_base, flex_target_kw, residual_mall_load_kw,
                              start, end, time_resolution, frequency, collect_bounds=False,
                              allow_export=False, verbose=False):

    prosumer, period, optimization_controller = build_mall_prosumer(
        time_series_data_base=time_series_data_base,
        flex_target_kw=flex_target_kw,
        start=start, end=end,
        time_resolution=time_resolution,
        frequency=frequency,
        collect_bounds=collect_bounds
    )

    run_timeseries(prosumer, period, verbose=verbose)

    # Extract all data source DataFrames
    data_frames = []
    for i in range(len(prosumer.time_series.data_source)):
        data_frames.append(prosumer.time_series.data_source.iloc[i].df)

    def find_df_by_columns(required_cols):
        for df in data_frames:
            if all(col in df.columns for col in required_cols):
                return df
        raise RuntimeError(f"No DataFrame found with columns {required_cols}")

    # Use optimizer output for electrical powers
    res_opt = find_df_by_columns(['p_el_bhp_in', 'p_el_chp_out', 'p_el_battery_out'])
    res_chp = find_df_by_columns(['p_el_out_kw', 'p_th_out_kw'])
    res_storage = find_df_by_columns(['soc', 'q_delivered_kw'])
    res_heat_demand = find_df_by_columns(['q_received_kw'])
    res_battery = find_df_by_columns(['p_storage_kw', 'soc'])

    residual_mall_series = pd.Series(np.asarray(residual_mall_load_kw),
                                     index=res_chp.index, name="residual_mall_load_kw")

    bhp_p_el_kw = res_opt["p_el_bhp_in"]
    chp_p_el_kw = res_opt["p_el_chp_out"]
    battery_p_kw = res_opt["p_el_battery_out"]

    p_device_kw = chp_p_el_kw - bhp_p_el_kw + battery_p_kw
    p_grid_kw = residual_mall_series - p_device_kw

    res_df = pd.DataFrame({
        "residual_mall_load_kw": residual_mall_series,
        "chp_p_el_kw": chp_p_el_kw,
        "bhp_p_el_kw": bhp_p_el_kw,
        "battery_p_kw": battery_p_kw,
        "battery_soc_percent": res_battery["soc"] * 100,
        "p_device_kw": p_device_kw,
        "p_grid_kw": p_grid_kw,
        "chp_q_th_kw": res_chp["p_th_out_kw"],
        "bhp_q_th_kw": np.zeros_like(res_chp.index),  # placeholder
        "q_delivered_storage_kw": res_storage["q_delivered_kw"],
        "q_received_demand_kw": res_heat_demand["q_received_kw"],
        "soc_percent": res_storage["soc"] * 100,
        "flex_target_kw": flex_target_kw
    }, index=res_chp.index)

    if not collect_bounds:
        return res_df, None

    bounds_log = getattr(optimization_controller, "_flex_bounds_log", {})
    if not bounds_log:
        raise RuntimeError("No flexibility bounds")

    bounds_df = pd.DataFrame.from_dict(bounds_log, orient="index")
    bounds_df.index = pd.to_datetime(bounds_df.index)
    bounds_df = bounds_df.reindex(res_df.index)

    residual_kw = res_df["residual_mall_load_kw"]
    bounds_df["p_mall_base_kw"] = res_df["p_grid_kw"]
    bounds_df["p_mall_min_kw"] = (residual_kw - bounds_df["p_device_max_support_kw"])
    bounds_df["p_mall_max_kw"] = (residual_kw - bounds_df["p_device_max_absorption_kw"])

    if not allow_export:
        bounds_df["p_mall_base_kw"] = bounds_df["p_mall_base_kw"].clip(lower=0.0)
        bounds_df["p_mall_min_kw"] = bounds_df["p_mall_min_kw"].clip(lower=0.0)
        bounds_df["p_mall_max_kw"] = bounds_df["p_mall_max_kw"].clip(lower=0.0)

    raw_cols = ["p_mall_min_kw", "p_mall_base_kw", "p_mall_max_kw"]
    bounds_df["p_mall_min_mw"] = bounds_df[raw_cols].min(axis=1) / 1000.0
    bounds_df["p_mall_base_mw"] = bounds_df["p_mall_base_kw"] / 1000.0
    bounds_df["p_mall_max_mw"] = bounds_df[raw_cols].max(axis=1) / 1000.0
    bounds_df["flex_down_mw"] = (bounds_df["p_mall_base_mw"] - bounds_df["p_mall_min_mw"])
    bounds_df["flex_up_mw"] = (bounds_df["p_mall_max_mw"] - bounds_df["p_mall_base_mw"])

    return res_df, bounds_df

# ============================================================
# 6. OPF and grid functions (unchanged except as needed)
# ============================================================
v_min_pu_std = 0.90
v_max_pu_std = 1.10
loading_percent_max_std = 100.0
allow_export_to_grid = True

def get_schutterwald_subnets():
    return lv_schutterwald(separation_by_sub=True, include_heat_pumps=False)

def get_single_schutterwald_subnet(subnet_id):
    subnets = get_schutterwald_subnets()
    if subnet_id >= len(subnets):
        raise RuntimeError(f"Subnet id {subnet_id} does not exist. Available: {len(subnets)}")
    return subnets[subnet_id]

def run_pf(net, context="", print_error=True):
    try:
        pp.runpp(net, algorithm="nr", max_iteration=50, tolerance_mva=1e-8, init="auto", numba=False)
        return True
    except Exception as exc:
        if print_error:
            print(f"\nPower flow failed: {context}\nReason: {exc}")
        return False

def check_grid_violations(net):
    violations = {"undervoltage": [], "overvoltage": [],
                  "line_overload": [], "trafo_overload": []}
    for bus in net.res_bus.index:
        vm_pu = net.res_bus.at[bus, "vm_pu"]
        if vm_pu < v_min_pu_std:
            violations["undervoltage"].append((bus, vm_pu))
        if vm_pu > v_max_pu_std:
            violations["overvoltage"].append((bus, vm_pu))
    if len(net.line):
        for line in net.res_line.index:
            loading = net.res_line.at[line, "loading_percent"]
            if loading > loading_percent_max_std:
                violations["line_overload"].append((line, loading))
    if len(net.trafo):
        for trafo in net.res_trafo.index:
            loading = net.res_trafo.at[trafo, "loading_percent"]
            if loading > loading_percent_max_std:
                violations["trafo_overload"].append((trafo, loading))
    has_violation = any(len(v) > 0 for v in violations.values())
    return has_violation, violations

def prepare_grid_for_opf(net):
    if len(net.load):
        net.load["controllable"] = False
    if len(net.sgen):
        net.sgen["controllable"] = False
    net.bus["min_vm_pu"] = v_min_pu_std
    net.bus["max_vm_pu"] = v_max_pu_std
    if len(net.line):
        net.line["max_loading_percent"] = loading_percent_max_std
    if len(net.trafo):
        net.trafo["max_loading_percent"] = loading_percent_max_std
    net.ext_grid["min_p_mw"] = -10.0
    net.ext_grid["max_p_mw"] = 10.0
    net.ext_grid["min_q_mvar"] = -10.0
    net.ext_grid["max_q_mvar"] = 10.0

def create_mall_load(net, mall_bus, p_mw, p_min_mw, p_max_mw, q_mvar, q_eps):
    return pp.create_load(net, bus=mall_bus, p_mw=p_mw, q_mvar=q_mvar,
                          name="Shopping Mall load", controllable=True,
                          min_p_mw=p_min_mw, max_p_mw=p_max_mw,
                          min_q_mvar=q_mvar - q_eps, max_q_mvar=q_mvar + q_eps)

def run_mall_opf(net, mall_load, p_base_mw, print_error=True):
    if "poly_cost" in net and len(net.poly_cost):
        net.poly_cost.drop(net.poly_cost.index, inplace=True)
    weight = 1000.0
    pp.create_poly_cost(net, element=mall_load, et="load",
                        cp2_eur_per_mw2=weight,
                        cp1_eur_per_mw=-2.0 * weight * p_base_mw,
                        cp0_eur=weight * p_base_mw**2)
    for eg in net.ext_grid.index:
        pp.create_poly_cost(net, element=eg, et="ext_grid", cp1_eur_per_mw=0.0, cp2_eur_per_mw2=0.0)
    try:
        pp.runopp(net, calculate_voltage_angles=False, init="pf", numba=False,
                  verbose=False, suppress_warnings=True,
                  OPF_VIOLATION=1e-4, PDIPM_FEASTOL=1e-4,
                  PDIPM_GRADTOL=1e-4, PDIPM_COMPTOL=1e-4,
                  PDIPM_COSTTOL=1e-4, PDIPM_MAX_IT=500)
    except Exception as exc:
        if print_error:
            print(f"\nOPF failed.\nReason: {exc}")
        return None
    if not getattr(net, "OPF_converged", False):
        if print_error:
            print("\nOPF did not converge.")
        return None
    return net.res_load.at[mall_load, "p_mw"]

def build_opf_result_row(selected_time, subnet_id, mall_bus, status,
                         flex_activation_required, p_mall_min_mw, p_mall_base_mw,
                         p_mall_max_mw, p_reference_mw, p_mall_opf_mw,
                         q_mall_opf_mvar, p_grid_setpoint_kw, p_device_setpoint_kw,
                         v_before=None, v_after=None, violations_before=None,
                         violations_after=None):
    if violations_before is None:
        violations_before = {"undervoltage": [], "overvoltage": [], "line_overload": [], "trafo_overload": []}
    if violations_after is None:
        violations_after = {"undervoltage": [], "overvoltage": [], "line_overload": [], "trafo_overload": []}
    v_min_before = v_before.min() if v_before is not None else np.nan
    v_max_before = v_before.max() if v_before is not None else np.nan
    v_min_after = v_after.min() if v_after is not None else np.nan
    v_max_after = v_after.max() if v_after is not None else np.nan
    grid_support_kw = 0.0 if pd.isna(p_mall_opf_mw) else (p_mall_base_mw - p_mall_opf_mw) * 1000.0
    return {
        "time": selected_time,
        "subnet_id": subnet_id,
        "mall_bus": mall_bus,
        "status": status,
        "flex_activation_required": flex_activation_required,
        "p_min_mw": p_mall_min_mw,
        "p_base_mw": p_mall_base_mw,
        "p_max_mw": p_mall_max_mw,
        "p_reference_mw": p_reference_mw,
        "p_opf_mw": p_mall_opf_mw,
        "q_opf_mvar": q_mall_opf_mvar,
        "p_grid_setpoint_kw": p_grid_setpoint_kw,
        "p_device_setpoint_kw": p_device_setpoint_kw,
        "grid_support_kw": grid_support_kw,
        "v_min_before_pu": v_min_before,
        "v_min_after_pu": v_min_after,
        "v_max_before_pu": v_max_before,
        "v_max_after_pu": v_max_after,
        "n_undervoltage_before": len(violations_before["undervoltage"]),
        "n_undervoltage_after": len(violations_after["undervoltage"]),
        "n_overvoltage_before": len(violations_before["overvoltage"]),
        "n_overvoltage_after": len(violations_after["overvoltage"]),
        "n_line_overload_before": len(violations_before["line_overload"]),
        "n_line_overload_after": len(violations_after["line_overload"]),
        "n_trafo_overload_before": len(violations_before["trafo_overload"]),
        "n_trafo_overload_after": len(violations_after["trafo_overload"])
    }

def run_opf_timeseries_for_subnet(fixed_subnet_id, fixed_mall_bus, valid_times, bounds_df,
                                  residual_mall_load_kw, baseline_flex_target_kw,
                                  q_mall_base_mvar, q_eps):
    updated_flex_target_kw = baseline_flex_target_kw.copy()
    opf_rows = []

    for selected_time in valid_times.index:
        selected_position = bounds_df.index.get_loc(selected_time)
        p_mall_min_mw = bounds_df.at[selected_time, "p_mall_min_mw"]
        p_mall_base_mw = bounds_df.at[selected_time, "p_mall_base_mw"]
        p_mall_max_mw = bounds_df.at[selected_time, "p_mall_max_mw"]

        net = get_single_schutterwald_subnet(fixed_subnet_id)
        prepare_grid_for_opf(net)
        if fixed_mall_bus not in net.bus.index:
            raise RuntimeError(f"Selected mall bus {fixed_mall_bus} is not in subnet {fixed_subnet_id}.")

        p_grid_setpoint_kw = p_mall_base_mw * 1000.0
        p_device_setpoint_kw = baseline_flex_target_kw[selected_position]

        mall_load = create_mall_load(net, fixed_mall_bus, p_mall_base_mw,
                                     p_mall_min_mw, p_mall_max_mw,
                                     q_mall_base_mvar, q_eps)

        # 1. Baseline PF
        if not run_pf(net, f"subnet {fixed_subnet_id} with mall at {selected_time}", print_error=False):
            opf_rows.append(build_opf_result_row(
                selected_time, fixed_subnet_id, fixed_mall_bus, "pf_with_mall_failed",
                False, p_mall_min_mw, p_mall_base_mw, p_mall_max_mw, p_mall_base_mw,
                np.nan, np.nan, p_grid_setpoint_kw, p_device_setpoint_kw))
            continue
        v_before = net.res_bus.vm_pu.copy()
        has_violation_before, violations_before = check_grid_violations(net)

        if not has_violation_before:
            opf_rows.append(build_opf_result_row(
                selected_time, fixed_subnet_id, fixed_mall_bus, "no_violation_no_flex_needed",
                False, p_mall_min_mw, p_mall_base_mw, p_mall_max_mw, p_mall_base_mw,
                p_mall_base_mw, q_mall_base_mvar, p_grid_setpoint_kw, p_device_setpoint_kw,
                v_before, v_before, violations_before, violations_before))
            updated_flex_target_kw[selected_position] = p_device_setpoint_kw
            continue

        # 2. OPF
        p_mall_opf_mw = run_mall_opf(net, mall_load, p_mall_base_mw, print_error=False)
        if p_mall_opf_mw is None:
            opf_rows.append(build_opf_result_row(
                selected_time, fixed_subnet_id, fixed_mall_bus, "opf_failed",
                True, p_mall_min_mw, p_mall_base_mw, p_mall_max_mw, p_mall_base_mw,
                np.nan, np.nan, p_grid_setpoint_kw, p_device_setpoint_kw,
                v_before, None, violations_before, None))
            continue

        q_mall_opf_mvar = net.res_load.at[mall_load, "q_mvar"]
        net.load.at[mall_load, "p_mw"] = p_mall_opf_mw
        net.load.at[mall_load, "q_mvar"] = q_mall_opf_mvar

        if not run_pf(net, f"subnet {fixed_subnet_id} after OPF at {selected_time}", print_error=False):
            opf_rows.append(build_opf_result_row(
                selected_time, fixed_subnet_id, fixed_mall_bus, "pf_after_opf_failed",
                True, p_mall_min_mw, p_mall_base_mw, p_mall_max_mw, p_mall_base_mw,
                p_mall_opf_mw, q_mall_opf_mvar, p_grid_setpoint_kw, p_device_setpoint_kw,
                v_before, None, violations_before, None))
            continue

        v_after = net.res_bus.vm_pu.copy()
        has_violation_after, violations_after = check_grid_violations(net)
        status = "opf_success_violations_resolved" if not has_violation_after else "opf_success_remaining_violations"

        p_grid_setpoint_kw = p_mall_opf_mw * 1000.0
        residual_load_selected_kw = residual_mall_load_kw[selected_position]
        p_device_setpoint_kw = residual_load_selected_kw - p_grid_setpoint_kw
        updated_flex_target_kw[selected_position] = p_device_setpoint_kw

        opf_rows.append(build_opf_result_row(
            selected_time, fixed_subnet_id, fixed_mall_bus, status,
            True, p_mall_min_mw, p_mall_base_mw, p_mall_max_mw, p_mall_base_mw,
            p_mall_opf_mw, q_mall_opf_mvar, p_grid_setpoint_kw, p_device_setpoint_kw,
            v_before, v_after, violations_before, violations_after))

    opf_results_df = pd.DataFrame(opf_rows)
    if not opf_results_df.empty:
        opf_results_df = opf_results_df.set_index("time")
    return opf_results_df, updated_flex_target_kw

# ============================================================
# 7. Main workflow
# ============================================================
def main():
    # Baseline run and bounds
    res_base, bounds_df = run_mall_case_with_bounds(
        time_series_data_base=time_series_data,
        flex_target_kw=baseline_flex_target_kw,
        residual_mall_load_kw=residual_mall_load_kw,
        start=start, end=end,
        time_resolution=time_resolution,
        frequency=frequency,
        collect_bounds=True,
        allow_export=allow_export_to_grid,
        verbose=False
    )

    valid_times = bounds_df[bounds_df["feasible"] == True].dropna(
        subset=["p_mall_min_mw", "p_mall_base_mw", "p_mall_max_mw"])
    if valid_times.empty:
        raise RuntimeError("No feasible timestep found")

    print("\nComplete OPF time series")
    print(f"Number of OPF timesteps: {len(valid_times)}")
    print(f"P_base min: {valid_times['p_mall_min_mw'].min():.3f} MW, ",
          f"P_base max: {valid_times['p_mall_max_mw'].max():.3f} MW")

    q_mall_base_mvar = 0.0
    q_eps = 1e-6

    # Fixed Schutterwald subnet and mall bus
    fixed_subnet_id = 1
    fixed_subnet_name = "LV Schutterwald 1"
    fixed_mall_bus = 623

    print(f"\nUsing selected Schutterwald OPF case")
    print(f"Subnet id: {fixed_subnet_id}")
    print(f"Subnet name: {fixed_subnet_name}")
    print(f"Mall bus: {fixed_mall_bus}")

    check_net = get_single_schutterwald_subnet(fixed_subnet_id)
    print(f"Number of buses in selected subnet: {len(check_net.bus)}")
    if fixed_mall_bus not in check_net.bus.index:
        raise RuntimeError(f"Selected mall bus {fixed_mall_bus} is not in subnet {fixed_subnet_id}.")
    if not run_pf(check_net, f"subnet {fixed_subnet_id} base PF"):
        raise RuntimeError(f"Base PF does not converge for subnet {fixed_subnet_id}.")

    # Run OPF time series
    opf_results_df, updated_flex_target_kw = run_opf_timeseries_for_subnet(
        fixed_subnet_id=fixed_subnet_id, fixed_mall_bus=fixed_mall_bus,
        valid_times=valid_times, bounds_df=bounds_df,
        residual_mall_load_kw=residual_mall_load_kw,
        baseline_flex_target_kw=baseline_flex_target_kw,
        q_mall_base_mvar=q_mall_base_mvar, q_eps=q_eps
    )

    if opf_results_df.empty:
        raise RuntimeError("No OPF timestep was calculated.")

    # Summary statistics
    n_violation_timesteps = ((opf_results_df["n_undervoltage_before"] > 0) |
                             (opf_results_df["n_overvoltage_before"] > 0) |
                             (opf_results_df["n_line_overload_before"] > 0) |
                             (opf_results_df["n_trafo_overload_before"] > 0)).sum()
    n_opf_success = opf_results_df["status"].isin(
        ["opf_success_violations_resolved", "opf_success_remaining_violations"]).sum()
    n_opf_resolved = (opf_results_df["status"] == "opf_success_violations_resolved").sum()
    n_voltage_improved = (opf_results_df["status"].isin(
        ["opf_success_violations_resolved", "opf_success_remaining_violations"]) &
        (opf_results_df["v_min_after_pu"] > opf_results_df["v_min_before_pu"])).sum()

    print("\nSelected Schutterwald OPF case summary")
    print(f"Subnet id: {fixed_subnet_id}")
    print(f"Subnet name: {fixed_subnet_name}")
    print(f"Mall bus: {fixed_mall_bus}")
    print(f"Calculated timesteps: {len(opf_results_df)}")
    print(f"Violation timesteps: {n_violation_timesteps}")
    print(f"OPF success timesteps: {n_opf_success}")
    print(f"OPF resolved timesteps: {n_opf_resolved}")
    print(f"Voltage-improved timesteps: {n_voltage_improved}")

    # Save OPF setpoint time series
    opf_results_df.to_csv("mall_opf_setpoint_timeseries.csv")

    print("\nStatus summary")
    print(opf_results_df["status"].value_counts(dropna=False))
    print(f"PF with mall failed: {(opf_results_df['status'] == 'pf_with_mall_failed').sum()}")
    print(f"OPF failed: {(opf_results_df['status'] == 'opf_failed').sum()}")
    print(f"PF after OPF failed: {(opf_results_df['status'] == 'pf_after_opf_failed').sum()}")
    print(f"Resolved: {(opf_results_df['status'] == 'opf_success_violations_resolved').sum()}")
    print(f"Remaining violations: {(opf_results_df['status'] == 'opf_success_remaining_violations').sum()}")
    print(f"No-flex-needed: {(opf_results_df['status'] == 'no_violation_no_flex_needed').sum()}")

    # Run updated pandaprosumer with OPF setpoints
    res_updated, _ = run_mall_case_with_bounds(
        time_series_data_base=time_series_data,
        flex_target_kw=updated_flex_target_kw,
        residual_mall_load_kw=residual_mall_load_kw,
        start=start, end=end,
        time_resolution=time_resolution,
        frequency=frequency,
        collect_bounds=False,
        allow_export=allow_export_to_grid,
        verbose=False
    )

    # Compare
    opf_results_df["p_updated_grid_kw"] = res_updated["p_grid_kw"].reindex(opf_results_df.index)
    opf_results_df["tracking_error_kw"] = opf_results_df["p_updated_grid_kw"] - opf_results_df["p_grid_setpoint_kw"]
    opf_results_df.to_csv("mall_opf_setpoint_timeseries_with_tracking.csv")

    # Build final mall flexibility time series
    mall_idx = res_base.index
    flex_ts_df = pd.DataFrame(index=mall_idx)
    flex_ts_df["residual_mall_load_kw"] = res_updated["residual_mall_load_kw"].reindex(mall_idx)
    flex_ts_df["p_grid_baseline_kw"] = res_base["p_grid_kw"].reindex(mall_idx)
    flex_ts_df["p_grid_updated_kw"] = res_updated["p_grid_kw"].reindex(mall_idx)
    flex_ts_df["flexibility_provided_to_grid_kw"] = (
        flex_ts_df["p_grid_baseline_kw"] - flex_ts_df["p_grid_updated_kw"])
    flex_ts_df["p_device_kw"] = res_updated["p_device_kw"].reindex(mall_idx)
    flex_ts_df["chp_p_el_kw"] = res_updated["chp_p_el_kw"].reindex(mall_idx)
    flex_ts_df["bhp_p_el_kw"] = res_updated["bhp_p_el_kw"].reindex(mall_idx)
    flex_ts_df["battery_p_kw"] = res_updated["battery_p_kw"].reindex(mall_idx)
    flex_ts_df["battery_soc_percent"] = res_updated["battery_soc_percent"].reindex(mall_idx)
    flex_ts_df["soc_percent"] = res_updated["soc_percent"].reindex(mall_idx)
    flex_ts_df["q_delivered_storage_kw"] = res_updated["q_delivered_storage_kw"].reindex(mall_idx)
    flex_ts_df["q_received_demand_kw"] = res_updated["q_received_demand_kw"].reindex(mall_idx)
    flex_ts_df["p_flex_request_kw"] = pd.Series(updated_flex_target_kw, index=mall_idx)
    flex_ts_df["opf_timestep"] = flex_ts_df.index.isin(opf_results_df.index)
    flex_ts_df.to_csv("mall_storage_aware_flexibility_timeseries.csv")

    print("\nMall flexibility timeseries dataframe")
    print(f"pandaprosumer run timesteps: {len(flex_ts_df)}")
    print(f"OPF timesteps: {flex_ts_df['opf_timestep'].sum()}")
    print(f"Max tracking error = {opf_results_df['tracking_error_kw'].abs().max():.6f} kW")
    print(f"Mean tracking error = {opf_results_df['tracking_error_kw'].abs().mean():.6f} kW")

    # ============================
    # Plots
    # ============================
    plt.figure(figsize=(12, 6))
    plt.plot(flex_ts_df.index, flex_ts_df["p_grid_updated_kw"], label="Updated mall grid power", linewidth=1.5)
    plt.plot(flex_ts_df.index, flex_ts_df["p_grid_baseline_kw"], label="Baseline mall grid power", linestyle=":", linewidth=2.5)
    plt.plot(flex_ts_df.index, flex_ts_df["flexibility_provided_to_grid_kw"], label="Flexibility provided to grid", linewidth=1.5)
    plt.ylabel("Power [kW]")
    plt.xlabel("Time")
    plt.title("Storage-aware Mall Flexibility Provision")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(12, 6))
    plt.plot(flex_ts_df.index, flex_ts_df["p_flex_request_kw"], label="OPF-calculated flex request")
    plt.plot(flex_ts_df.index, flex_ts_df["p_device_kw"], linestyle="--", label="P_device = CHP - BHP + Battery")
    plt.ylabel("Power [kW]")
    plt.xlabel("Time")
    plt.title("Requested vs pandaprosumer device-side flexibility potential")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(12, 6))
    plt.plot(opf_results_df.index, opf_results_df["p_grid_setpoint_kw"], label="OPF grid setpoint")
    plt.plot(opf_results_df.index, opf_results_df["p_updated_grid_kw"], linestyle="--", label="Updated pandaprosumer grid power")
    plt.ylabel("Mall net grid power [kW]")
    plt.xlabel("Time")
    plt.title("OPF Setpoint Tracking by pandaprosumer")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(12, 6))
    plt.plot(opf_results_df.index, opf_results_df["v_min_before_pu"], label="V_min before OPF")
    plt.plot(opf_results_df.index, opf_results_df["v_min_after_pu"], label="V_min after OPF")
    plt.axhline(v_min_pu_std, linestyle="--", label=f"V_min threshold {v_min_pu_std:.2f} pu")
    plt.ylabel("Minimum voltage [pu]")
    plt.xlabel("Time")
    plt.title("Minimum Grid Voltage Comparison")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(12, 6))
    plt.plot(flex_ts_df.index, flex_ts_df["p_device_kw"], label="P_device = CHP - BHP + Battery")
    plt.plot(flex_ts_df.index, flex_ts_df["chp_p_el_kw"], linestyle="--", label="CHP electrical output")
    plt.plot(flex_ts_df.index, flex_ts_df["bhp_p_el_kw"], linestyle=":", label="BHP electrical consumption")
    plt.plot(flex_ts_df.index, flex_ts_df["battery_p_kw"], linestyle="-.", label="Battery power (discharge +)")
    plt.ylabel("Power [kW]")
    plt.xlabel("Time")
    plt.title("Mall Flexibility Provision")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(12, 6))
    plt.plot(flex_ts_df.index, flex_ts_df["soc_percent"], label="Thermal storage SOC")
    plt.plot(flex_ts_df.index, flex_ts_df["battery_soc_percent"], label="Battery SOC")
    plt.ylabel("SOC [%]")
    plt.xlabel("Time")
    plt.title("Storage SOC during Flexibility Provision")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()