import pandaprosumer as ppr
from create_nets import create_thermal_networks
from create_prosumer import *
from create_energy_system import _create_energy_system
import pandapipes as ppi
import pandas as pd
import numpy as np
import sys
import os
from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.energy_system.timeseries.run_time_series_energy_system import \
run_timeseries as run_time_series_system
from pandapower.control.basic_controller import Controller

start = '2024-06-01 00:00:00'
time_resolution_s = 3600

current_directory = os.getcwd()
parent_directory = os.path.dirname(current_directory)
sys.path.append(parent_directory)

demand_data = pd.read_excel('data/cordoba_hospital_data.xlsx')

# First week
n_steps_week = int(7 * 24 * 3600 / time_resolution_s)  # 168 bei 1h-Auflösung
# demand_data = demand_data.iloc[:n_steps_week]
demand_data = demand_data.iloc[:24]

end = (
    pd.Timestamp(start)
    + len(demand_data) * pd.Timedelta(seconds=time_resolution_s)
    - pd.Timedelta(seconds=1)
)

dur = pd.date_range(
    start=start,
    end=end,
    freq=f'{time_resolution_s}s',
    tz='utc'
)

demand_data.index = dur
demand_data["t_flow_cold_c"] = 10
demand_data["t_return_cold_c"] = 15
demand_data["t_flow_hot_c"] = 78
demand_data["t_return_hot_c"] = 70
# Assumed domestic-hot-water temperatures
demand_data["t_dhw_cold_c"] = 15.0
demand_data["t_dhw_hot_c"] = 60.0

# Real ambient temperature from Excel
demand_data["t_ambient_c"] = (demand_data["T_amb(°C)"].astype(float))
# Increase condenser temperatures only when ambient exceeds 25°C
temperature_increase_c = np.maximum(demand_data["t_ambient_c"] - 25.0, 0.0)
# Water from chiller condenser to Dry Cooler
demand_data["dry_cooler_t_in_c"] = (35.0 + temperature_increase_c)
# Water from Dry Cooler back to chiller condenser
demand_data["dry_cooler_t_out_c"] = (30.0 + temperature_increase_c)
# Required by the controller; adiabatic mode remains disabled
demand_data["phi_air_in_percent"] = 50.0



demand_input = DFData(demand_data)

net_cold, net_hot = create_thermal_networks()

prosumer_hd = create_prosumer_heat_demand(demand_input, time_resolution_s, start, end, level=4, net_hot=net_hot)
prosumer_cd = create_prosumer_cooling_demand(demand_input, time_resolution_s, start, end, net_cold=net_cold)
(
    prosumer_dhw,
    dhw_storage_controller_index,
    dhw_demand_controller_index
) = create_prosumer_dhw_system(
    demand_input,
    time_resolution_s,
    start,
    end,
    net_hot=net_hot
)
prosumer_prod, hp_controller_index, chiller_controller_index, dry_cooler_controller_index = create_prosumer_prod(demand_input, time_resolution_s, start, end, level=3, net_hot=net_hot, net_cold=net_cold)



energy_system = _create_energy_system([net_hot, net_cold], [ prosumer_cd, prosumer_hd, prosumer_prod, prosumer_dhw,], name="test_energy_system")

from pandapower.timeseries import OutputWriter

sample_prosumer_period = prosumer_prod.period
ow_time_steps = pd.date_range(sample_prosumer_period.iloc[0]["start"], sample_prosumer_period.iloc[0]["end"],
                              freq='%ss' % int(sample_prosumer_period.iloc[0]["resolution_s"]),
                              tz=sample_prosumer_period.iloc[0]["timezone"])
ow_net_hot = OutputWriter(net_hot, ow_time_steps, log_variables=[
    ('res_circ_pump_pressure', 't_from_k'),
    ('res_circ_pump_pressure', 't_to_k'),
    ('res_circ_pump_pressure', 'mdot_from_kg_per_s'),
    ('res_heat_consumer', 't_from_k'),
    ('res_heat_consumer', 't_to_k'),
    ('res_heat_consumer', 'mdot_from_kg_per_s'),
    ('heat_consumer', 'qext_w'),
    ('res_pipe', 'v_mean_m_per_s'),
    ('res_pipe', 't_from_k'),
    ('res_pipe', 't_to_k')
])
ow_net_cold = OutputWriter(
    net_cold,
    ow_time_steps,
    log_variables=[
        ("res_circ_pump_pressure", "t_from_k"),
        ("res_circ_pump_pressure", "t_to_k"),
        ("res_circ_pump_pressure", "mdot_from_kg_per_s"),
        ("heat_exchanger", "qext_w"),
        ("flow_control", "controlled_mdot_kg_per_s")
    ]
)


period_index = 0
run_time_series_system(energy_system,
                       period_index=period_index, continue_on_divergence=False, verbose=True,
                       transient=True, dt=time_resolution_s, mode="bidirectional")
