import numpy as np
import pandapipes
from pandapower import control


class NetTempControl(control.basic_controller.Controller):
    """
        NetTempControl
    """

    def __init__(self, net, pump_id, tol=1, in_service=True, recycle=False, level=0, order=0, **kwargs):
        super().__init__(net, in_service=in_service, recycle=recycle, order=order, level=level,
                         initial_powerflow=True, **kwargs)

        self.pump_id = pump_id  # Id of the circ pump controlled by this controller, FixMe: manage multiple pumps ?
        self.tol = tol  # Tolerance on the temperature difference for convergence condition.
        self.max_mdot_dmd_kg_per_s = 10000  # Maximum mass flow rate through the consumers. The producer.s has to be able to provide this amount of heat (maximum massflow and temperature at every demanders)
        self.min_mdot_dmd_kg_per_s = 0.05  # Minimum mass flow rate through the consumers
        self.max_mdot_pump_kg_per_s = 100  # Maximum mass flow rate through the pump
        self.max_t_pump_feed_k = 100 + 273.15  # Maximum temperature supplied at the pump feed
        self.min_t_pump_feed_k = 20 + 273.15  # Minimum temperature supplied at the pump feed
        self.min_t_dmd_return_k = 10 + 273.15  # Minimum temperature returned by the consumers
        self.applied = False

    def level_reset(self, net):
        super().level_reset(net)
        self.applied = False
        # After executing the demander prosumers, the heat_consumer elements have a "_pandaprosumer_t_feed_c"
        # with the feed temperature that they require,
        # and "controlled_mdot_kg_per_s" and "qext_w" are set to the demand level
        assert not np.isnan(net.heat_consumer["_pandaprosumer_t_feed_c"]).any(), "The heat_consumer elements must have a '_pandaprosumer_t_feed_c' attribute"
        assert not np.isnan(net.heat_consumer["controlled_mdot_kg_per_s"]).any(), "The heat_consumer elements must have a 'controlled_mdot_kg_per_s' attribute"
        assert not np.isnan(net.heat_consumer["qext_w"]).any(), "The heat_consumer elements must have a 'qext_w' attribute"
        assert not np.isnan(net.circ_pump_pressure["t_flow_k"]).any(), "The circ_pump_pressure elements must have a 't_flow_k' attribute"
        tfeed_set_tab_c = [net.heat_consumer.loc[consumer, "_pandaprosumer_t_feed_c"] for consumer in net.heat_consumer.index]
        net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] = max(tfeed_set_tab_c) + 273.15 + 5  # self.tfeed_set_k + 5  # net.res_heat_consumer.t_from_k.max() + 10
        pandapipes.pipeflow(net)

    def control_step(self, net):
        super().control_step(net)
        converged = True
        # The temperature supplied by the pump must be higher than the maximum temperatures required by the consumers
        min_t_pump_feed_k = net.heat_consumer["_pandaprosumer_t_feed_c"].max() + 273.15
        # Need to iterate more than the maximum number of iterations max_iter. ToDo: converge faster
        # ToDo: In the general case, it is not possible that every consumer get the temperature that they require, what to do ?
        for i in range(10):
            if net.res_circ_pump_pressure.loc[self.pump_id, "t_to_k"] < min_t_pump_feed_k:
                net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] = min_t_pump_feed_k + 1
                converged = False
            elif net.res_circ_pump_pressure.loc[self.pump_id, "t_to_k"] > self.max_t_pump_feed_k:
                net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] = self.max_t_pump_feed_k - 1
                converged = False
            else:
                for consumer in net.heat_consumer.index:
                    t_consumer_from_k = net.res_heat_consumer.loc[consumer, "t_from_k"]
                    t_consumer_to_k = net.res_heat_consumer.loc[consumer, "t_to_k"]
                    mdot_consumer_kg_per_s = net.res_heat_consumer.loc[consumer, "mdot_from_kg_per_s"]
                    if mdot_consumer_kg_per_s < self.min_mdot_dmd_kg_per_s:
                        net.heat_consumer.loc[consumer, "controlled_mdot_kg_per_s"] = self.min_mdot_dmd_kg_per_s + .1
                        converged = False
                        break
                    elif mdot_consumer_kg_per_s > self.max_mdot_dmd_kg_per_s:
                        net.heat_consumer.loc[consumer, "controlled_mdot_kg_per_s"] = self.max_mdot_dmd_kg_per_s - .1
                        converged = False
                        break
                    # Convergence condition:
                    if abs(t_consumer_from_k - (net.heat_consumer.loc[consumer, "_pandaprosumer_t_feed_c"] + 273.15)) > self.tol:
                        if t_consumer_from_k < (net.heat_consumer.loc[consumer, "_pandaprosumer_t_feed_c"] + 273.15):
                            if mdot_consumer_kg_per_s < self.max_mdot_dmd_kg_per_s:
                                if net.res_circ_pump_pressure.loc[self.pump_id, "mdot_from_kg_per_s"] + .1 < self.max_mdot_pump_kg_per_s:
                                    # Raising the mass flow rate of the consumer reduce the heat losses in the pipes
                                    net.heat_consumer.loc[consumer, "controlled_mdot_kg_per_s"] += .1
                                    converged = False
                            else:
                                if net.res_circ_pump_pressure.loc[self.pump_id, "t_to_k"] + .1 < self.max_t_pump_feed_k:
                                    # Increasing the temperature of the pump feed increase the temperature at the consumers
                                    net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] += .1
                                    converged = False
                        else:
                            if mdot_consumer_kg_per_s - .2 > self.min_mdot_dmd_kg_per_s:
                                # Lowering the mass flow rate of the consumer increase the heat losses in the pipes
                                net.heat_consumer.loc[consumer, "controlled_mdot_kg_per_s"] -= .2
                                converged = False
                            else:
                                if net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] - .1 > min_t_pump_feed_k:
                                    net.circ_pump_pressure.loc[self.pump_id, "t_flow_k"] -= .1
                                    converged = False
                        pandapipes.pipeflow(net)
                        t_consumer_from_k = net.res_heat_consumer.loc[consumer, "t_from_k"]
                        t_consumer_to_k = net.res_heat_consumer.loc[consumer, "t_to_k"]
                        mdot_consumer_kg_per_s = net.res_heat_consumer.loc[consumer, "mdot_from_kg_per_s"]
                        if t_consumer_to_k < self.min_t_dmd_return_k:
                            # If the return temperature is too low, reduce the heat consumption of the consumer.
                            # Some demand will not be satisfied
                            # ToDo: If the temperature that the consumer recieves do not match "_pandaprosumer_t_feed_c",
                            # or the mass flow rate through the consumer is changed, the way the consumer react could change,
                            # so maybe should reexecute the consumer prosumer with the new values
                            net.heat_consumer.loc[consumer, "qext_w"] = mdot_consumer_kg_per_s * 4186 * (t_consumer_from_k - self.min_t_dmd_return_k) - 1
                            converged = False
                            pandapipes.pipeflow(net)
                pandapipes.pipeflow(net)
                if converged:
                    break

        self.applied = converged

        # self.t_flow_k -= net.res_heat_consumer.loc[self.consumerid, "t_from_k"] - self.min_t_pump_k
        # net.circ_pump_pressure.loc[self.pumpid, "t_flow_k"] = self.t_flow_k

    def is_converged(self, net):
        super().is_converged(net)
        # ToDo: Maybe should write a condition to check if the controller is applied rather than the is_applied boolean?
        if self.applied:
            print("NetTempControl Applied")
        return self.applied
        # tfeed_k = net.res_heat_consumer.loc[self.consumerid, "t_from_k"]
        # difference = 1 - self.tfeed_set_k / tfeed_k
        # converged = np.abs(difference) < self.tol
        # return converged


class NetMassControl(control.basic_controller.Controller):
    """
        NetMassControl
    """

    def __init__(self, net, tol=1e-3, in_service=True, recycle=False, level=0, order=0, **kwargs):
        super().__init__(net, in_service=in_service, recycle=recycle, order=order, level=level,
                         initial_powerflow=True, **kwargs)
        self.tol = tol

    def is_converged(self, net):
        super().is_converged(net)
        mdot_tot_prod_kg_per_s = net.circ_pump_pressure["_pandaprosumer_mdot_kg_per_s"].sum()
        delta_mdot_kg_per_s = abs(mdot_tot_prod_kg_per_s - net.heat_consumer.controlled_mdot_kg_per_s.sum())
        if delta_mdot_kg_per_s < self.tol:
            print("NetMassControl Applied")
        return delta_mdot_kg_per_s < self.tol

    def control_step(self, net):
        super().control_step(net)
        print("NetMassControl control_step")
        # The circ pump pressure elements have a "_pandaprosumer_mdot_kg_per_s" attribute with the mass flow rate
        # that they deliver to the network
        # This controller Reduce the mass flow rate of the consumers to match the mass flow rate
        # provided by the producers
        # FixMe: this should never be done ? The producer should be able to provide the maximal mass flow
        #  rate to every consumers
        # Else it would be need to re-execute the producer, as it will change the return temperature to the producer
        # ToDo: Detect if the producer cant provide the required power and raise an error
        #  (or re-execute the producer with the new return temperature ?)
        mdot_tot_prod_kg_per_s = net.circ_pump_pressure["_pandaprosumer_mdot_kg_per_s"].sum()
        assert mdot_tot_prod_kg_per_s > 1e-6, "Total mass flow rate provided by the producer must be greater than zero"
        net.heat_consumer.controlled_mdot_kg_per_s -= net.heat_consumer.controlled_mdot_kg_per_s - mdot_tot_prod_kg_per_s/len(net.heat_consumer)
