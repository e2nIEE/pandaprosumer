from pandaprosumer import create_controlled_gas_boiler
from pandapower.control.controller.const_control import ConstControl
from pandaprosumer.create_controlled import (create_controlled_network_coupling,create_controlled_heat_pump,
                                             create_controlled_heat_demand, create_controlled_chiller,
                                             create_controlled_dry_cooler,create_controlled_heat_storage,
                                             create_empty_prosumer_container, create_period,
                                             create_controlled_const_profile)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.mapping import FluidMixEnergySystemMapping, GenericEnergySystemMapping
from pandapower import get_element_index
import numpy as np

class ColdSideHpToChillerMapping(FluidMixMapping):

    def __init__(
        self,
        container,
        initiator_id,
        responder_id,
        net_cold,
        cooling_flow_index,
        order=0,
        no_chain=True,
        index=None
    ):
        super().__init__(
            container=container,
            initiator_id=initiator_id,
            responder_id=responder_id,
            order=order,
            no_chain=no_chain,
            index=index
        )

        self.net_cold = net_cold
        self.cooling_flow_index = cooling_flow_index

    def map(
        self,
        initiator_controller,
        responder_controller
    ):
        temperature_column_index = (
            initiator_controller.result_columns.index(
                "t_evap_out_c"
            )
        )

        temperature_after_hp_c = float(
            np.asarray(
                initiator_controller.step_results[
                    :,
                    temperature_column_index
                ]
            ).reshape(-1)[0]
        )

        cold_network_mass_flow = float(
            self.net_cold.flow_control.at[
                self.cooling_flow_index,
                "controlled_mdot_kg_per_s"
            ]
        )

        responder_controller.input_mass_flow_with_temp = {
            FluidMixMapping.TEMPERATURE_KEY:
                temperature_after_hp_c,

            FluidMixMapping.MASS_FLOW_KEY:
                cold_network_mass_flow
        }

cp_level = 0
nc_read_level_hot = 3
prosumer_prod_level_hot = 4
prosumer_dmd_level_hot = 5
nc_write_level_hot = 2
dhw_prosumer_level = 1

nc_read_level_cold = 3
# prosumer_prod_level_cold = 2
# prosumer_dmd_level_cold = 3
# nc_write_level_cold = 4



def create_prosumer_heat_demand(data_source, time_res, start, end, net_hot):
    prosumer = create_empty_prosumer_container("heat demand")
    period = create_period(prosumer, time_res, start, end, 'utc', 'default')

    hd_params = {"name": 'heat_consumer'}

    cp_input_columns = ["Heating demand (kW)", "t_flow_hot_c", "t_return_hot_c"]
    cp_result_columns = ["q_demand_kw_cp", "t_flow_hot_c_cp", "t_return_hot_c_cp"]

    cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns, data_source,
                                                          period, level=cp_level, order=0)
    hd_controller_index = create_controlled_heat_demand(prosumer, period=period, level=prosumer_dmd_level_hot, order=0, **hd_params)

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
                                                           level=nc_read_level_hot,
                                                           order=0)

    # Controller that writes the demand (q_kw and mdot_kg_per_s) to the net
    nc_write_dmd_index = create_controlled_network_coupling(net_hot,
                                                            consumer_elmt_index,
                                                            element_name='heat_consumer',
                                                            input_columns=['qext_w', 'controlled_mdot_kg_per_s'],
                                                            level=nc_write_level_hot,
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



def create_prosumer_prod(data_source, time_res, start, end, net_hot, net_cold):
    prosumer = create_empty_prosumer_container(
        "producer",
        # check_order=False
    )
    period = create_period(prosumer, time_res, start, end, 'utc', 'default')

    hp_params = {'carnot_efficiency': 0.5,
                 'pinch_c': 5,
                 'delta_t_evap_c': 5,
                 'max_p_comp_kw': 100}


    hp_controller_index = create_controlled_heat_pump(prosumer, period=period, name='hp_controller',
                                                      level=prosumer_prod_level_hot, order=1, **hp_params)
    gb_controller_index = create_controlled_gas_boiler(prosumer, period=period, max_q_kw=2000, name='gb_controller',
                                                       level=prosumer_prod_level_hot, order=2)


    pump_elmt_index = get_element_index(net_hot, 'circ_pump_pressure', 'pump_hp_coupling')

    # Controller that writes the flow temperature and massflow of the heat generator to the net
    nc_write_pump_index = create_controlled_network_coupling(net_hot,
                            pump_elmt_index,
                            element_name = 'circ_pump_pressure',
                            temp_fluid_map_input_col = ['t_flow_k'],
                            mdot_fluid_map_input_col = ['mdot_flow_kg_per_s'],
                            level = nc_write_level_hot,
                            order = 3)
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
        level=nc_read_level_cold,
        order=0,
        name='nc_read_pump_cold'
    )

    FluidMixEnergySystemMapping(container=net_cold,
                                initiator_id=nc_read_pump_cold_index,
                                responder_net=prosumer,
                                responder_id=hp_controller_index,
                                order=0,
                                no_chain=False)  # analog zur Verbraucher-Kopplung
    #
    # # GenericEnergySystemMapping(
    # #     container=net_cold,
    # #     initiator_id=nc_read_pump_cold_index,
    # #     initiator_column="t_from_k",
    # #     responder_net=prosumer,
    # #     responder_id=hp_controller_index,
    # #     responder_column="t_evap_in_c",
    # #     order=0,
    # #     no_chain=True,
    # #     conversion_function=lambda t_k: (
    # #         np.asarray(t_k) - 273.15
    # #     )
    # # )
    #
    # dry_cooler_cp_index = create_controlled_const_profile(
    #     prosumer,
    #     input_columns=["dry_cooler_t_in_c", "dry_cooler_t_out_c", "t_ambient_c", "phi_air_in_percent"],
    #     result_columns=["dry_cooler_t_in_c_cp", "dry_cooler_t_out_c_cp", "t_ambient_c_cp", "phi_air_in_percent_cp"],
    #     data_source=data_source,
    #     period=period,
    #     level=cp_level,
    #     order=0
    # )
    # chiller_carnot_efficiency = 0.5
    # chiller_pinch_c = 5
    # target_cold_supply_c = 10
    # chiller_max_p_comp_kw = 1000
    #
    # chiller_controller_index = create_controlled_heat_pump(
    #     prosumer,
    #     period=period,
    #     name="reversed_hp_controller",
    #     carnot_efficiency=chiller_carnot_efficiency,
    #     pinch_c=chiller_pinch_c,
    #     delta_t_evap_c=8,
    #     max_p_comp_kw=chiller_max_p_comp_kw,
    #     level=prosumer_prod_level_cold,
    #     order=4
    # )
    # dry_cooler_controller_index = create_controlled_dry_cooler(
    #     prosumer,
    #     period=period,
    #     name="dry_cooler_controller",
    #
    #     # Assumed aggregate nominal fan data
    #     n_nom_rpm=730.0,
    #     p_fan_nom_kw=40.0,
    #     qair_nom_m3_per_h=3_000_000.0,
    #
    #     # Nominal operating point
    #     t_air_in_nom_c=25.0,
    #     t_air_out_nom_c=30.0,
    #     t_fluid_in_nom_c=35.0,
    #     t_fluid_out_nom_c=30.0,
    #
    #     fans_number=10,
    #     adiabatic_mode=False,
    #     min_delta_t_air_c=1.0,
    #
    #     level=prosumer_prod_level_cold,
    #     order=5
    # )
    #
    # chiller_pump_cold_index = get_element_index(
    #     net_cold,
    #     "circ_pump_pressure",
    #     "pump_hp_coupling"
    # )
    #
    # cooling_flow_index = get_element_index(
    #     net_cold,
    #     "flow_control",
    #     "cooling_demand_flow_control"
    # )
    #
    # ColdSideHpToChillerMapping(
    #     container=prosumer,
    #     initiator_id=hp_controller_index,
    #     responder_id=chiller_controller_index,
    #     net_cold=net_cold,
    #     cooling_flow_index=cooling_flow_index,
    #     order=0,
    #     no_chain=True
    # )
    #
    # # Send temperatures and ambient conditions to the Dry Cooler.
    # GenericMapping(
    #     container=prosumer,
    #     initiator_id=dry_cooler_cp_index,
    #     initiator_column=[
    #         "dry_cooler_t_in_c_cp",
    #         "dry_cooler_t_out_c_cp",
    #         "t_ambient_c_cp",
    #         "phi_air_in_percent_cp"
    #     ],
    #     responder_id=dry_cooler_controller_index,
    #     responder_column=[
    #         "t_in_c",
    #         "t_out_c",
    #         "t_air_in_c",
    #         "phi_air_in_percent"
    #     ],
    #     order=0
    # )
    #
    # def calculate_required_mdot_cond_kg_per_s(t_after_hp_c):
    #     """
    #     Calculate the condenser-water flow required for the chiller
    #     to cool the cold network down to 10°C.
    #     """
    #
    #     t_evap_in_c = float(
    #         np.asarray(t_after_hp_c).reshape(-1)[0]
    #     )
    #
    #     # Current cold-network mass flow
    #     mdot_cold_kg_per_s = float(
    #         net_cold.flow_control.at[
    #             cooling_flow_index,
    #             "controlled_mdot_kg_per_s"
    #         ]
    #     )
    #
    #     # Heat that still must be removed from the cold network
    #     q_evap_required_kw = (
    #             mdot_cold_kg_per_s
    #             * 4.18
    #             * max(t_evap_in_c - target_cold_supply_c, 0.0)
    #     )
    #
    #     # Read the condenser temperatures for the current hour
    #     hp_controller = prosumer.controller.at[
    #         hp_controller_index,
    #         "object"
    #     ]
    #
    #     current_time = hp_controller.time
    #     current_profile = data_source.df.loc[current_time]
    #
    #     t_cond_hot_c = float(current_profile["dry_cooler_t_in_c"])
    #
    #     t_cond_cold_c = float(current_profile["dry_cooler_t_out_c"])
    #
    #     delta_t_cond_c = t_cond_hot_c - t_cond_cold_c
    #
    #     if delta_t_cond_c <= 0:
    #         raise ValueError(
    #             "Dry Cooler inlet temperature must be higher "
    #             "than its outlet temperature."
    #         )
    #
    #     # Chiller COP at the current condenser temperature
    #     temperature_lift_c = max(
    #         t_cond_hot_c - t_evap_in_c,
    #         0.1
    #     )
    #
    #     cop = (
    #             chiller_carnot_efficiency
    #             * (t_cond_hot_c + chiller_pinch_c + 273.15)
    #             / temperature_lift_c
    #     )
    #
    #     cop = max(cop, 1.01)
    #
    #     # Required condenser heat
    #     q_cond_required_kw = (q_evap_required_kw * cop / (cop - 1.0))
    #
    #     # Energy balance of the chiller:
    #     # Q_cond = Q_evap + P_comp
    #     #
    #     # Definition of COP:
    #     # COP = Q_cond / P_comp
    #     #
    #     # Therefore:
    #     # P_comp = Q_cond / COP
    #     #
    #     # Substitute P_comp into the energy balance:
    #     # Q_cond = Q_evap + Q_cond / COP
    #     #
    #     # Solving for Q_cond:
    #     # Q_cond = Q_evap * COP / (COP - 1)
    #
    #     # Compressor-power limitation
    #     q_cond_max_kw = chiller_max_p_comp_kw * cop
    #
    #     q_cond_required_kw = min(
    #         q_cond_required_kw,
    #         q_cond_max_kw
    #     )
    #
    #     # Required condenser-water mass flow
    #     mdot_cond_kg_per_s = (
    #             q_cond_required_kw
    #             / (4.18 * delta_t_cond_c)
    #     )
    #
    #
    #     return float(mdot_cond_kg_per_s)
    #
    #
    # GenericMapping(
    #     container=prosumer,
    #     initiator_id=hp_controller_index,
    #     initiator_column="t_evap_out_c",
    #     responder_id=dry_cooler_controller_index,
    #     responder_column="mdot_fluid_kg_per_s",
    #     order=1,
    #     no_chain=True,
    #     conversion_function=calculate_required_mdot_cond_kg_per_s
    # )
    #
    # # Connect the chiller condenser to the Dry Cooler.
    # FluidMixMapping(
    #     container=prosumer,
    #     initiator_id=chiller_controller_index,
    #     responder_id=dry_cooler_controller_index,
    #     order=0,
    #     no_chain=False
    # )
    #
    # # Write the chiller outlet temperature into the cold network.
    # nc_write_chiller_index = create_controlled_network_coupling(
    #     net_cold,
    #     chiller_pump_cold_index,
    #     element_name="circ_pump_pressure",
    #     input_columns=["t_flow_k"],
    #     level=nc_write_level_cold,
    #     order=6,
    #     name="nc_write_chiller_evaporator"
    # )
    #
    # # Überschreibt die bisherige Vorlauftemperatur mit der Chiller-Austrittstemperatur.
    # def overwrite_cold_supply_temperature(t_c):
    #     writer_controller = net_cold.controller.at[
    #         nc_write_chiller_index,
    #         "object"
    #     ]
    #
    #     temperature_column_index = (
    #         writer_controller.input_columns.index(
    #             "t_flow_k"
    #         )
    #     )
    #
    #     previous_temperature_k = np.nan_to_num(
    #         writer_controller.inputs[
    #             :,
    #             temperature_column_index
    #         ],
    #         nan=0.0
    #     )
    #
    #     target_temperature_k = (
    #             np.asarray(t_c) + 273.15
    #     )
    #
    #     return (
    #             target_temperature_k
    #             - previous_temperature_k
    #     )
    #
    # GenericEnergySystemMapping(
    #     container=prosumer,
    #     initiator_id=chiller_controller_index,
    #     initiator_column="t_evap_out_c",
    #     responder_net=net_cold,
    #     responder_id=nc_write_chiller_index,
    #     responder_column="t_flow_k",
    #     order=1,
    #     no_chain=True,
    #     conversion_function=overwrite_cold_supply_temperature
    # )

    return prosumer, hp_controller_index#, chiller_controller_index, dry_cooler_controller_index

def create_prosumer_dhw_system(
        data_source,
        time_res,
        start,
        end,
        net_hot
    ):

    prosumer = create_empty_prosumer_container(
        "dhw_system",
        # check_order=False
    )

    period = create_period(
        prosumer,
        time_res,
        start,
        end,
        "utc",
        "default"
    )


    solar_dhw_cp_index = create_controlled_const_profile(
        prosumer,
        input_columns=[
            "Solarthermal (kW)",
            "DHW(kg/s)",
            "t_dhw_cold_c",
            "t_dhw_hot_c"
        ],
        result_columns=[
            "solar_thermal_kw_cp",
            "dhw_mdot_kg_per_s_cp",
            "t_dhw_cold_c_cp",
            "t_dhw_hot_c_cp"
        ],
        data_source=data_source,
        period=period,
        level=cp_level,
        order=0
    )


    dhw_storage_controller_index = create_controlled_heat_storage(
        prosumer,
        q_capacity_kwh=2926.0,
        init_soc=0.5,
        period=period,
        name="dhw_heat_storage",
        level=dhw_prosumer_level,
        order=0
    )


    dhw_demand_controller_index = create_controlled_heat_demand(
        prosumer,
        period=period,
        name="dhw_demand_controller",
        level=dhw_prosumer_level,
        order=1
    )

    dhw_network_demand_controller_index = (
        create_controlled_heat_demand(
            prosumer,
            period=period,
            name="dhw_network_demand_controller",
            level=dhw_prosumer_level,
            order=2
        )
    )

    dhw_backup_element_index = get_element_index(
        net_hot,
        "heat_consumer",
        "dhw_backup_demand_coupling"
    )

    nc_read_dhw_backup_index = (
        create_controlled_network_coupling(
            net_hot,
            dhw_backup_element_index,
            element_name="heat_consumer",
            result_columns=[
                "t_from_k",
                "t_to_k",
                "mdot_from_kg_per_s"
            ],
            temp_fluid_map_output_idx=0,
            mdot_fluid_map_output_idx=2,
            level=nc_read_level_hot,
            order=0,
            name="nc_read_dhw_backup"
        )
    )



    nc_write_dhw_backup_index = (
        create_controlled_network_coupling(
            net_hot,
            dhw_backup_element_index,
            element_name="heat_consumer",
            input_columns=["qext_w"],
            level=nc_write_level_hot,
            order=1,
            name="nc_write_dhw_backup"
        )
    )

    # Solar thermal charges the storage.
    GenericMapping(
        container=prosumer,
        initiator_id=solar_dhw_cp_index,
        initiator_column="solar_thermal_kw_cp",
        responder_id=dhw_storage_controller_index,
        responder_column="q_received_kw",
        order=0
    )

    GenericMapping(
        container=prosumer,
        initiator_id=solar_dhw_cp_index,
        initiator_column=[
            "t_dhw_hot_c_cp",
            "t_dhw_cold_c_cp"
        ],
        responder_id=dhw_demand_controller_index,
        responder_column=[
            "t_feed_demand_c",
            "t_return_demand_c"
        ],
        order=0
    )


    GenericMapping(
        container=prosumer,
        initiator_id=solar_dhw_cp_index,
        initiator_column="dhw_mdot_kg_per_s_cp",
        responder_id=dhw_demand_controller_index,
        responder_column="q_demand_kw",
        order=1,
        conversion_function=lambda mdot: (
            mdot * 4.18 * (60.0 - 15.0)
        )
    )


    GenericMapping(
        container=prosumer,
        initiator_id=dhw_storage_controller_index,
        initiator_column="q_delivered_kw",
        responder_id=dhw_demand_controller_index,
        responder_column="q_received_kw",
        order=0,
        no_chain=False
    )

    GenericEnergySystemMapping(
        container=net_hot,
        initiator_id=dhw_demand_controller_index,
        initiator_column="q_uncovered_kw",
        responder_net=net_hot,
        responder_id=nc_write_dhw_backup_index,
        responder_column="qext_w",
        order=0,
        no_chain=True,
        conversion_function=lambda q_kw: (
            np.maximum(q_kw, 0.0) * 1000.0
        )
    )


    GenericMapping(
        container=prosumer,
        initiator_id=dhw_demand_controller_index,
        initiator_column="q_uncovered_kw",
        responder_id=dhw_network_demand_controller_index,
        responder_column="q_demand_kw",
        order=0,
        no_chain=True,
        conversion_function=lambda q_kw: (
            np.maximum(q_kw, 0.0)
        )
    )


    FluidMixEnergySystemMapping(
        container=net_hot,
        initiator_id=nc_read_dhw_backup_index,
        responder_net=prosumer,
        responder_id=dhw_network_demand_controller_index,
        order=0,
        no_chain=False
    )

    GenericEnergySystemMapping(
        container=net_hot,
        initiator_id=nc_read_dhw_backup_index,
        initiator_column="t_from_k",
        responder_net=prosumer,
        responder_id=dhw_network_demand_controller_index,
        responder_column="t_feed_demand_c",
        order=1,
        no_chain=False,
        conversion_function=lambda t_k: (
            np.asarray(t_k) - 273.15
        )
    )

    GenericEnergySystemMapping(
        container=net_hot,
        initiator_id=nc_read_dhw_backup_index,
        initiator_column="t_to_k",
        responder_net=prosumer,
        responder_id=dhw_network_demand_controller_index,
        responder_column="t_return_demand_c",
        order=2,
        no_chain=False,
        conversion_function=lambda t_k: (
            np.asarray(t_k) - 273.15
        )
    )

    return (
        prosumer,
        dhw_storage_controller_index,
        dhw_demand_controller_index,
        dhw_network_demand_controller_index
    )



def prepare_winter_pv_control_profiles(
    demand_data,
    normal_temperature_c=78.0,
    surplus_temperature_c=80.0,
    normal_hp_limit_kw=100.0,
    maximum_hp_limit_kw=350.0
):

    # Maximum allowed HP electrical power in every hour
    demand_data["hp_power_limit_kw"] = np.where(
        demand_data["pv_surplus_kw"] > 0.0,
        np.minimum(
            demand_data["hp_baseline_power_kw"]
            + demand_data["pv_surplus_kw"],
            maximum_hp_limit_kw
        ),
        normal_hp_limit_kw
    )

    # Hot-network supply-temperature target
    demand_data["hot_supply_target_c"] = np.where(
        demand_data["pv_surplus_kw"] > 0.0,
        surplus_temperature_c,
        normal_temperature_c
    )

    # pandapipes uses Kelvin
    demand_data["hot_supply_target_k"] = (
        demand_data["hot_supply_target_c"]
        + 273.15
    )

    return demand_data


# def add_winter_pv_controllers(
#         prosumer_prod,
#         net_hot,
#         data_source,
#         hp_controller_index
# ):
#
#     hp_element_index = (
#         prosumer_prod.controller.at[
#             hp_controller_index,
#             "object"
#         ].obj.element_index[0]
#     )
#
#     # Apply the hourly compressor-power limit.
#     hp_power_controller = ConstControl(
#         prosumer_prod,
#         element="heat_pump",
#         variable="max_p_comp_kw",
#         element_index=hp_element_index,
#         profile_name="hp_power_limit_kw",
#         data_source=data_source,
#         level=1,
#         order=0
#     )
#
#     # Find the physical circulation pump
#     # of the hot network.
#     hot_pump_index = get_element_index(
#         net_hot,
#         "circ_pump_pressure",
#         "pump_hp_coupling"
#     )
#
#     # Apply the hourly hot-network temperature:
#     # 78°C normally and 80°C during PV surplus.
#     temperature_controller = ConstControl(
#         net_hot,
#         element="circ_pump_pressure",
#         variable="t_flow_k",
#         element_index=hot_pump_index,
#         profile_name="hot_supply_target_k",
#         data_source=data_source,
#         level=1,
#         order=0
#     )
#
#     return hp_power_controller, temperature_controller


# def create_prosumer_cooling_demand(data_source, time_res, start, end, net_cold):
#
#     prosumer = create_empty_prosumer_container(
#         "cooling_demand_prosumer"
#     )
#
#     period = create_period(prosumer, time_res, start, end, "utc", "default")
#
#     # Read the hourly cooling demand from the Excel file.
#     cp_controller_index = create_controlled_const_profile(
#         prosumer,
#         input_columns=["Cooling demand (kW)"],
#         result_columns=["cooling_demand_kw_cp"],
#         data_source=data_source ,
#         period=period,
#         level=cp_level,
#         order=0
#     )
#
#     cooling_hx_index = get_element_index(
#         net_cold,
#         "heat_exchanger",
#         "cooling_demand_heat_exchanger"
#     )
#
#     # Write the cooling demand into the cold-network heat exchanger.
#     nc_write_cooling_index = create_controlled_network_coupling(
#         net_cold,
#         cooling_hx_index,
#         element_name="heat_exchanger",
#         input_columns=["qext_w"],
#         level=nc_write_level_cold,
#         order=0,
#         name="nc_write_cooling_demand"
#     )
#
#     GenericEnergySystemMapping(
#         container=prosumer,
#         initiator_id=cp_controller_index,
#         initiator_column="cooling_demand_kw_cp",
#         responder_net=net_cold,
#         responder_id=nc_write_cooling_index,
#         responder_column="qext_w",
#         order=0,
#         no_chain=True,
#         conversion_function=lambda q_kw: -q_kw * 1000
#     )
#
#     cooling_flow_index = get_element_index(
#         net_cold,
#         "flow_control",
#         "cooling_demand_flow_control"
#     )
#
#     # Controller that writes the required mass flow into the cold network.
#     nc_write_flow_index = create_controlled_network_coupling(
#         net_cold,
#         cooling_flow_index,
#         element_name="flow_control",
#         input_columns=["controlled_mdot_kg_per_s"],
#         level=nc_write_level_cold,
#         order=1,
#         name="nc_write_cooling_mass_flow"
#     )
#
#     # Convert cooling demand from kW to the required mass flow.
#     GenericEnergySystemMapping(
#         container=prosumer,
#         initiator_id=cp_controller_index,
#         initiator_column="cooling_demand_kw_cp",
#         responder_net=net_cold,
#         responder_id=nc_write_flow_index,
#         responder_column="controlled_mdot_kg_per_s",
#         order=1,
#         no_chain=True,
#         conversion_function=lambda q_kw: (
#             q_kw * 1000 / (4182 * 5.0)
#         )
#     )
#
#     return prosumer