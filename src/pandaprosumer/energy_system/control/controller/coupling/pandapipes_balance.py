import numpy as np
import pandapipes
from pandapower import control

from pandaprosumer.controller import MappedController, BasicProsumerController
from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.mapping import FluidMixMapping


def getvalue(df, index, column_key, default_value=None):
    """
    Get from DF with default value
    """
    try:
        return df.loc[index, column_key]
    except KeyError:
        if default_value:
            return default_value
        else:
            raise KeyError(f"Index {index}; column {column_key} not found in DataFrame")


class PandapipesBalanceControl(BasicProsumerController):
    """
        NetTempControl
    """

    def __init__(self, net, pandapipes_connector_controllers, hc_element_indexes, connector_prosumers,
                 basic_prosumer_object=None, pump_id=0, tol=1, in_service=True, level=0, order=0, **kwargs):
        super().__init__(net, basic_prosumer_object=basic_prosumer_object, in_service=in_service,
                         order=order, level=level, initial_powerflow=True, **kwargs)

        self.pump_id = pump_id  # Id of the circ pump controlled by this controller, FixMe: manage multiple pumps ?
        self.tol = tol  # Tolerance on the temperature difference for convergence condition.
        self.pandapipes_connector_controllers = pandapipes_connector_controllers
        self.connector_prosumers = connector_prosumers
        self.hc_element_indexes = hc_element_indexes
        self.applied = False

    def add_new_hc_element(self, pandapipes_connector_ctrl, hc_element_index, connector_prosumer):
        self.pandapipes_connector_controllers.append(pandapipes_connector_ctrl)
        self.hc_element_indexes.append(hc_element_index)
        self.connector_prosumers.append(connector_prosumer)

    def level_reset(self, net):
        super().level_reset(net)
        self.applied = False
        self.first = False
        # After executing the demander prosumers, the heat_consumer elements have a "_pandaprosumer_t_feed_c"
        # with the feed temperature that they require,
        # and "controlled_mdot_kg_per_s" and "qext_w" are set to the demand level

    def control_step(self, net):
        super().control_step(net)

        for fcc, hc_element_index, connector_prosumer in zip(self.pandapipes_connector_controllers, self.hc_element_indexes, self.connector_prosumers):
            fcc.applied = False
            fcc.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                             FluidMixMapping.MASS_FLOW_KEY: np.nan}
            fcc._unapply_responders(connector_prosumer)
            t_feed_c, t_ret_c, mdot_kg_per_s = fcc.t_m_to_receive(connector_prosumer)
            # mdot_kg_per_s = sum(mdot_tab_kg_per_s)

            q_ext_w = mdot_kg_per_s * 4186 * (t_feed_c - t_ret_c)
            # min_mdot_kg_per_s = .1
            # if mdot_kg_per_s < min_mdot_kg_per_s:
            #     mdot_kg_per_s = min_mdot_kg_per_s
            # min_q_ext_w = 1
            # if q_ext_w < min_q_ext_w:
            #     q_ext_w = min_q_ext_w  # FixMe

            net.heat_consumer.loc[hc_element_index, "_pandaprosumer_t_feed_c"] = t_feed_c
            net.heat_consumer.loc[hc_element_index, "_pandaprosumer_t_ret_c"] = t_ret_c
            net.heat_consumer.loc[hc_element_index, "qext_w"] = q_ext_w
            net.heat_consumer.loc[hc_element_index, "controlled_mdot_kg_per_s"] = mdot_kg_per_s

        # print("PandapipesBalanceControl.control_step")
        # print(self.pandapipes_connector_controllers)
        # print(self.hc_element_indexes)
        # print(self.connector_prosumers)
        # print(net.heat_consumer)
        # print(net.circ_pump_pressure)

        if not self.first:
            assert not np.isnan(net.heat_consumer["_pandaprosumer_t_feed_c"]).any(), \
                "The heat_consumer elements must have a '_pandaprosumer_t_feed_c' attribute"
            assert not np.isnan(net.heat_consumer["controlled_mdot_kg_per_s"]).any(), \
                "The heat_consumer elements must have a 'controlled_mdot_kg_per_s' attribute"
            assert not np.isnan(net.heat_consumer["qext_w"]).any(), \
                "The heat_consumer elements must have a 'qext_w' attribute"
            assert not np.isnan(net.circ_pump_pressure["t_flow_k"]).any(), \
                "The circ_pump_pressure elements must have a 't_flow_k' attribute"

            q_ext_thresold_w = 5000
            tfeed_set_tab_c = [net.heat_consumer.loc[consumer, "_pandaprosumer_t_feed_c"] for consumer in net.heat_consumer.index if net.heat_consumer.loc[consumer, "qext_w"] > q_ext_thresold_w]
            if not tfeed_set_tab_c:
                tfeed_set_tab_c = [net.heat_consumer.loc[consumer, "_pandaprosumer_t_feed_c"] for consumer in
                                   net.heat_consumer.index]
            net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] = max(tfeed_set_tab_c) + CELSIUS_TO_K + 5  # self.tfeed_set_k + 5  # net.res_heat_consumer.t_from_k.max() + 10
            pandapipes.pipeflow(net)

        # self.first = True

        count = 0
        MAX_ITER = 50

        while not self.applied and count < MAX_ITER:
            count += 1
            converged = True
            # The temperature supplied by the pump must be higher than the maximum temperatures required by the consumers
            min_t_pump_feed_k = net.heat_consumer["_pandaprosumer_t_feed_c"].max() + CELSIUS_TO_K
            # Need to iterate more than the maximum number of iterations max_iter. ToDo: converge faster
            # ToDo: In the general case, it is not possible that every consumer get the temperature that they require, what to do ?
            for i in range(50):
                pandapipes.pipeflow(net)
                max_t_pump_feed_k = getvalue(net.circ_pump_pressure, self.pump_id, "_pandaprosumer_max_t_pump_feed_k",
                                             100 + CELSIUS_TO_K)
                max_mdot_pump_kg_per_s = getvalue(net.circ_pump_pressure, self.pump_id,
                                                  "_pandaprosumer_max_mdot_pump_kg_per_s", 100)

                if net.res_circ_pump_pressure.loc[self.pump_id, "t_to_k"] < min_t_pump_feed_k:
                    net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] = min_t_pump_feed_k + 1
                    converged = False
                elif net.res_circ_pump_pressure.loc[self.pump_id, "t_to_k"] > max_t_pump_feed_k:
                    net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] = max_t_pump_feed_k - 1
                    converged = False
                else:
                    for consumer in net.heat_consumer.index:
                        min_mdot_dmd_kg_per_s = getvalue(net.heat_consumer, consumer,
                                                         "_pandaprosumer_min_mdot_dmd_kg_per_s", .05)
                        max_mdot_dmd_kg_per_s = getvalue(net.heat_consumer, consumer,
                                                         "_pandaprosumer_max_mdot_dmd_kg_per_s", 10000)
                        min_t_dmd_return_k = getvalue(net.heat_consumer, consumer, "_pandaprosumer_min_t_dmd_return_k",
                                                      10 + CELSIUS_TO_K)
                        t_consumer_from_k = net.res_heat_consumer.loc[consumer, "t_from_k"]
                        t_consumer_to_k = net.res_heat_consumer.loc[consumer, "t_outlet_k"]
                        mdot_consumer_kg_per_s = net.res_flow_control.loc[
                            consumer, "mdot_from_kg_per_s"]  # FixMe: + net.res_heat_consumer.loc[consumer, "mdot_from_kg_per_s"]
                        if mdot_consumer_kg_per_s < min_mdot_dmd_kg_per_s:
                            net.flow_control.loc[consumer, "controlled_mdot_kg_per_s"] = min_mdot_dmd_kg_per_s + .1
                            converged = False
                            break
                        elif mdot_consumer_kg_per_s > max_mdot_dmd_kg_per_s:
                            net.flow_control.loc[consumer, "controlled_mdot_kg_per_s"] = max_mdot_dmd_kg_per_s - .1
                            converged = False
                            break
                        # Convergence condition:
                        if abs(t_consumer_from_k - (
                                net.heat_consumer.loc[consumer, "_pandaprosumer_t_feed_c"] + CELSIUS_TO_K)) > self.tol:
                            if t_consumer_from_k < (
                                    net.heat_consumer.loc[consumer, "_pandaprosumer_t_feed_c"] + CELSIUS_TO_K):
                                if mdot_consumer_kg_per_s < max_mdot_dmd_kg_per_s:
                                    if net.res_circ_pump_pressure.loc[
                                        self.pump_id, "mdot_from_kg_per_s"] + .1 < max_mdot_pump_kg_per_s:
                                        # Raising the mass flow rate of the consumer reduce the heat losses in the pipes
                                        net.flow_control.loc[consumer, "controlled_mdot_kg_per_s"] += .1
                                        converged = False
                                else:
                                    if net.res_circ_pump_pressure.loc[self.pump_id, "t_to_k"] + .1 < max_t_pump_feed_k:
                                        # Increasing the temperature of the pump feed increase the temperature at the consumers
                                        net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] += .1
                                        converged = False
                            else:
                                if net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] - .1 > min_t_pump_feed_k and (
                                        net.res_heat_consumer["t_from_k"] > net.heat_consumer[
                                    "_pandaprosumer_t_feed_c"]).all():
                                    net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] -= .1
                                    converged = False
                                else:
                                    if mdot_consumer_kg_per_s - .2 > min_mdot_dmd_kg_per_s:
                                        # Lowering the mass flow rate of the consumer increase the heat losses in the pipes
                                        net.flow_control.loc[consumer, "controlled_mdot_kg_per_s"] -= .2
                                        converged = False
                            pandapipes.pipeflow(net)
                            t_consumer_from_k = net.res_heat_consumer.loc[consumer, "t_from_k"]
                            t_consumer_to_k = net.res_heat_consumer.loc[consumer, "t_outlet_k"]
                            mdot_consumer_kg_per_s = net.res_heat_consumer.loc[consumer, "mdot_from_kg_per_s"]
                            if t_consumer_to_k < min_t_dmd_return_k:
                                # If the return temperature is too low, reduce the heat consumption of the consumer.
                                # Some demand will not be satisfied
                                # ToDo: If the temperature that the consumer recieves do not match "_pandaprosumer_t_feed_c",
                                # or the mass flow rate through the consumer is changed, the way the consumer react could change,
                                # so maybe should reexecute the consumer prosumer with the new values
                                net.heat_consumer.loc[consumer, "qext_w"] = mdot_consumer_kg_per_s * 4186 * (
                                            t_consumer_from_k - min_t_dmd_return_k) - 1
                                converged = False
                                pandapipes.pipeflow(net)
                    pandapipes.pipeflow(net)

                    if converged:
                        break

            self.applied = converged

        result_fluid_mix = []
        # for i, heat_consumer in net.res_heat_consumer.iterrows():
        for hc_index in self.hc_element_indexes:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: net.res_heat_consumer.loc[hc_index].t_from_k - CELSIUS_TO_K,
                                     FluidMixMapping.MASS_FLOW_KEY: net.res_heat_consumer.loc[hc_index].mdot_from_kg_per_s})

        result = np.array([[]])
        self.finalize(net, result, result_fluid_mix)
