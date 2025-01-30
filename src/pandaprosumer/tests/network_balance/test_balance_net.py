import pytest
from pandas._testing import assert_series_equal

from pandaprosumer2.energy_system.control.controller import NetControllerData
from pandaprosumer2.energy_system.control.controller.coupling.heat_demand_energy_system import \
    HeatDemandEnergySystemController
from pandaprosumer2.energy_system.control.controller.coupling.pandapipes_control import NetMassControl, NetTempControl
from pandaprosumer2.energy_system.control.controller.coupling.pandapipes_connector import \
    PandapipesConnectorController
from pandaprosumer2.energy_system.control.controller.coupling.pandapipes_interface import ReadPipeControl, \
    WritePipeControl, ReadPipeProdControl, WritePipeProdControl
from pandaprosumer2.energy_system.control.controller.coupling.pandapower_interface import LoadControl
from pandaprosumer2.energy_system.control.controller.data_model.pandapipes_connector import \
    PandapipesConnectorControllerData
from pandaprosumer2.energy_system.create_energy_system import create_empty_energy_system, add_net_to_energy_system, \
    add_pandaprosumer_to_energy_system
from pandaprosumer2.energy_system.timeseries.run_time_series_energy_system import \
    run_timeseries as run_timeseries_system
from pandaprosumer2.mapping import FluidMixEnergySystemMapping, GenericEnergySystemMapping
from tests.create_elements_controllers import *
from .create_networks import *
from .create_prosumers import *


class TestBalanceNet:
    """
    In this example, a more complex energy system is created with multiple prosumers and networks.
    """

    def test_balance_net(self):
        """
        Create 2 prosumers (1 producer and 1 heat consumer) connected to a district heating network

        # ToDo: What if HP cant provide required
        # ToDo: Managing many Heat demands
        # ToDo: Managing multiple Heat Production units
        # ToDo: Make it easier for the user of the library to create the energy system
        # ToDo: Define/use mdot_max_kg_per_s in the pandapipes network
        """

        # These values have to be set to run the pandapipes net for each demander and producer
        # ToDo: Read from a ConstProfile or define a strategy to read from the demanders' and producers' capacities
        tfeed_prod_k = [390]
        pfeed_prod_bar = [10]
        preturn_prod_bar = [5]
        # These are just for the initialisation of the network but will be overwritten on level 1
        mdot_dmd_kg_per_s = [5]
        # treturn_dmd_k = [10 + 273.15, 10 + 273.15]

        t_dmd_feed_target_c = [90]

        nb_repeat = 1
        nb_levels = 11
        level_write_dmd_to_pipe = [1 + i * nb_levels for i in range(nb_repeat)]
        level_balance_net = [2 + i * nb_levels for i in range(nb_repeat)]
        level_read_pipe_to_prod = [3 + i * nb_levels for i in range(nb_repeat)]
        level_prod = [4 + i * nb_levels for i in range(nb_repeat)]
        level_prod_fake_dmd = [4 + i * nb_levels for i in range(nb_repeat)]
        level_prod_write_to_pipe = [6 + i * nb_levels for i in range(nb_repeat)]
        level_balance_net_mass = [7 + i * nb_levels for i in range(nb_repeat)]
        level_read_pipe_to_dmd = [8 + i * nb_levels for i in range(nb_repeat)]
        level_fcc = [9 + i * nb_levels for i in range(nb_repeat)]
        level_dmd = [10 + i * nb_levels for i in range(nb_repeat)]
        load_level = [11 + i * nb_levels for i in range(nb_repeat)]

        # Create prosumers
        prosumer_prod1 = create_prosumer_prod(level_prod)
        prosumer_dmd1 = create_prosumer_dmd_hx(level_dmd)

        # Create Output writer time steps for networks
        ow_time_steps = pd.date_range(prosumer_prod1.period.iloc[0]["start"], prosumer_prod1.period.iloc[0]["end"],
                                      freq='%ss' % int(prosumer_prod1.period.iloc[0]["resolution_s"]),
                                      tz=prosumer_prod1.period.iloc[0]["timezone"])

        # Create pandapipes/power networks
        net_pipes = create_pandapipes_net_loop(ow_time_steps, mdot_dmd_kg_per_s, tfeed_prod_k, pfeed_prod_bar, preturn_prod_bar)
        net_power = create_pandapower_net(ow_time_steps)

        # Create an energy system and add the prosumers and networks to it
        energy_system = create_empty_energy_system()
        create_period(energy_system, prosumer_prod1.period.iloc[0]["resolution_s"],
                      prosumer_prod1.period.iloc[0]["start"],
                      prosumer_prod1.period.iloc[0]["end"],
                      timezone=prosumer_prod1.period.iloc[0]["timezone"],
                      name=prosumer_prod1.period.iloc[0]["name"])
        add_net_to_energy_system(energy_system, net_pipes, net_name='hydro')
        add_net_to_energy_system(energy_system, net_power, net_name='el')
        add_pandaprosumer_to_energy_system(energy_system, prosumer_prod1, pandaprosumer_name='prosumer_prod1')
        add_pandaprosumer_to_energy_system(energy_system, prosumer_dmd1, pandaprosumer_name='prosumer_dmd1')

        # Run the net once so the res_ tables are created
        # ToDo: Check the "initial run" parameter of the controllers
        pandapipes.pipeflow(net_pipes)

        NetTempControl(net=net_pipes, pump_id=0, tol=.5, level=level_balance_net, name='net_temp_control')
        NetMassControl(net=net_pipes, tol=1e-3, level=level_balance_net_mass, name='net_mass_control')

        # Create some DataClass controller data to refer to elements in the pandapipes networks
        heat_consumer_data = NetControllerData(input_columns=[],
                                               result_columns=[],
                                               element_name='heat_consumer',
                                               element_index=[0])

        heat_consumer_write_data = NetControllerData(input_columns=['tfeed_c', 'treturn_c', 'mdot_kg_per_s'],
                                                     result_columns=[],
                                                     element_name='heat_consumer',
                                                     element_index=[0])

        circ_pump_pressure_data = NetControllerData(input_columns=[],
                                                    result_columns=['t_c', 'tfeed_c', 'mdot_kg_per_s'],
                                                    element_name='circ_pump_pressure',
                                                    element_index=[0])

        circ_pump_pressure_write_data = NetControllerData(input_columns=[],
                                                          result_columns=[],
                                                          element_name='circ_pump_pressure',
                                                          element_index=[0])

        # On level 0, execute the Const profile controllers in all the prosumers

        # Create a new coupling controller in the demanders prosumer
        connector_controllerids = []
        for prosumer_dmd in [prosumer_dmd1]:
            pipes_connector_controller_data = PandapipesConnectorControllerData(period_index=0)
            PandapipesConnectorController(prosumer_dmd,
                                          pipes_connector_controller_data,
                                          order=0,
                                          level=level_fcc,
                                          name='pandapipes_connector_controller')
            connector_controllerid = prosumer_dmd.controller.index[-1]
            connector_controllerids.append(connector_controllerid)

        # Read the results from the feed pandapipes network
        # For each demander, create a controller in the feed pandapipes network
        # and a mapping between this controller and the Heat Exchanger controller in the corresponding prosumer
        # Read a data from an element in the net and map it to the input of a prosumer controller
        for prosumer_dmd, heat_consumer, connector_controllerid in zip([prosumer_dmd1],
                                                                       [heat_consumer_data],
                                                                       connector_controllerids):
            read_pipe_controller = ReadPipeControl(net_pipes, heat_consumer,
                                                   level=level_read_pipe_to_dmd, order=0,
                                                   name='read_pipe_controller')
            dmd_read_feed_control_index = read_pipe_controller.index

            # Create mapping between the pandapipes controller and this controller
            FluidMixEnergySystemMapping(container=net_pipes,
                                        initiator_id=dmd_read_feed_control_index,
                                        responder_net=prosumer_dmd,
                                        responder_id=connector_controllerid,
                                        order=0)
            hx_index = 1  # index of the HX controller that is connected to the DHN
            # Create mapping inside the prosumer between this connector controller and the (each) heat exchanger(s)
            FluidMixMapping(container=prosumer_dmd,
                            initiator_id=connector_controllerid,
                            responder_id=hx_index,
                            order=0)

        # Write the data from the prosumers to the net
        # For each demander, create a controller in the feed pandapipes network
        # and a mapping between this controller and the Pandapipes connector controller in the corresponding network
        for prosumer_dmd, heat_consumer, connector_controllerid in zip([prosumer_dmd1],
                                                                       [heat_consumer_write_data],
                                                                       connector_controllerids):
            WritePipeControl(net_pipes,
                             heat_consumer,
                             prosumer_dmd,
                             prosumer_dmd.controller.loc[connector_controllerid].object,
                             level=level_write_dmd_to_pipe,
                             name='dmd_write_pipe_control')

        # Reading the temperature at the junction and the mass flow in the ext_grid
        # at the input of the prosumer in the return network
        # For each producer, create a controller in the return pandapipes network
        # and 2 mappings between this controller and the Heat Demand controller in the corresponding prosumer
        for prosumer_prod, pump_data, pump_write_data, load_id in zip([prosumer_prod1],
                                                                      [circ_pump_pressure_data],
                                                                      [circ_pump_pressure_write_data],
                                                                      [0]):
            # Create a demand without period that act as a network connector controller in the prosumer
            heat_demand_index = init_hd_element(prosumer_prod)
            heat_demand_controller_data = HeatDemandControllerData(element_name='heat_demand',
                                                                   element_index=[heat_demand_index],
                                                                   period_index=0)  # FixMe: Adding a period to the controller is convenient for debuging
            heat_demand_controller = HeatDemandEnergySystemController(prosumer_prod,
                                                                      heat_demand_controller_data,
                                                                      order=0,
                                                                      level=level_prod_fake_dmd,
                                                                      name='heat_demand_connector_controller')
            hd_controller_index = heat_demand_controller.index

            hp_index = 1  # index of the HP controller that is connected to the DHN
            # Create a mapping between the HP and the HD that connect to the DHN
            FluidMixMapping(container=prosumer_prod,
                            initiator_id=hp_index,
                            responder_id=hd_controller_index,
                            order=0)

            prod_read_return_control = ReadPipeProdControl(net_pipes, pump_data, level=level_read_pipe_to_prod)
            prod_read_return_control_index = prod_read_return_control.index
            GenericEnergySystemMapping(container=net_pipes,
                                       initiator_id=prod_read_return_control_index,
                                       initiator_column="t_c",
                                       responder_net=prosumer_prod,
                                       responder_id=hd_controller_index,
                                       responder_column="t_return_demand_c",
                                       order=0)
            GenericEnergySystemMapping(container=net_pipes,
                                       initiator_id=prod_read_return_control_index,
                                       initiator_column="tfeed_c",
                                       responder_net=prosumer_prod,
                                       responder_id=hd_controller_index,
                                       responder_column="t_feed_demand_c",
                                       order=0)
            GenericEnergySystemMapping(container=net_pipes,
                                       initiator_id=prod_read_return_control_index,
                                       initiator_column="mdot_kg_per_s",
                                       responder_net=prosumer_prod,
                                       responder_id=hd_controller_index,
                                       responder_column="mdot_demand_kg_per_s",
                                       order=0)

            write_pipe_controller = WritePipeProdControl(net_pipes,
                                                         pump_write_data,
                                                         level=level_prod_write_to_pipe,
                                                         order=0,
                                                         name='prod_write_pipe_control')
            dmd_read_feed_control_index = write_pipe_controller.index

            # Create mapping between the pandapipes controller and this controller
            FluidMixEnergySystemMapping(container=prosumer_prod,
                                        initiator_id=hd_controller_index,
                                        responder_net=net_pipes,
                                        responder_id=dmd_read_feed_control_index,
                                        order=0)

            # Map the HP el consumption to the Pandapower net
            load_data = NetControllerData(element_index=[load_id],
                                          element_name='load',
                                          input_columns=['p_in_kw'],
                                          result_columns=[])
            load_control = LoadControl(net_power, load_data, level=load_level, name='load_control')
            load_control_index = load_control.index
            GenericEnergySystemMapping(container=prosumer_prod,
                                       initiator_id=hp_index,
                                       initiator_column="p_comp_kw",
                                       responder_net=net_power,
                                       responder_id=load_control_index,
                                       responder_column="p_in_kw",
                                       order=1)

        run_timeseries_system(energy_system, 0)

        print(prosumer_prod1.time_series.loc[0, 'data_source'].df)
        print(prosumer_dmd1.time_series.loc[0, 'data_source'].df)
        print(prosumer_dmd1.time_series.loc[1, 'data_source'].df)
        print(net_pipes.res_junction)
        print(net_pipes.res_junction.t_k - 273.15)
        print(net_pipes.res_pipe)
        print(net_power.res_bus)
        print(net_power.res_line)
        print(net_power.res_load)
        print(net_power.res_ext_grid)

        hp_res_df = prosumer_prod1.time_series.loc[0].data_source.df
        prod_hd_res_df = prosumer_prod1.time_series.loc[1].data_source.df
        hx_res_df = prosumer_dmd1.time_series.loc[0].data_source.df
        hd_res_df = prosumer_dmd1.time_series.loc[1].data_source.df
        fcc_ctrl = prosumer_dmd1.controller.loc[3].object
        fcc_ctrl_res = fcc_ctrl.time_series_finalization(prosumer_dmd1)
        fcc_res_df = [DFData(pd.DataFrame(entry, columns=fcc_ctrl.result_columns, index=fcc_ctrl.time_index)) for entry in fcc_ctrl_res][0].df
        jct_t_k_res_df = pd.read_csv('./tmp/res_junction/t_k.csv', sep=';')
        pipes_mdot_kg_per_s_res_df = pd.read_csv('./tmp/res_pipe/mdot_from_kg_per_s.csv', sep=';')
        hc_mdot_kg_per_s_res_df = pd.read_csv('./tmp/res_heat_consumer/mdot_from_kg_per_s.csv', sep=';')
        pump_mdot_kg_per_s_res_df = pd.read_csv('./tmp/res_circ_pump_pressure/mdot_from_kg_per_s.csv', sep=';')
        bus_vm_pu_res_df = pd.read_csv('./tmp/res_bus/vm_pu.csv', sep=';')
        line_loading_percent_res_df = pd.read_csv('./tmp/res_line/loading_percent.csv', sep=';')
        load_p_mw_res_df = pd.read_csv('./tmp/res_load/p_mw.csv', sep=';')
        ext_grid_p_mw_res_df = pd.read_csv('./tmp/res_ext_grid/p_mw.csv', sep=';')
        cp = prosumer_dmd1.fluid.get_heat_capacity((hx_res_df.t_2_out_c + hx_res_df.t_2_in_c)/2) / 1e3
        hx_q_2_kw = hx_res_df.mdot_2_kg_per_s * cp * (hx_res_df.t_2_out_c - hx_res_df.t_2_in_c)

        assert_series_equal(hx_q_2_kw, hd_res_df.q_received_kw, check_dtype=False, atol=.1, rtol=.1, check_names=False)
        assert_series_equal(hx_res_df.mdot_2_kg_per_s, hd_res_df.mdot_kg_per_s, check_dtype=False, atol=.01, rtol=.01, check_names=False)
        assert_series_equal(hx_res_df.t_2_out_c, hd_res_df.t_in_c, check_dtype=False, atol=.01, rtol=.01, check_names=False)
        assert_series_equal(hx_res_df.t_2_in_c, hd_res_df.t_out_c, check_dtype=False, atol=.01, rtol=.01, check_names=False)
        assert_series_equal(fcc_res_df.t_received_in_c, jct_t_k_res_df["3"]-CELSIUS_TO_K, check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(fcc_res_df.t_received_in_c, hx_res_df.t_1_in_c, check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(fcc_res_df.mdot_delivered_kg_per_s, hx_res_df.mdot_1_kg_per_s, check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(fcc_res_df.mdot_delivered_kg_per_s + fcc_res_df.mdot_bypass_kg_per_s, hc_mdot_kg_per_s_res_df["0"], check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(hp_res_df.t_cond_out_c, prod_hd_res_df.t_in_c, check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(hp_res_df.t_cond_in_c, prod_hd_res_df.t_out_c, check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(hp_res_df.mdot_cond_kg_per_s, prod_hd_res_df.mdot_kg_per_s, check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(prod_hd_res_df.t_in_c, jct_t_k_res_df["0"]-CELSIUS_TO_K, check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(prod_hd_res_df.mdot_kg_per_s, hc_mdot_kg_per_s_res_df["0"], check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(prod_hd_res_df.t_out_c, jct_t_k_res_df["7"]-CELSIUS_TO_K, check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)

        assert_series_equal(hp_res_df.p_comp_kw/1e3, load_p_mw_res_df["0"], check_dtype=False, atol=.01, check_names=False, check_index=False, check_freq=False)

        # FixMe: These tests are not passing in some cases because the return network is not balanced,
        #  need to reexecute prosumers
        assert_series_equal(prod_hd_res_df.mdot_kg_per_s, pump_mdot_kg_per_s_res_df["0"], check_dtype=False, atol=.01, rtol=.01, check_names=False, check_index=False, check_freq=False)
        fcc_t_return_out_c = (fcc_res_df.t_received_in_c * fcc_res_df.mdot_bypass_kg_per_s + hx_res_df.t_1_out_c * hx_res_df.mdot_1_kg_per_s) / (
                              fcc_res_df.mdot_bypass_kg_per_s + hx_res_df.mdot_1_kg_per_s)
        assert_series_equal(fcc_res_df.t_return_out_c, fcc_t_return_out_c, check_dtype=False, atol=.01, rtol=.01, check_names=False, check_index=False, check_freq=False)
        assert_series_equal(fcc_res_df.t_return_out_c, jct_t_k_res_df["4"]-273.15, check_dtype=False, atol=.01, rtol=.01, check_names=False, check_index=False, check_freq=False)
