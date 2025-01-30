from pandaprosumer.controller.mapped import MappedController
import numpy as np
import pandas as pd
from pandaprosumer.mapping import FluidMixMapping, GenericEnergySystemMapping


class ReadPipeControl(MappedController):
    """
        ReadPipeControl

        Read the temperature at the first element and the mass flow at the second element in the net.
        Write these data to the output for mapping
    """

    @classmethod
    def name(cls):
        return "read_pipe_controller"

    def __init__(self, net, heat_consumer_data, in_service=True,
                 recycle=False, order=0, level=0, **kwargs):
        super().__init__(net, heat_consumer_data, in_service=in_service, order=order, level=level, **kwargs)

    def control_step(self, net):
        super().control_step(net)

        t_c = net['res_'+self.element_name].loc[self.element_index[0], "t_from_k"] - 273.15
        mdot_kg_per_s = net['res_'+self.element_name].loc[self.element_index[0], "mdot_from_kg_per_s"]

        result = np.array([[t_c, mdot_kg_per_s]])
        result_fluid_mix = [{FluidMixMapping.TEMPERATURE_KEY: t_c, FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s}]

        self.finalize(net, result, result_fluid_mix)

        self.applied = True


class ReadPipeProdControl(MappedController):
    """
        ReadPipeProdControl

        Read the temperature at the first element and the mass flow at the second element in the net.
        Write these data to the output for mapping
    """

    @classmethod
    def name(cls):
        return "read_pipe_controller"

    def __init__(self, net, heat_producer_data, in_service=True,
                 recycle=False, order=0, level=0, **kwargs):
        super().__init__(net, heat_producer_data, in_service=in_service, order=order, level=level, **kwargs)

    def control_step(self, net):
        super().control_step(net)

        ret_jct_id = net[self.element_name]['return_junction'].values[0]
        t_c = net.res_junction.loc[ret_jct_id]['t_k'] - 273.15
        feed_jct_id = net[self.element_name]['flow_junction'].values[0]
        tflow_c = net.res_junction.loc[feed_jct_id]['t_k'] - 273.15
        mdot_kg_per_s = net['res_'+self.element_name].loc[self.element_index, "mdot_from_kg_per_s"].values[0]

        result = np.array([[t_c, tflow_c, mdot_kg_per_s]])

        self.finalize(net, result)

        self.applied = True


class WritePipeControl(MappedController):
    """
        WritePipeControl

        Take to inputs 'treturn_c' and 'mdot_kg_per_s' and write them to the net
    """

    @classmethod
    def name(cls):
        return "write_pipe_controller"

    def __init__(self, net, heat_consumer_data, connector_prosumer, connector_controller, in_service=True,
                 recycle=False, order=0, level=0, **kwargs):
        super().__init__(net, heat_consumer_data, in_service=in_service, order=order, level=level, **kwargs)
        self.connector_prosumer = connector_prosumer
        self.connector_controller = connector_controller

    def control_step(self, net):
        super().control_step(net)

        # FixMe: Should create mapping rather than passing a reference to the prosumer controller
        t_feed_c, t_ret_c, mdot_tab_kg_per_s = self.connector_controller.t_m_to_receive(self.connector_prosumer)
        mdot_kg_per_s = sum(mdot_tab_kg_per_s)

        q_ext_w = mdot_kg_per_s * 4186 * (t_feed_c - t_ret_c)
        min_mdot_kg_per_s = .1
        if mdot_kg_per_s < min_mdot_kg_per_s:
            mdot_kg_per_s = min_mdot_kg_per_s
        min_q_ext_w = 1000
        if q_ext_w < min_q_ext_w:
            q_ext_w = min_q_ext_w  # FixMe

        # ToDo: Set all the network attributes keys as constants
        net[self.element_name].loc[self.element_index, "_pandaprosumer_t_feed_c"] = t_feed_c
        net[self.element_name].loc[self.element_index, "_pandaprosumer_t_ret_c"] = t_ret_c
        net[self.element_name].loc[self.element_index, "qext_w"] = q_ext_w
        net[self.element_name].loc[self.element_index, "controlled_mdot_kg_per_s"] = mdot_kg_per_s

        result = []

        self.finalize(net, result)

        self.applied = True


class WritePipeProdControl(MappedController):
    """
        WritePipeProdControl

        Take to inputs 't_feed_c' and 'mdot_kg_per_s' and write them to the net
    """

    @classmethod
    def name(cls):
        return "write_pipe_controller"

    def __init__(self, net, heat_producer_data, in_service=True,
                 recycle=False, order=0, level=0, **kwargs):
        super().__init__(net, heat_producer_data, in_service=in_service, order=order, level=level, **kwargs)

    @property
    def _t_feed_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        else:
            return np.nan

    @property
    def _mdot_kg_per_s(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        else:
            return np.nan

    def control_step(self, net):
        super().control_step(net)

        # FixMe: Set the mass flow through the cir_pump_pressure ?
        net[self.element_name].loc[self.element_index, "t_flow_k"] = self._t_feed_c + 273.15
        net[self.element_name].loc[self.element_index, "_pandaprosumer_mdot_kg_per_s"] = self._mdot_kg_per_s

        result = []

        self.finalize(net, result)

        self.applied = True
