from pandaprosumer.mapping import GenericMapping
from pandaprosumer import *
from tests.data_sources.define_period import define_and_get_period_and_data_source

def create_prosumer_prod(hp_level):
    prosumer = create_empty_prosumer_container(name='prosumer_prod',check_order=False)
    period, data_source = define_and_get_period_and_data_source(prosumer)

    cp_input_columns = ["Tin,evap"]
    cp_result_columns = ["Tin,evap"]

    hp_params = {'carnot_efficiency': 0.5,
                 'pinch_c': 5,
                 'delta_t_evap_c': 8,
                 'max_p_comp_kw': 1000e3}

    cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                        period, data_source, 0)


    hp_controller_index = create_controlled_heat_pump(prosumer,period =period,level=hp_level,order = 0,**hp_params)
    GenericMapping(container=prosumer,
                   initiator_id=cp_controller_index,
                   initiator_column="Tin,evap",
                   responder_id=hp_controller_index,
                   responder_column="t_evap_in_c",
                   order=0)

    return prosumer


def create_prosumer_dmd_hx(level):
    prosumer = create_empty_prosumer_container(check_order=False)
    period, data_source = define_and_get_period_and_data_source(prosumer)

    cp_input_columns = ["demand_1"]  # demand_4 is 10 times lower than demand_1, doesn't work with demand_1 ?
    cp_result_columns = ["demand_kw"]

    hx_params = {'t_1_in_nom_c': 45,  # HX will return nan if 50°C is used
                 't_1_out_nom_c': 30,
                 't_2_in_nom_c': 20,
                 't_2_out_nom_c': 40,
                 'mdot_2_nom_kg_per_s': 3.58}

    hd_params = {'t_in_set_c': 40,
                 't_out_set_c': 20}

    cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                        period, data_source, 0)

    hx_controller_index = create_controlled_heat_exchanger(prosumer, period =period,level=level,order = 0,**hx_params)
    hd_controller_index = create_controlled_heat_demand(prosumer, period =period,level=level,order = 1,**hd_params)

    GenericMapping(container=prosumer,
                   initiator_id=cp_controller_index,
                   initiator_column="demand_kw",
                   responder_id=hd_controller_index,
                   responder_column="q_demand_kw",
                   order=0)

    FluidMixMapping(container=prosumer,
                    initiator_id=hx_controller_index,
                    responder_id=hd_controller_index,
                    order=0)

    return prosumer
