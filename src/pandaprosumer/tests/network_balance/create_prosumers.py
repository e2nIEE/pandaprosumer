from pandaprosumer2.mapping import GenericMapping
from ..create_elements_controllers import *


def create_prosumer_prod(hp_level):
    prosumer = create_empty_prosumer_container(name='prosumer_prod')
    period, data_source = define_and_get_period_and_data_source(prosumer)

    cp_input_columns = ["Tin,evap"]
    cp_result_columns = ["Tin,evap"]

    hp_params = {'carnot_efficiency': 0.5,
                 'pinch_c': 5,
                 'delta_t_evap_c': 8,
                 'max_p_comp_kw': 1000e3}

    cp_controller_index = init_const_profile_controller(prosumer, cp_input_columns, cp_result_columns,
                                                        period, data_source, 0)
    heat_pump_index = init_hp_element(prosumer, **hp_params)
    hp_controller_index = init_hp_controller(prosumer, period, [heat_pump_index], hp_level)

    GenericMapping(container=prosumer,
                   initiator_id=cp_controller_index,
                   initiator_column="Tin,evap",
                   responder_id=hp_controller_index,
                   responder_column="t_evap_in_c",
                   order=0)

    return prosumer


def create_prosumer_dmd_hx(level):
    prosumer = create_empty_prosumer_container()
    period, data_source = define_and_get_period_and_data_source(prosumer)

    cp_input_columns = ["demand_4"]  # demand_4 is 10 times lower than demand_1, doesn't work with demand_1 ?
    cp_result_columns = ["demand_kw"]

    hx_params = {'t_1_in_nom_c': 45,  # HX will return nan if 50°C is used
                 't_1_out_nom_c': 30,
                 't_2_in_nom_c': 20,
                 't_2_out_nom_c': 40,
                 'mdot_2_nom_kg_per_s': 1.2}

    hd_params = {'t_in_set_c': 40,
                 't_out_set_c': 20}

    cp_controller_index = init_const_profile_controller(prosumer, cp_input_columns, cp_result_columns,
                                                        period, data_source, 0)
    hx_index = init_hx_element(prosumer, **hx_params)
    heat_demand_index = init_hd_element(prosumer, **hd_params)
    hx_controller_index = init_hx_controller(prosumer, period, [hx_index], level=level, order=0)
    hd_controller_index = init_hd_controller(prosumer, period, [heat_demand_index], level=level, order=1)

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
