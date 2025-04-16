from pandapower.timeseries.data_sources.frame_data import DFData
import pandas as pd


chp_size = 1.2
chp_name = 'example_chp'
altitude = 0

hp_type = "water-water"
hp_name = 'example_hp'

q_capacity_kwh = 50

start = '2020-01-01 00:00:00'
end = '2020-01-01 23:59:59'
time_resolution = 900

demand_data = pd.read_excel('example_data/hp_chp_test.xlsx')

dur = pd.date_range(start, end, freq="15min", tz='utc')
demand_data.index = dur
demand_input = DFData(demand_data)

from pandaprosumer.create import create_empty_prosumer_container
prosumer = create_empty_prosumer_container()

from pandaprosumer.create import create_period
period = create_period(prosumer, time_resolution, start, end, 'utc', 'default')

from pandaprosumer.create import create_ice_chp
chp_index = create_ice_chp(prosumer, chp_size, altitude)

from pandaprosumer.create import create_booster_heat_pump
hp_index = create_booster_heat_pump(prosumer, hp_type, name=hp_name)

from pandaprosumer.create import create_heat_storage
heat_storage_index = create_heat_storage(prosumer,q_capacity_kwh=q_capacity_kwh)

from pandaprosumer.create import create_heat_demand
create_heat_demand(
    prosumer, scaling=1.0
)

from pandaprosumer.controller.data_model import ConstProfileControllerData
const_controller_data = ConstProfileControllerData(
    input_columns=['cycle', 't_source', 'demand', 'mode'],
    result_columns=["cycle_cp", 't_source_cp', "demand_cp", 'mode_cp'],
    period_index = period
)

from pandaprosumer.controller.data_model.ice_chp import IceChpControllerData
ice_chp_controller_data = IceChpControllerData(
    element_name='ice_chp',                                                 # PM: copy of this here
    element_index=[chp_index],
    period_index=period
)

from pandaprosumer.controller.data_model import BoosterHeatPumpControllerData
booster_heat_pump_controller_data = BoosterHeatPumpControllerData(
    element_name='booster_heat_pump',
    element_index=[hp_index],
    period_index=period
)

from pandaprosumer.controller.data_model.heat_demand_kassel import HeatDemandKasselControllerData
heat_demand_controller_data = HeatDemandKasselControllerData(
    element_name='heat_demand',
    element_index=[0],
    period_index=period
)

from pandaprosumer.controller import HeatStorageControllerData
heat_storage_controller_data = HeatStorageControllerData(
    element_name='heat_storage',
    element_index=[heat_storage_index],
    period_index=period
)

from pandaprosumer.controller import ConstProfileController
ConstProfileController(prosumer,
                       const_object=const_controller_data,
                       df_data=demand_input,
                       order=0,
                       level=0)

from pandaprosumer.controller import IceChpController
ice_chp_obj = IceChpController(prosumer,
                          ice_chp_controller_data,
                          order=1,
                          level=0)

from pandaprosumer.controller import BoosterHeatPumpController
BoosterHeatPumpController(prosumer,
                               booster_heat_pump_controller_data,
                               order=2,
                               level=0)

from pandaprosumer.controller import HeatStorageController
HeatStorageController(prosumer,
                      heat_storage_controller_data,
                      order=3,
                      level=0)

from pandaprosumer.controller import HeatDemandControllerKassel
HeatDemandControllerKassel(prosumer,
                           heat_demand_controller_data,
                           order=4,
                           level=0)

from pandaprosumer.mapping import GenericMapping
GenericMapping(
    prosumer,
    initiator_id=0,
    initiator_column="cycle_cp",
    responder_id=1,
    responder_column="cycle",
    order=0
)

from pandaprosumer.mapping import GenericMapping
GenericMapping(
    prosumer,
    initiator_id=0,
    initiator_column="t_source_cp",
    responder_id=2,
    responder_column="t_source_k",
    order=0
)

from pandaprosumer.mapping import GenericMapping
GenericMapping(
    prosumer,
    initiator_id=0,
    initiator_column="mode_cp",
    responder_id=2,
    responder_column="mode",
    order=0
)

from pandaprosumer.mapping import GenericMapping
GenericMapping(
    prosumer,
    initiator_id=0,
    initiator_column="demand_cp",
    responder_id=4,
    responder_column="q_demand_kw",
    order=0
)

from pandaprosumer.mapping import GenericMapping
GenericMapping(
    prosumer,
    initiator_id=1,
    initiator_column="p_el_mw",
    responder_id=2,
    responder_column="p_received_kw",
    order=0
)

from pandaprosumer.mapping import GenericMapping
GenericMapping(
    prosumer,
    initiator_id=1,
    initiator_column="p_th_mw",
    responder_id=2,
    responder_column="q_received_kw",
    order=0
)

from pandaprosumer.mapping import GenericMapping
GenericMapping(
    prosumer,
    initiator_id=2,
    initiator_column="q_floor",
    responder_id=3,
    responder_column="q_received_kw",
    order=0
)

from pandaprosumer.mapping import GenericMapping
GenericMapping(
    prosumer,
    initiator_id=3,
    initiator_column="q_delivered_kw",
    responder_id=4,
    responder_column="q_received_kw",
    order=0
)

from pandaprosumer.run_time_series import run_timeseries
run_timeseries(prosumer, period)

# removing the log file handler:
ice_chp_obj.remove_logfile_handler()


import matplotlib.pyplot as plt
print(prosumer.time_series.data_source.loc[2].df.head())
# subplots

fig, axes = plt.subplots(nrows=4, ncols=1, figsize=(10, 6), sharex=True)

# Plot the first time series on the first subplot
prosumer.time_series.data_source.loc[0].df.p_th_mw.plot(ax=axes[0])
axes[0].set_title("P_th (MW) Time Series")
axes[0].set_ylabel("P_th (MW)")

# Plot the second time series on the second subplot
prosumer.time_series.data_source.loc[2].df.soc.plot(ax=axes[1])
axes[1].set_title("Storage Heat Demand Time Series")
axes[1].set_ylabel("Storage Heat Demand")

# Plot the third time series on the third subplot
prosumer.time_series.data_source.loc[1].df.q_floor.plot(ax=axes[2])
axes[2].set_title("q_floor Time Series")
axes[2].set_ylabel("q_floor")
axes[2].set_xlabel("Time")

prosumer.time_series.data_source.loc[0].df.p_el_mw.plot(ax=axes[3])
axes[2].set_title("p_el")
axes[2].set_ylabel("p_el")
axes[2].set_xlabel("Time")

# Adjust layout and display
plt.tight_layout()
plt.show()