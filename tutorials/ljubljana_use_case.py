import pandas as pd
from numba.cuda import profile_start
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_heat_demand, \
    create_controlled_booster_heat_pump, create_controlled_ice_chp, create_controlled_chiller,
                                             create_controlled_heat_storage, create_controlled_supervisor)
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries
import numpy as np
import json
import os

import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

# flex =  np.linspace(-200, 200, 96)

n = 96

# Erzeuge Sinus über eine Periode (0 bis 2π)
t = np.linspace(0, 4*2*np.pi, n)

# Skaliere Sinus auf [-200, 200]
flex = 200 * np.sin(t)

prosumer = create_empty_prosumer_container()

bhp_type = 'water-water1'
bhp_name = 'example_bhp'

name = 'example_chp'
size_kw = 700
fuel = 'ng'
altitude_m = 0

q_capacity_kwh = 10000

start = '2020-01-01 00:00:00'
end = '2020-01-01 23:59:59'
time_resolution = 900        # 15 min
frequency = '15min'


time_series_data = pd.read_excel('data/heat_demand_input_chp_bhp.xlsx')
time_series_data["c_electricity_eur_per_mw"] = np.random.randint(100, 251, size=len(time_series_data))
time_series_data["c_gas_eur_per_mw"] = 70
time_series_data["flex_demand_kw"] = flex
time_series_data["p_el_bhp"] = 0
time_series_data["p_el_chp"] = 0
time_series_data["mode"] = 2
time_series_data["cycle"] = 1


dur = pd.date_range(start=start, end=end, freq=frequency, tz='utc')
time_series_data.index = dur
time_series_input_bhp = DFData(time_series_data)
period = create_period(prosumer, time_resolution, start, end, 'utc', 'default')

print(time_series_data.head())
input_params = ['mode', 't_source_k', 'q_demand_kw', 'cycle', 't_intake_k',
                    "c_electricity_eur_per_mw", "c_gas_eur_per_mw", "flex_demand_kw", "p_el_bhp", "p_el_chp"]
result_params = ['mode_cp', 't_source_cp_k', 'q_demand_cp_kw', 'cycle_cp', 't_intake_cp_k',
                     "c_electricity_cp_eur_per_mw", "c_gas_cp_eur_per_mw", "flex_demand_cp_kw", "p_el_bhp_cp", "p_el_chp_cp"]

cp_index = create_controlled_const_profile(
        prosumer, input_params, result_params, time_series_input_bhp, period, level=0)

bhp_index = create_controlled_booster_heat_pump(prosumer, bhp_type, bhp_name, level=2, order=0)

ice_chp_index = create_controlled_ice_chp(prosumer, size_kw, fuel, altitude_m, name, level=2, order=1)

heat_storage_index = create_controlled_heat_storage(prosumer, q_capacity_kwh,level = 2,order=2)

heat_demand_index = create_controlled_heat_demand(prosumer, scaling=1.0, level=2, order=3)

GenericMapping(prosumer,
        initiator_id=cp_index,
        initiator_column=["t_source_cp_k", "mode_cp","p_el_bhp_cp"],
        responder_id=bhp_index,
        responder_column=["t_source_k", "mode", "p_received_kw"],
    )

GenericMapping(
        prosumer,
        initiator_id=cp_index,
        initiator_column=["cycle_cp", "t_intake_cp_k", "p_el_chp_cp"],
        responder_id=ice_chp_index,
        responder_column=["cycle", "t_intake_k", "p_requested_kw"],
    )


GenericMapping(prosumer,
        initiator_id=cp_index,
        initiator_column="q_demand_cp_kw",
        responder_id=heat_demand_index,
        responder_column="q_demand_kw",
    )

GenericMapping(prosumer,
                initiator_id=bhp_index,
                initiator_column="q_floor",
                responder_id=heat_storage_index,
                responder_column="q_received_kw",
                order=0,
)

GenericMapping(
    prosumer,
    initiator_id=ice_chp_index,
    initiator_column="p_th_out_kw",
    responder_id=heat_storage_index,
    responder_column="q_received_kw",
    order=1,
)


GenericMapping(
    prosumer,
    initiator_id=heat_storage_index,
    initiator_column="q_delivered_kw",
    responder_id=heat_demand_index,
    responder_column="q_received_kw",
)

def check_results(prosumer, ts):
    """
    Check the consistency of prosumer simulation results and, if necessary,
    rerun a local CHP and BHP optimization to adjust setpoints.

    This function inspects the most recent timestep of the prosumer's
    controller results. If the node electrical balance is not satisfied,
    it triggers a small Pyomo optimization model (`model_optimization_chp_fit`)
    using a CHP performance map. If the optimization is feasible, the
    corrected electrical outputs for BHP and CHP are written back into
    the prosumer's dataframe.

    Parameters
    ----------
    prosumer :
        Prosumer object with attributes:
        - controller_results : dict
            Dictionary of timestep results.

    Returns
    -------
    rerun : bool
        True if a feasible optimization was found and results were updated,
        False otherwise.
    """
    rerun = False

    #previous timestep
    ts_prev = ts - pd.Timedelta(seconds=900)

    #Results for the timestep
    results_timestep = prosumer.controller_results

    #DFData - DataSourceClass for the inut data
    df_data = prosumer.controller.object[0].df_data

    #input data for the const. profile for the timestep
    input = prosumer.controller.object[0].df_data.get_time_step_value(
        time_step=ts,
        profile_name=prosumer.controller.object[0].input_columns
    ).reshape(1, -1)

    #result data for el. power for the timestep (bhp - input, chp - output)
    p_el_out_chp = results_timestep[ts][2]["p_el_out_kw"]
    p_el_floor_bhp = results_timestep[ts][1]["pel_floor_kw"]

    #node balance for the timestep
    node_balance = p_el_out_chp - p_el_floor_bhp + input[0, 7]

    #select the chp_map for the optimization
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "src", "pandaprosumer", "library", "chp_maps", "ice_chp_maps.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    chp_map_2 = next(m for m in data["chp_ice_map"] if m["__chp_nominal_size_kw__"] == 700)

    cop_bhp = results_timestep[ts][1]["cop_floor"]
    if ts_prev in results_timestep:
        soc = results_timestep[ts_prev][3]["soc"]
    else:
        # first timestep → SOC = 0
        soc = 0.0

    if node_balance != 0:
        results = model_optimization_chp_fit(
            heat_demand=input[0, 2],
            flex_demand=input[0, 7],
            cop_bhp=cop_bhp,
            soc=soc,
            chp_map=chp_map_2,
        )

        if results["feasible"]:
            #put the results of the optimization as input data for the const profile for the rerun of the timestep
            col_p_el_bhp = prosumer.controller.object[0].input_columns[8]
            col_p_el_chp = prosumer.controller.object[0].input_columns[9]
            df_data.df.loc[ts, col_p_el_bhp] = results["p_el_bhp"]
            df_data.df.loc[ts, col_p_el_chp] = results["p_el_chp"]


            rerun = True
        else:
            rerun = False

    return rerun


def fit_chp_relations(chp_map, degree=1):
    """
    Fit a polynomial relation between CHP electrical power and recovered heat.

    Given a CHP performance map (with arrays of electrical and thermal
    outputs), this function performs a least-squares polynomial regression
    of heat flow as a function of electrical power.

    Parameters
    ----------
    chp_map : dict
        Dictionary containing at least:
        - "power_el_kw" : list of float
            Electrical power values [kW].
        - "heat_flow_recovered_kw" : list of float
            Corresponding recovered heat values [kW].
    degree : int, optional
        Degree of the polynomial fit (default is 1, i.e. linear).

    Returns
    -------
    dict
        Dictionary with keys:
        - "degree" : int
            Polynomial degree used.
        - "coeff_HE" : list of float
            Polynomial coefficients for H(E).
        - "bounds" : dict
            Min/max bounds for E and H.
    """
    # data of the thermal (H) and electric (E) output
    E = np.array(chp_map["power_el_kw"], dtype=float)
    H = np.array(chp_map["heat_flow_recovered_kw"], dtype=float)

    idx = np.argsort(E)
    E, H = E[idx], H[idx]

    X = np.vander(E, N=degree+1, increasing=True)

    # Least Squares Fit: H = f(E)
    coeff_HE, *_ = np.linalg.lstsq(X, H, rcond=None)

    # Bounds
    E_min, E_max = float(E.min()), float(E.max())
    H_min, H_max = float(H.min()), float(H.max())

    return {
        "degree": degree,
        "coeff_HE": coeff_HE.tolist(),
        "bounds": {"E": (E_min, E_max), "H": (H_min, H_max)}
    }

def poly_expr(coeffs, x):
    return sum(coeffs[i] * (x**i) for i in range(len(coeffs)))


def model_optimization_chp_fit(heat_demand, flex_demand, cop_bhp, soc, chp_map,
                               resol=900, degree=1, storage_cap=10000, q_bhp_max=2000):
    """
    Build and solve a Pyomo MINLP for CHP + heat pump + storage dispatch.

    The model decides on CHP electrical output, heat pump consumption,
    and storage charging/discharging to satisfy heat and electrical
    balances at minimum heat pump electricity use. The CHP thermal
    output is approximated by a polynomial fit of electrical power.

    Parameters
    ----------
    heat_demand : float
        Heat demand at the current timestep [kW].
    flex_demand : float
        Flexible electrical demand (e.g. load to be balanced) [kW].
    cop_bhp : float
        Coefficient of performance of the heat pump [-].
    soc : float
        Current state of charge of the thermal storage [0–1].
    chp_map : dict
        CHP performance map with electrical and thermal outputs.
    resol : int, optional
        Timestep resolution in seconds (default 900).
    degree : int, optional
        Degree of polynomial fit for CHP relation (default 1).
    storage_cap : float, optional
        Thermal storage capacity [kWh] (default 10000).
    q_bhp_max : float, optional
        Maximum thermal output of the heat pump [kW] (default 2000).

    Returns
    -------
    dict
        If feasible:
        - "p_el_bhp" : float
            Heat pump electrical consumption [kW].
        - "p_el_chp" : float
            CHP electrical output [kW].
        - "q_th_bhp" : float
            Heat pump thermal output [kW].
        - "q_th_chp" : float
            CHP thermal output [kW].
        - "soc" : float
            State of charge (unchanged).
        - "q_th_discharge" : float
            Storage discharge [kW].
        - "q_th_charge" : float
            Storage charge [kW].
        - "heat_demand" : float
            Heat demand satisfied [kW].
        - "y_chp" : int
            CHP on/off status.
        - "el_balance" : float
            Value of electrical balance constraint.
        - "feasible" : bool
            True if optimization succeeded.
        Otherwise: {"feasible": False}.
    """
    fit = fit_chp_relations(chp_map, degree=degree)

    m = pyo.ConcreteModel()

    # Parameter
    m.heat_demand = pyo.Param(initialize=heat_demand)
    m.flex_demand = pyo.Param(initialize=flex_demand)
    m.cop_bhp     = pyo.Param(initialize=cop_bhp)
    m.q_th_bhp_max   = pyo.Param(initialize=q_bhp_max)
    m.soc         = pyo.Param(initialize=soc)
    m.storage_cap = pyo.Param(initialize=storage_cap)
    m.resol       = pyo.Param(initialize=resol)

    # decision variables for electrical input (BHP) and output (CHP)
    m.p_el_bhp  = pyo.Var(domain=pyo.NonNegativeReals)  # WP Stromverbrauch
    m.p_el_chp = pyo.Var(domain=pyo.NonNegativeReals)  # BHKW Strom

    # binary Variable for chp. To turn the chp of ig´f the load is out of bounds
    m.y_chp = pyo.Var(domain=pyo.Binary)

    # Bounds CHP
    p_el_min_chp = 0.2 * 700
    p_el_max_chp = 700

    #Bound Constraints CHP
    m.p_el_chp_min = pyo.Constraint(expr=m.p_el_chp >= p_el_min_chp * m.y_chp)
    m.p_el_chp_max = pyo.Constraint(expr=m.p_el_chp <= p_el_max_chp * m.y_chp)

    # variables thermal output
    m.q_th_bhp  = pyo.Var(domain=pyo.NonNegativeReals)  # WP Wärme
    m.q_th_chp = pyo.Var(domain=pyo.NonNegativeReals)

    ## Relation between thermal and electric ouput CHP
    # coefficient of the fit curve of thermal and electric output of the CHP
    coeff_HE = fit["coeff_HE"]
    M_chp = 5000  # Big-M

    #  Link q_th_chp to polynomial of p_el_chp only if CHP is on (y_chp = 1), relaxed otherwise
    m.q_th_chp_upper = pyo.Constraint(
        expr=m.q_th_chp <= poly_expr(coeff_HE, m.p_el_chp) + M_chp * (1 - m.y_chp)
    )
    m.q_th_chp_lower = pyo.Constraint(
        expr=m.q_th_chp >= poly_expr(coeff_HE, m.p_el_chp) - M_chp * (1 - m.y_chp)
    )

    # If the CHP is off (y=0) no thermal output is allowed.
    m.q_th_chp_off = pyo.Constraint(expr=m.q_th_chp <= M_chp * m.y_chp)

    ## Relation between thermal and electric ouput BHP
    m.q_th_bhp = pyo.Expression(expr= m.cop_bhp * m.p_el_bhp)

    # capacity bound for the BHP
    m.hp_cap = pyo.Constraint(expr=m.q_th_bhp <= m.q_th_bhp_max)

    # stoage variables
    m.q_th_charge    = pyo.Var(domain=pyo.NonNegativeReals)
    m.q_th_discharge = pyo.Var(domain=pyo.NonNegativeReals)

    # Binary-vriables storage
    m.y_charge = pyo.Var(domain=pyo.Binary)
    m.y_discharge = pyo.Var(domain=pyo.Binary)

    #allows to only charge or discharge the storage. Not both at the same time.
    m.charge_discharge = pyo.Constraint(expr=m.y_discharge + m.y_charge <= 1)

    #bounds for charging or discharging the storge dependend on the soc
    m.q_th_charge_max   = pyo.Constraint(expr=m.q_th_charge <= m.storage_cap * (1 - m.soc) * m.resol / 3600 * m.y_charge)
    m.q_th_discharge_max = pyo.Constraint(expr=m.q_th_discharge <= m.storage_cap * m.soc * m.resol / 3600 * m.y_discharge)

    # balances
    m.heat_bal = pyo.Constraint(expr=m.q_th_bhp + m.q_th_chp + m.q_th_discharge - m.q_th_charge == m.heat_demand)
    m.el_bal   = pyo.Constraint(expr=-m.p_el_bhp + m.p_el_chp - m.flex_demand == 0)

    # objective to minimize the electric power consumption of the whole system.
    m.obj = pyo.Objective(
        expr=m.p_el_bhp,
        sense=pyo.minimize
    )

    # Solver
    solver = pyo.SolverFactory('mindtpy')
    results = solver.solve(m, strategy='OA', mip_solver='glpk', nlp_solver='ipopt')

    if (results.solver.status == SolverStatus.ok and
        results.solver.termination_condition == TerminationCondition.optimal):
        return {
            "p_el_bhp": pyo.value(m.p_el_bhp),
            "p_el_chp": pyo.value(m.p_el_chp),
            "q_th_bhp": pyo.value(m.q_th_bhp),
            "q_th_chp": pyo.value(m.q_th_chp),
            "soc": pyo.value(m.soc),
            "q_th_discharge": pyo.value(m.q_th_discharge),
            "q_th_charge": pyo.value(m.q_th_charge),
            "heat_demand": pyo.value(m.heat_demand),
            "y":pyo.value(m.y_chp),
            "el_balance": pyo.value(m.el_bal),
            "feasible": True
        }
    else:
        return {"feasible": False}

run_timeseries(prosumer, period, check_results_fct=check_results, verbose=True)


res_chp = prosumer.time_series.data_source.iloc[1].df
chp_p_el_out_kw = res_chp['p_el_out_kw']
chp_p_th_out_kw = res_chp['p_th_out_kw']


res_bhp = prosumer.time_series.data_source.iloc[0].df
bhp_p_el_in_kw = -res_bhp['p_el_floor']#or radiator?
bhp_q_th_ou_kw = res_bhp["q_floor"]

res_storage=prosumer.time_series.data_source.iloc[2].df
res_heat_demand=prosumer.time_series.data_source.iloc[3].df

p_el_balance = chp_p_el_out_kw + bhp_p_el_in_kw - flex

df = pd.DataFrame({
    "chp_p_el": chp_p_el_out_kw.values,
    "bhp_p_el": bhp_p_el_in_kw.values,
    "flex": flex,
    "p_el_balance": p_el_balance.values
}, index=res_chp.index)  # falls du den Zeitindex behalten willst
print(df)

import matplotlib.pyplot as plt
# Summen berechnen
p_el_sum = chp_p_el_out_kw + bhp_p_el_in_kw
q_th_sum = chp_p_th_out_kw + bhp_q_th_ou_kw
# DataFrame erweitern
df["p_el_sum"] = p_el_sum.values
df["q_th_sum"] = q_th_sum.values
df["q_delivered_storage"] = res_storage["q_delivered_kw"].values
df["q_received_demand"] = res_heat_demand["q_received_kw"].values
# Plotten
fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
# Elektrische Leistungen
ax[0].plot(df.index, df["chp_p_el"], label="CHP electric output (kW)")
ax[0].plot(df.index, df["bhp_p_el"], label="BHP electric input (kW)")
ax[0].plot(df.index, df["p_el_sum"], label="Combined electric demand (kW)", linewidth=2, color="black")
ax[0].plot(df.index, df["flex"], label="Flex-Signal (kW)", color="red", linewidth=1, linestyle="--")
ax[0].set_ylabel("Electrical power (kW)")
# ax[0].set_title("Elektrische Leistungen")
ax[0].legend()

ax[1].plot(df.index, df["q_delivered_storage"], label="Thermal output storage (kW)", linewidth=2, color="black")
ax[1].plot(df.index, df["q_received_demand"], label="Heat demand (kW)", color="red", linewidth=1, linestyle="--")
ax[1].set_ylabel("Thermal power (kW)")
ax[1].legend()
plt.show()

p_el_sum = chp_p_el_out_kw + bhp_p_el_in_kw
df = pd.DataFrame({
    "p_el_sum": p_el_sum.values,
    "flex": flex
}, index=res_chp.index)
import matplotlib.pyplot as plt
plt.figure(figsize=(12,6))
plt.plot(df.index, df["p_el_sum"], label="Summe elektrische Leistung (kW)", color="blue", linewidth=2)
plt.plot(df.index, df["flex"], label="Flex-Signal (kW)", color="orange", linewidth=2)
plt.xlabel("Zeit")
plt.ylabel(" [kW]")
plt.title("Elektrische Summe und Flex-Signal")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()




