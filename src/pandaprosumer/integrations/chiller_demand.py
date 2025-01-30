import pickle
import random

import pandas as pd
import matplotlib.pyplot as plt
import pyromat as pm

from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer.controller.const_profile import ConstProfileController
from pandaprosumer.controller.data_model.const_profile import ConstProfileControllerData
from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.create import create_empty_prosumer_container, define_period, define_senergy_nets_chiller, cr
from pandaprosumer.controller import SenergyNetsChillerController, SenergyNetsChillerControllerData, \
    HeatDemandController, HeatDemandControllerData
from pandaprosumer.mapping import GenericMapping

from pandaprosumer import ppros2_dir


def _define_and_get_period_and_data_source(prosumer):
    data = pd.read_excel(f"{ppros2_dir}/../demo/data/senergy_nets_example_chiller.xlsx")
    start = '2020-01-01 00:00:00'
    end = '2020-01-01 01:59:59'
    resol = 3600
    dur = pd.date_range(start, end, freq='%ss' % resol)
    data.index = dur
    data_source = DFData(data)
    period = define_period(prosumer,
                           3600,
                           '2020-01-01 00:00:00',
                           '2020-01-01 01:59:59',
                           'utc',
                           'default')
    return period, data_source


if __name__ == '__main__':
    """
    In this example, a single ConstProsumer is mapped to a heat pump, element-wise (there is only one of each, but the
    logic carries forward for multiple, as long as there as many ConstProsumers as heat pumps
    """

    random.seed(0)

    prosumer = create_empty_prosumer_container()
    period, data_source = _define_and_get_period_and_data_source(prosumer)

    # ==================================================================================================================
    # components
    # ==================================================================================================================

    # Create a SenergyNetsHeatPump component. Get back the index of this component.
    # The table it gets created in is called "heat_pump"
    define_senergy_nets_chiller(prosumer)
    define_heat_demand(
        prosumer
    )

    # ==================================================================================================================
    # controllers
    # ==================================================================================================================

    const_controller_data = ConstProfileControllerData(
        input_columns=["Set Point Temperature T_set [K]", "Evaporator inlet temperature T_in_ev [K]",
                       "Condenser inlet temperature T_in_cond [K]",
                       "Condenser temperature increase Dt_cond [K]", "Cooling demand Q_load [kJ/h]",
                       "Isentropic efficiency N_is [-]",
                       "Maximum chiller power Q_max [kJ/h]", "Control signal Ctrl [-]"],
        result_columns=["t_set_pt_const_profile_in_c", "t_evap_in_const_profile_in_c",
                        "t_cond_inlet_const_profile_in_c", "t_cond_delta_t_const_profile_in_c",
                        "q_chiller_demand_const_profile_kw", "n_is_const_profile", "q_max_deliverable_const_profile_kw",
                        "ctrl_signal_const_profile"],
        period_index=period,
    )

    chiller_controller_data = SenergyNetsChillerControllerData(
        element_name='sn_chiller',
        element_index=[0],
        period_index=period
    )
    heat_demand_controller_data = HeatDemandControllerData(
        element_name='heat_demand',
        element_index=[0],
        period_index=period
    )

    # ==================================================================================================================
    # coupling
    # ==================================================================================================================

    ConstProfileController(prosumer,
                           const_object=const_controller_data,
                           df_data=data_source,
                           order=0,
                           level=0)

    SenergyNetsChillerController(prosumer,
                                 chiller_controller_data,
                                 order=1,
                                 level=0)

    HeatDemandController(prosumer,
                         heat_demand_controller_data,
                         order=2,
                         level=0)

    GenericMapping(prosumer=prosumer,
                   initiator=0,
                   initiator_column="t_cond_inlet_const_profile_in_c",
                   responder=1,
                   responder_column="t_in_cond_c",
                   order=0)
    GenericMapping(prosumer=prosumer,
                   initiator=0,
                   initiator_column="t_cond_delta_t_const_profile_in_c",
                   responder=1,
                   responder_column="dt_cond_c",
                   order=0)
    GenericMapping(prosumer=prosumer,
                   initiator=0,
                   initiator_column="t_evap_in_const_profile_in_c",
                   responder=1,
                   responder_column="t_in_ev_c",
                   order=0)
    GenericMapping(prosumer=prosumer,
                   initiator=0,
                   initiator_column="n_is_const_profile",
                   responder=1,
                   responder_column="n_is",
                   order=0)
    GenericMapping(prosumer=prosumer,
                   initiator=0,
                   initiator_column="t_set_pt_const_profile_in_c",
                   responder=1,
                   responder_column="t_set_pt_c",
                   order=0)
    GenericMapping(prosumer=prosumer,
                   initiator=0,
                   initiator_column="q_max_deliverable_const_profile_kw",
                   responder=1,
                   responder_column="q_max_kw",
                   order=0)
    GenericMapping(prosumer=prosumer,
                   initiator=0,
                   initiator_column="ctrl_signal_const_profile",
                   responder=1,
                   responder_column="ctrl",
                   order=0)

    GenericMapping(prosumer=prosumer,
                   initiator=0,
                   initiator_column="q_chiller_demand_const_profile_kw",
                   responder=2,
                   responder_column="q_demand_kw",
                   order=0)
    GenericMapping(prosumer=prosumer,
                   initiator=1,
                   initiator_column="q_cond_kw",
                   responder=2,
                   responder_column="q_received_kw",
                   order=0)

# ==================================================================================================================
# run timeseries
# ==================================================================================================================

run_timeseries(prosumer, period, True)

# ==================================================================================================================
# results
# ==================================================================================================================

# res_df = prosumer.time_series.loc[4].data_source.df

print()