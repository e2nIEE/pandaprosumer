from pandaprosumer import create_controlled_gas_boiler
from pandaprosumer.create_controlled import (create_controlled_network_coupling,create_controlled_heat_pump,
                                             create_controlled_heat_demand, create_controlled_chiller,
                                             create_empty_prosumer_container, create_period,
                                             create_controlled_const_profile)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.mapping import FluidMixEnergySystemMapping, GenericEnergySystemMapping
from pandapower import get_element_index
import numpy as np


def create_prosumer_heat_demand(data_source, time_res, start, end, level, net_hot):
    prosumer = create_empty_prosumer_container("heat demand")
    period = create_period(prosumer, time_res, start, end, 'utc', 'default')

    hd_params = {"name": 'heat_consumer'}

    cp_input_columns = ["Heating demand (kW)", "t_flow_hot_c", "t_return_hot_c"]
    cp_result_columns = ["q_demand_kw_cp", "t_flow_hot_c_cp", "t_return_hot_c_cp"]
    cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns, data_source,
                                                          period, level=0, order=0)
    hd_controller_index = create_controlled_heat_demand(prosumer, period=period, level=level, **hd_params)

    GenericMapping(container=prosumer,
                   initiator_id=cp_controller_index,
                   initiator_column=["q_demand_kw_cp", "t_flow_hot_c_cp"],#, "t_return_hot_c_cp"],
                   responder_id=hd_controller_index,
                   responder_column=["q_demand_kw", "t_feed_demand_c"],#, "t_return_demand_c"],
                   order=0)

    consumer_elmt_index = get_element_index(net_hot, 'heat_consumer', 'heat_consumer_demand_coupling')

    # Controller that reads the temperatures and deands from the net
    nc_read_dmd_index = create_controlled_network_coupling(net_hot,
                                                           consumer_elmt_index,
                                                           element_name='heat_consumer',
                                                           result_columns=['t_from_k', 't_to_k',
                                                                           'mdot_from_kg_per_s'],
                                                           temp_fluid_map_output_idx=0,
                                                           mdot_fluid_map_output_idx=2,
                                                           level=2,
                                                           order=0)
    # Controller that writes the demand (q_kw and mdot_kg_per_s) to the net
    nc_write_dmd_index = create_controlled_network_coupling(net_hot,
                                                            consumer_elmt_index,
                                                            element_name='heat_consumer',
                                                            input_columns=['qext_w', 'controlled_mdot_kg_per_s'],
                                                            level=1,
                                                            order=0)

    #Mapping of t_feed and mdot from the read_dmd to the heat_demand
    FluidMixEnergySystemMapping(container=net_hot,
                                initiator_id=nc_read_dmd_index,
                                responder_net=prosumer,
                                responder_id=hd_controller_index,
                                order=0,
                                no_chain=False)

    #Mapping from t_return from the read demdn controller to the heat_demand
    GenericEnergySystemMapping(container=net_hot,
                               initiator_id=nc_read_dmd_index,
                               initiator_column='t_to_k',
                               responder_net=prosumer,
                               responder_id=hd_controller_index,
                               responder_column='t_return_demand_c',
                               order=1,
                               conversion_function=lambda t_k: t_k - 273.15)  # K -> °C, siehe Hinweis unten

    #Mapping of q_demand_kw from the heat_demand to the write dmd conteoller
    GenericEnergySystemMapping(container=prosumer,
                               initiator_id=cp_controller_index,  # Direkt vom ConstProfile
                               initiator_column='q_demand_kw_cp',  # Die ausgelesene kW-Spalte
                               responder_net=net_hot,
                               responder_id=nc_write_dmd_index,
                               responder_column='qext_w',
                               order=0,
                               conversion_function=lambda q: q * 1000)  # kW in W umrechnen


    # GenericEnergySystemMapping(container=prosumer,
    #                            initiator_id=hd_controller_index,
    #                            initiator_column='mdot_kg_per_s',
    #                            responder_net=net_hot,
    #                            responder_id=nc_write_dmd_index,
    #                            responder_column='controlled_mdot_kg_per_s',
    #                            order=1)

    return prosumer



def create_prosumer_prod(data_source, time_res, start, end, level, net_hot, net_cold):
    prosumer = create_empty_prosumer_container("producer")
    period = create_period(prosumer, time_res, start, end, 'utc', 'default')

    hp_params = {'carnot_efficiency': 0.5,
                 'pinch_c': 5,
                 'delta_t_evap_c': 5,
                 'max_p_comp_kw': 100}

    # cp_input_columns = ["t_evap_in_c"]
    # cp_result_columns = ["t_evap_in_c_cp"]
    # #
    # cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
    #                                                       data_source, period, level=0, order=0)

    hp_controller_index = create_controlled_heat_pump(prosumer, period=period, name='hp_controller',
                                                      level=level, order=0, **hp_params)
    gb_controller_index = create_controlled_gas_boiler(prosumer, period=period, max_q_kw=2000, name='gb_controller',
                                                       level=level, order=1)

    # This is just a workaround as long as the evaporater side is not connected to the cold net
    # GenericMapping(container=prosumer,
    #                initiator_id=cp_controller_index,
    #                initiator_column="t_evap_in_c_cp",
    #                responder_id=hp_controller_index,
    #                responder_column="t_evap_in_c",
    #                order=0)

    pump_elmt_index = get_element_index(net_hot, 'circ_pump_pressure', 'pump_hp_coupling')

    # Controller that writes the flow temperature and massflow of the heat generator to the net
    nc_write_pump_index = create_controlled_network_coupling(net_hot,
                            pump_elmt_index,
                            element_name = 'circ_pump_pressure',
                            temp_fluid_map_input_col = ['t_flow_k'],
                            mdot_fluid_map_input_col = ['mdot_flow_kg_per_s'],
                            level = 1,
                            order = 0)
     # Mapping of teperatuer and massflow from the heat pump to the writ pump controller
    FluidMixEnergySystemMapping(container=prosumer,
                                initiator_id=hp_controller_index,
                                responder_net=net_hot,
                                responder_id=nc_write_pump_index,
                                order=0,
                                no_chain=False)
    # Mapping of temperatuer and massflow from the gas boiler to the writ pump controller
    FluidMixEnergySystemMapping(container=prosumer,
                                initiator_id=gb_controller_index,
                                responder_net=net_hot,
                                responder_id=nc_write_pump_index,
                                order=0,
                                no_chain=False)

    #### ----------- Cooling side -------------------------------------

    pump_cold_elmt_index = get_element_index(net_cold, 'circ_pump_pressure', 'pump_hp_coupling')

    nc_read_pump_cold_index = create_controlled_network_coupling(
        net_cold,
        pump_cold_elmt_index,
        element_name='circ_pump_pressure',
        result_columns=['t_from_k', 't_to_k', 'mdot_from_kg_per_s'],
        temp_fluid_map_output_idx=0,  # t_from_k -> Temperatur, die zur Pumpe zurückfließt
        mdot_fluid_map_output_idx=2,
        level=2,
        order=0,
        name='nc_read_pump_cold'
    )

    FluidMixEnergySystemMapping(container=net_cold,
                                initiator_id=nc_read_pump_cold_index,
                                responder_net=prosumer,
                                responder_id=hp_controller_index,
                                order=0,
                                no_chain=True)  # analog zur Verbraucher-Kopplung

    nc_write_pump_cold_index = create_controlled_network_coupling(
        net_cold,
        pump_cold_elmt_index,
        element_name='circ_pump_pressure',
        input_columns=['t_flow_k'],
        level=4,
        order=0,
        name='nc_write_pump_cold'
    )

    GenericEnergySystemMapping(container=prosumer,
                               initiator_id=hp_controller_index,
                               initiator_column='t_evap_out_c',
                               responder_net=net_cold,
                               responder_id=nc_write_pump_cold_index,
                               responder_column='t_flow_k',
                               order=1,
                               no_chain=True,
                               conversion_function=lambda t: t + 273.15)

    return prosumer, hp_controller_index

# def create_prosumer_cooling_demand(data_source, time_res, start, end, level):
#     prosumer = create_empty_prosumer_container("cooling demand")
#     period = create_period(prosumer, time_res, start, end, 'utc', 'default')
#
#     hd_params = {"name": 'cooling_consumer'}
#
#     cp_input_columns = ["Cooling Demand (kW)", "t_flow_cold_c", "t_return_cold_c"]
#     cp_result_columns = ["q_demand_kw_cp", "t_flow_cold_c_cp", "t_return_cold_c_cp"]
#     cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns, data_source,
#                                                           period, level=0, order=0)
#     hd_controller_index = create_controlled_heat_demand(prosumer, period=period, level=level, **hd_params)
#
#     GenericMapping(container=prosumer,
#                    initiator_id=cp_controller_index,
#                    initiator_column=["q_demand_kw_cp", "t_flow_hot_c_cp", "t_return_hot_c_cp"],
#                    responder_id=hd_controller_index,
#                    responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
#                    order=0)
#
#     return prosumer
def create_prosumer_cooling_demand(data_source, time_res, start, end, net_cold):

    prosumer = create_empty_prosumer_container(
        "cooling_demand_prosumer"
    )

    period = create_period(prosumer, time_res, start, end, "utc", "default")

    # Read the hourly cooling demand from the Excel file.
    cp_controller_index = create_controlled_const_profile(
        prosumer,
        input_columns=["Cooling demand (kW)"],
        result_columns=["cooling_demand_kw_cp"],
        data_source=data_source,
        period=period,
        level=0,
        order=0
    )

    cooling_hx_index = get_element_index(
        net_cold,
        "heat_exchanger",
        "cooling_demand_heat_exchanger"
    )

    # Write the cooling demand into the cold-network heat exchanger.
    nc_write_cooling_index = create_controlled_network_coupling(
        net_cold,
        cooling_hx_index,
        element_name="heat_exchanger",
        input_columns=["qext_w"],
        level=1,
        order=0,
        name="nc_write_cooling_demand"
    )

    GenericEnergySystemMapping(
        container=prosumer,
        initiator_id=cp_controller_index,
        initiator_column="cooling_demand_kw_cp",
        responder_net=net_cold,
        responder_id=nc_write_cooling_index,
        responder_column="qext_w",
        order=0,
        no_chain=True,
        conversion_function=lambda q_kw: -q_kw * 1000
    )

    cooling_flow_index = get_element_index(
        net_cold,
        "flow_control",
        "cooling_demand_flow_control"
    )

    # Controller that writes the required mass flow into the cold network.
    nc_write_flow_index = create_controlled_network_coupling(
        net_cold,
        cooling_flow_index,
        element_name="flow_control",
        input_columns=["controlled_mdot_kg_per_s"],
        level=1,
        order=1,
        name="nc_write_cooling_mass_flow"
    )

    # Convert cooling demand from kW to the required mass flow.
    GenericEnergySystemMapping(
        container=prosumer,
        initiator_id=cp_controller_index,
        initiator_column="cooling_demand_kw_cp",
        responder_net=net_cold,
        responder_id=nc_write_flow_index,
        responder_column="controlled_mdot_kg_per_s",
        order=1,
        no_chain=True,
        conversion_function=lambda q_kw: (
            q_kw * 1000 / (4182 * 5.0)
        )
    )

    return prosumer



def create_prosumer_chiller(data_source, time_res, start, end, net_cold, level=6):
    prosumer = create_empty_prosumer_container("chiller_prosumer")

    period = create_period(prosumer, time_res, start, end, "utc", "default")

    # Only condenser temperatures remain fixed for now.
    cp_input_columns = [
        "chiller_t_cond_flow_c",
        "chiller_t_cond_return_c"
    ]

    cp_result_columns = [
        "chiller_t_cond_flow_c_cp",
        "chiller_t_cond_return_c_cp"
    ]

    cp_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns, data_source, period, level=0, order=0)

    carnot_efficiency = 0.5
    pinch_c = 5
    condenser_flow_c = 40
    target_cold_supply_c = 10
    max_p_comp_kw = 1000

    reversed_hp_index = create_controlled_heat_pump(
        prosumer,
        period=period,
        name="reversed_hp_controller",
        carnot_efficiency=carnot_efficiency,
        pinch_c=pinch_c,
        delta_t_evap_c=8,
        max_p_comp_kw=max_p_comp_kw,
        level=level,
        order=0
    )

    pump_cold_index = get_element_index(
        net_cold,
        "circ_pump_pressure",
        "pump_hp_coupling"
    )

    # Main-loop mass flow is currently fixed by the flow controller.
    cooling_flow_index = get_element_index(
        net_cold,
        "flow_control",
        "cooling_demand_flow_control"
    )

    nc_read_chiller_index = create_controlled_network_coupling(
        net_cold,
        pump_cold_index,
        element_name="circ_pump_pressure",
        result_columns=[
            "t_from_k",
            "t_to_k",
            "mdot_from_kg_per_s"
        ],
        temp_fluid_map_output_idx=1,
        mdot_fluid_map_output_idx=2,
        level=5,
        order=0,
        name="nc_read_chiller_evaporator"
    )

    FluidMixEnergySystemMapping(
        container=net_cold,
        initiator_id=nc_read_chiller_index,
        responder_net=prosumer,
        responder_id=reversed_hp_index,
        order=0,
        no_chain=False
    )

    ambient_sink_index = create_controlled_heat_demand(
        prosumer,
        period=period,
        name="temporary_ambient_sink",
        level=level,
        order=1
    )

    # Map required condenser temperatures.
    GenericMapping(
        container=prosumer,
        initiator_id=cp_index,
        initiator_column=[
            "chiller_t_cond_flow_c_cp",
            "chiller_t_cond_return_c_cp"
        ],
        responder_id=ambient_sink_index,
        responder_column=[
            "t_feed_demand_c",
            "t_return_demand_c"
        ],
        order=0
    )

    def calculate_required_q_cond_kw(t_evap_in_k):
        """Calculate condenser demand required for a 10 °C cold supply."""

        t_evap_in_c = np.asarray(t_evap_in_k) - 273.15

        mdot_cold_kg_per_s = float(
            net_cold.flow_control.at[
                cooling_flow_index,
                "controlled_mdot_kg_per_s"
            ]
        )

        # Required heat extraction from the cold water. Q = mdot × cp × ΔT
        q_evap_required_kw = (
            mdot_cold_kg_per_s
            * 4.18
            * np.maximum(t_evap_in_c - target_cold_supply_c, 0)
        )

        # Same simplified COP equation used by the HP model.
        temperature_lift_c = np.maximum(
            condenser_flow_c - t_evap_in_c,
            0.1
        )

        cop = (
            carnot_efficiency
            * (condenser_flow_c + pinch_c + 273.15)
            / temperature_lift_c
        )
        cop = np.maximum(cop, 1.01)

        q_cond_required_kw = (
            q_evap_required_kw
            * cop
            / (cop - 1)
        )

        # Compressor limitation: p_comp = q_cond / COP.
        q_cond_max_kw = max_p_comp_kw * cop

        return np.minimum(q_cond_required_kw, q_cond_max_kw)

    # Dynamically control chiller power from its inlet temperature.
    GenericEnergySystemMapping(
        container=net_cold,
        initiator_id=nc_read_chiller_index,
        initiator_column="t_to_k",
        responder_net=prosumer,
        responder_id=ambient_sink_index,
        responder_column="q_demand_kw",
        order=1,
        no_chain=True,
        conversion_function=calculate_required_q_cond_kw
    )

    # Condenser output goes to the temporary ambient heat sink.
    FluidMixMapping(
        container=prosumer,
        initiator_id=reversed_hp_index,
        responder_id=ambient_sink_index,
        order=0,
        no_chain=False
    )

    # Chiller evaporator outlet becomes the cold-network supply.
    nc_write_chiller_index = create_controlled_network_coupling(
        net_cold,
        pump_cold_index,
        element_name="circ_pump_pressure",
        input_columns=["t_flow_k"],
        level=7,
        order=0,
        name="nc_write_chiller_evaporator"
    )

    GenericEnergySystemMapping(
        container=prosumer,
        initiator_id=reversed_hp_index,
        initiator_column="t_evap_out_c",
        responder_net=net_cold,
        responder_id=nc_write_chiller_index,
        responder_column="t_flow_k",
        order=1,
        no_chain=True,
        conversion_function=lambda t_c: t_c + 273.15
    )

    return prosumer