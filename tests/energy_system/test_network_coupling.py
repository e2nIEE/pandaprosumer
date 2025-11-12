import pandapower
from pandapower.timeseries import OutputWriter

from pandaprosumer.create_controlled import *
from pandaprosumer.energy_system import create_empty_energy_system, add_net_to_energy_system, \
    add_pandaprosumer_to_energy_system
from pandaprosumer.energy_system.control.controller.coupling.network_coupling import NetworkCouplingControl
from pandaprosumer.energy_system.control.controller.data_model.network_coupling import NetworkCouplingData
from pandaprosumer.energy_system.timeseries.run_time_series_energy_system import \
    run_timeseries as run_time_series_system
from pandaprosumer.mapping import GenericMapping, FluidMixMapping, FluidMixEnergySystemMapping, \
    GenericEnergySystemMapping
from tests.data_sources import define_and_get_period_and_data_source


def _create_pipes_network():
    net = pandapipes.create_empty_network(fluid="water", name='net_pipes')
    t_amb_k = 293
    pandapipes.set_user_pf_options(net, ambient_temperature=t_amb_k, mode='bidirectional')

    # Create junctions
    j0 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 1))
    j1 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(2, 1))
    j2 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(2, 0))
    j3 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 0))

    # Create branched elements
    pandapipes.create_pipes_from_parameters(net, from_junctions=[j0, j2], to_junctions=[j1, j3], length_km=0.1,
                                            diameter_m=0.05, u_w_per_m2k=10, text_k=t_amb_k)

    pandapipes.create_circ_pump_const_pressure(net,
                                               j3,
                                               j0,
                                               p_flow_bar=10,
                                               plift_bar=5,
                                               t_flow_k=350)

    pandapipes.create_heat_consumer(net, from_junction=j1, to_junction=j2,
                                    qext_w=100e3, controlled_mdot_kg_per_s=3)

    return net


def _create_power_network():
    net = pandapower.create_empty_network(name='net_power')
    b1 = pandapower.create_bus(net, vn_kv=20.)
    b2 = pandapower.create_bus(net, vn_kv=20.)
    pandapower.create_line(net, from_bus=b1, to_bus=b2, length_km=2.5, std_type="NAYY 4x50 SE")
    pandapower.create_ext_grid(net, bus=b1)
    pandapower.create_load(net, bus=b2, p_mw=1.)
    return net


def _create_prosumer_prod(hp_level, RESOL_S):
    prosumer = create_empty_prosumer_container(name='prosumer_prod', check_order=False)
    period, data_source = define_and_get_period_and_data_source(prosumer, resol=RESOL_S)

    cp_input_columns = ["Tin,evap"]
    cp_result_columns = ["Tin,evap"]

    hp_params = {'carnot_efficiency': 0.5,
                 'pinch_c': 5,
                 'delta_t_evap_c': 8,
                 'max_p_comp_kw': 1000e3}

    cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                          data_source, period, 0, 0)

    hp_controller_index = create_controlled_heat_pump(prosumer, period=period, name='hp_controller',
                                                      level=hp_level, order=0, **hp_params)
    GenericMapping(container=prosumer,
                   initiator_id=cp_controller_index,
                   initiator_column="Tin,evap",
                   responder_id=hp_controller_index,
                   responder_column="t_evap_in_c",
                   order=0)

    return prosumer


def _create_prosumer_dmd(level, RESOL_S):
    prosumer = create_empty_prosumer_container(name='prosumer_dmd', check_order=False)
    period, data_source = define_and_get_period_and_data_source(prosumer, resol=RESOL_S)

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
                                                          data_source, period, 0, 0)

    hx_controller_index = create_controlled_heat_exchanger(prosumer, period=period, name='hx_controller',
                                                           level=level, order=0, **hx_params)
    hd_controller_index = create_controlled_heat_demand(prosumer, period=period, name='hd_controller',
                                                        level=level, order=1, **hd_params)

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


def _create_energy_system(nets, prosumers, name="test_energy_system"):
    energy_system = create_empty_energy_system(name=name)
    sample_prosumer_period = prosumers[0].period
    create_period(energy_system, sample_prosumer_period.iloc[0]["resolution_s"],
                  sample_prosumer_period.iloc[0]["start"],
                  sample_prosumer_period.iloc[0]["end"],
                  timezone=sample_prosumer_period.iloc[0]["timezone"],
                  name=sample_prosumer_period.iloc[0]["name"])
    for net in nets:
        add_net_to_energy_system(energy_system, net, net_name=net.name)
    for prosumer in prosumers:
        add_pandaprosumer_to_energy_system(energy_system, prosumer, pandaprosumer_name=prosumer.name)
    return energy_system


class TestNetworkCoupling:
    """
    In this example, an energy system is created with multiple prosumers and couplings with networks.
    """

    def test_create_energy_system(self):
        """
        Create 2 prosumers (1 producer and 1 heat consumer) and a district heating network in an energy system
        """
        net_pipes = _create_pipes_network()
        net_power = _create_power_network()
        RESOL_S = 3600
        prosumer_prod = _create_prosumer_prod(hp_level=2, RESOL_S=RESOL_S)
        prosumer_dmd = _create_prosumer_dmd(level=3, RESOL_S=RESOL_S)
        energy_system = _create_energy_system([net_pipes, net_power], [prosumer_prod, prosumer_dmd],
                                              name="test_energy_system")
        assert energy_system.name == "test_energy_system"
        assert len(energy_system.nets) == 2
        assert len(energy_system.prosumer) == 2
        assert len(energy_system.controller) == 0
        assert 'net_pipes' in energy_system.nets
        assert 'net_power' in energy_system.nets
        assert 'prosumer_prod' in energy_system.prosumer
        assert 'prosumer_dmd' in energy_system.prosumer

    def test_create_coupling(self):
        """
        Create 2 prosumers (1 producer and 1 heat consumer) connected to a district heating network
        """
        net = _create_pipes_network()
        net_power = _create_power_network()
        RESOL_S = 3600
        prosumer_prod = _create_prosumer_prod(hp_level=2, RESOL_S=RESOL_S)
        prosumer_dmd = _create_prosumer_dmd(level=3, RESOL_S=RESOL_S)
        energy_system = _create_energy_system([net, net_power], [prosumer_prod, prosumer_dmd])

        sample_prosumer_period = prosumer_prod.period
        ow_time_steps = pd.date_range(sample_prosumer_period.iloc[0]["start"], sample_prosumer_period.iloc[0]["end"],
                                      freq='%ss' % int(sample_prosumer_period.iloc[0]["resolution_s"]),
                                      tz=sample_prosumer_period.iloc[0]["timezone"])
        OutputWriter(net, ow_time_steps, log_variables=[])  # FixMe: should not be needed in last version of ppipes
        OutputWriter(net_power, ow_time_steps, log_variables=[])

        pump_elmt_index = 0
        consumer_elmt_index = 0

        # nc_read_pump_index = create_controlled_network_coupling(net,
        #                                                         pump_elmt_index,
        #                                                         element_name='circ_pump_pressure',
        #                                                         result_columns=['t_from_k', 't_to_k',
        #                                                                         'mdot_from_kg_per_s'],
        #                                                         level=1,
        #                                                         order=0)

        nc_write_pump_index = create_controlled_network_coupling(net,
                                                                 pump_elmt_index,
                                                                 element_name='circ_pump_pressure',
                                                                 temp_fluid_map_input_col=['t_flow_k'],
                                                                 mdot_fluid_map_input_col=['mdot_flow_kg_per_s'],
                                                                 # FixMe: doesn't exist in circ_pump_pressure
                                                                 level=4,
                                                                 order=0)

        nc_read_dmd_index = create_controlled_network_coupling(net,
                                                               consumer_elmt_index,
                                                               element_name='heat_consumer',
                                                               result_columns=['t_from_k', 't_to_k',
                                                                               'mdot_from_kg_per_s'],
                                                               temp_fluid_map_output_idx=0,
                                                               mdot_fluid_map_output_idx=2,
                                                               level=1, order=2)

        nc_write_dmd_index = create_controlled_network_coupling(net,
                                                                consumer_elmt_index,
                                                                element_name='heat_consumer',
                                                                input_columns=['qext_w', 'controlled_mdot_kg_per_s'],
                                                                level=4, order=2)

        # assert nc_read_pump_index == 0
        # assert nc_write_pump_index == 1
        # assert nc_read_dmd_index == 2
        # assert nc_write_dmd_index == 3
        # assert len(net.controller) == 4
        #
        # assert len(prosumer_prod.mapping) == 1
        # assert len(prosumer_dmd.mapping) == 2

        hp_ctrl_index = 1
        hx_ctrl_index = 1

        # FluidMixEnergySystemMapping(container=net,
        #                             initiator_id=nc_read_pump_index,
        #                             responder_net=prosumer_dmd,
        #                             responder_id=hp_ctrl_index,
        #                             order=0,
        #                             no_chain=True)

        FluidMixEnergySystemMapping(container=prosumer_prod,
                                    initiator_id=hp_ctrl_index,
                                    responder_net=net,
                                    responder_id=nc_write_pump_index,
                                    order=0,
                                    no_chain=False)

        FluidMixEnergySystemMapping(container=net,
                                    initiator_id=nc_read_dmd_index,
                                    responder_net=prosumer_dmd,
                                    responder_id=hx_ctrl_index,
                                    order=0,
                                    no_chain=True)

        GenericEnergySystemMapping(container=prosumer_dmd,
                                   initiator_id=hx_ctrl_index,
                                   initiator_column='q_exchanged_kw',
                                   responder_net=net,
                                   responder_id=nc_write_dmd_index,
                                   responder_column='qext_w',
                                   order=0,
                                   conversion_function=lambda q: q * 1000)

        GenericEnergySystemMapping(container=prosumer_dmd,
                                   initiator_id=hx_ctrl_index,
                                   initiator_column='mdot_1_kg_per_s',
                                   responder_net=net,
                                   responder_id=nc_write_dmd_index,
                                   responder_column='controlled_mdot_kg_per_s',
                                   order=1)

        load_elmt_index = 0

        nc_write_load_index = create_controlled_network_coupling(net_power,
                                                                 load_elmt_index,
                                                                 element_name='load',
                                                                 input_columns=['p_mw'],
                                                                 level=5, order=0)

        GenericEnergySystemMapping(container=prosumer_prod,
                                   initiator_id=hp_ctrl_index,
                                   initiator_column='p_comp_kw',
                                   responder_net=net_power,
                                   responder_id=nc_write_load_index,
                                   responder_column='p_mw',
                                   order=0,
                                   conversion_function=lambda p: p / 1000)

        # assert len(net.mapping) == 2
        # assert len(prosumer_prod.mapping) == 2
        # assert len(prosumer_dmd.mapping) == 3

        period = 0
        run_time_series_system(energy_system,
                               period_index=period, continue_on_divergence=False, verbose=True,
                               transient=True, dt=RESOL_S)
