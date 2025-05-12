from pandaprosumer.mapping import GenericMapping
from pandaprosumer.supervisor.supervisor import *
from pandaprosumer import *
import numpy as np
import re
from pandaprosumer.run_time_series import run_timeseries

def _define_and_get_period_and_data_source(prosumer):
    data = pd.DataFrame({"Tin_evap": [25, 25, 25, 35],
                         "demand_1": [50, 200, 800, 300],
                         "heating": [True,True,True,False],
                         "t_return_demand_c": [30,30,30,20],
                         "t_feed_demand_c": [40,40,40,30]})

    start = '2020-01-01 00:00:00'
    resol = 3600
    end = pd.Timestamp(start) + len(data["Tin_evap"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
    dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
    period = create_period(prosumer,
                           resol,
                           start,
                           end,
                           'utc',
                           'default')

    data.index = dur
    data_source = DFData(data)


    return period, data_source


prosumer = create_empty_prosumer_container()
period, data_source = _define_and_get_period_and_data_source(prosumer)

input_columns = ['Tin_evap', 'demand_1','heating', "t_return_demand_c","t_feed_demand_c"]
result_columns = ['Tin_evap', 'demand_1','heating', "t_return_demand_c","t_feed_demand_c"]

hp_params = {'carnot_efficiency': 0.5,
         'pinch_c': 0,
         'delta_t_evap_c': 5,
         'max_p_comp_kw': 100}
hd_params = {}
# hd_params = {'t_in_set_c': 40, 't_out_set_c': 30}
cp = create_controlled_const_profile(prosumer,input_columns=input_columns,result_columns=result_columns,period=period,data_source=data_source)
supervisor_index = create_controlled_supervisor(prosumer, input_columns, period, level = 1)
hp = create_controlled_heat_pump(prosumer,
                                 order =0,
                                 level=2,
                                 **hp_params)
hd = create_controlled_heat_demand(prosumer,
                                   order = 1,
                                   level = 2,
                                   **hd_params)

supervisor = prosumer.controller.iloc[supervisor_index].object
r = Rule('heating','==',True, hp, 'heating',True,False)
supervisor.add_rule(r)



GenericMapping(prosumer,
               cp,
            'Tin_evap',
               hp,
               responder_column='t_load_in_c')
GenericMapping(prosumer,
               cp,
                initiator_column='heating',
               responder_id = supervisor_index,
               responder_column='heating'
               )
GenericMapping(prosumer,
               cp,
               ['demand_1','t_return_demand_c','t_feed_demand_c'],
               hd,
               ['q_demand_kw','t_return_demand_c','t_feed_demand_c'])
FluidMixMapping(prosumer,
                hp,
                hd,
                order =0)

run_timeseries(prosumer, period, True)

print(prosumer.time_series.loc[0, 'data_source'].df)
