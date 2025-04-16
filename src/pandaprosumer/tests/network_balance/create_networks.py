import pandapipes
import pandapower
from pandapower.timeseries.output_writer import OutputWriter


def create_pandapipes_net_loop(ow_time_steps, mdot_dmd_kg_per_s, t_feed_prod_k, p_feed_prod_bar, p_return_prod_bar):
    t_amb_k = 293  # ToDo: make this depend on const profile ?
    net = pandapipes.create_empty_network(fluid="water", name='net_pipes')
    
    # Create output writer
    OutputWriter(net, ow_time_steps, output_path='./tmp', output_file_type='.csv',
                 log_variables=[
                     ('res_junction', 'p_bar'),
                     ('res_junction', 't_k'),
                     ('res_pipe', 'mdot_from_kg_per_s'),
                     ('res_heat_consumer', 'mdot_from_kg_per_s'),
                     ('res_circ_pump_pressure', 'mdot_from_kg_per_s')  # pandapipes 0.11
                 ])

    pandapipes.set_user_pf_options(net, ambient_temperature=t_amb_k, mode='all')
    
    # create junctions
    j0 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 2))
    j1 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 3))
    j2 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(1, 3))
    j3 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(1, 2))
    j4 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(1, 1))
    j5 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(1, 0))
    j6 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 0))
    j7 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 1))

    # create branch elements
    # alpha_w_per_m2k -> u_w_per_m2k = pandapipes 0.11
    pandapipes.create_pipes_from_parameters(net, from_junctions=[j0, j1, j2], to_junctions=[j1, j2, j3], length_km=0.1,
                                            diameter_m=0.05, alpha_w_per_m2k=10, u_w_per_m2k=10, text_k=t_amb_k)
    pandapipes.create_pipes_from_parameters(net, from_junctions=[j4, j5, j6], to_junctions=[j5, j6, j7], length_km=0.1,
                                            diameter_m=0.05, alpha_w_per_m2k=10, u_w_per_m2k=10, text_k=t_amb_k)

    pandapipes.create_circ_pump_const_pressure(net,
                                               j7,
                                               j0,
                                               p_flow_bar=p_feed_prod_bar[0],
                                               plift_bar=p_feed_prod_bar[0] - p_return_prod_bar[0],
                                               t_flow_k=t_feed_prod_k[0],
                                               _pandaprosumer_max_t_pump_feed_k=100 + 273.15,
                                               _pandaprosumer_min_t_pump_feed_k=20 + 273.15,
                                               _pandaprosumer_max_mdot_pump_kg_per_s=100)

    pandapipes.create_heat_consumer(net, from_junction=j3, to_junction=j4,
                                    qext_w=100e3, controlled_mdot_kg_per_s=mdot_dmd_kg_per_s[0],
                                    _pandaprosumer_max_mdot_dmd_kg_per_s=10000,
                                    _pandaprosumer_min_mdot_dmd_kg_per_s=0.05,
                                    _pandaprosumer_min_t_dmd_return_k=10 + 273.15)

    pandapipes.create_flow_control(net, from_junction=j3, to_junction=j4, controlled_mdot_kg_per_s=0.1,
                                   role="demander_bypass")

    return net


def create_pandapower_net(ow_time_steps):
    net = pandapower.create_empty_network(name='net_power')

    # Create output writer
    OutputWriter(net, ow_time_steps, output_path='./tmp', output_file_type='.csv',
                 log_variables=[
                     ('res_bus', 'vm_pu'),
                     ('res_line', 'loading_percent'),
                     ('res_load', 'p_mw'),
                     ('res_ext_grid', 'p_mw')
                 ])

    b0 = pandapower.create_bus(net, vn_kv=20.)
    b1 = pandapower.create_bus(net, vn_kv=20.)
    pandapower.create_line(net, from_bus=b0, to_bus=b1, length_km=2.5, std_type="NAYY 4x50 SE")
    pandapower.create_ext_grid(net, bus=b0)
    pandapower.create_load(net, bus=b1, p_mw=1.)

    return net
