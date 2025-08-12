import numpy as np

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K


class NetworkCouplingControl(BasicProsumerController):
    """
    NetworkCouplingControl
    Can be used to create a coupling between a prosumer and a pandapipes or pandapower network
    """

    @classmethod
    def name(cls):
        return "network_coupling_controller"

    def __init__(self, net, load_ctrl_object, in_service=True, order=0, level=0,
                 temp_fluid_map_input_col=None, mdot_fluid_map_input_col=None,
                 temp_fluid_map_output_idx=None, mdot_fluid_map_output_idx=None, **kwargs):
        super().__init__(net, load_ctrl_object, in_service=in_service, order=order, level=level,
                         temp_fluid_map_idx=None, mdot_fluid_map_idx=None, **kwargs)
        self.mdot_required_kg_per_s = 'mdot_from_kg_per_s'
        self.tfeed_required_k = 't_to_k'
        self.treturn_required_k = 't_from_k'
        self.temp_fluid_map_input_col = temp_fluid_map_input_col
        self.mdot_fluid_map_input_col = mdot_fluid_map_input_col
        self.temp_fluid_map_output_idx = temp_fluid_map_output_idx
        self.mdot_fluid_map_output_idx = mdot_fluid_map_output_idx
        if self.temp_fluid_map_output_idx is not None and self.mdot_fluid_map_output_idx is not None:
            assert len(self.result_columns) > temp_fluid_map_output_idx
            assert len(self.result_columns) > mdot_fluid_map_output_idx

    def _t_m_to_receive_init(self, net):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s.

        :param net: The network object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        # FixMe
        tfeed_required_c = 75  # np.array(net["res_" + self.element_name].loc[self.element_index, self.tfeed_required_k]) - CELSIUS_TO_K
        treturn_required_c =  50  # np.array(net["res_" + self.element_name].loc[self.element_index, self.treturn_required_k]) - CELSIUS_TO_K
        mdot_required_kg_per_s =  3  # np.array(net["res_" + self.element_name].loc[self.element_index, self.mdot_required_kg_per_s])
        return tfeed_required_c, treturn_required_c, mdot_required_kg_per_s

    def control_step(self, net):
        super().control_step(net)
        # EnergySystem Generic mappings inputs and outputs
        # Replace NaNs with 0
        clean_inputs = np.nan_to_num(self.inputs, nan=0.)  # FixMe: should avoid nan case
        net[self.element_name].loc[self.element_index, self.input_columns] = clean_inputs

        results = np.array(net["res_" + self.element_name].loc[self.element_index, self.result_columns])

        # EnergySystem FluidMix mapping inputs from prosumers
        if self.temp_fluid_map_input_col is not None and self.mdot_fluid_map_input_col is not None:
            if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
                if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]):
                    t_in_k = self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] + CELSIUS_TO_K
                    mdot_in_kg_per_s = self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
                    net[self.element_name].loc[self.element_index, self.temp_fluid_map_input_col] = t_in_k
                    net[self.element_name].loc[self.element_index, self.mdot_fluid_map_input_col] = mdot_in_kg_per_s

        # EnergySystem FluidMix mapping outputs to prosumers
        if self.temp_fluid_map_output_idx is not None and self.mdot_fluid_map_output_idx is not None:
            result_fluid_mix = [
                {FluidMixMapping.TEMPERATURE_KEY: results[0][self.temp_fluid_map_output_idx] - CELSIUS_TO_K,
                 FluidMixMapping.MASS_FLOW_KEY: results[0][self.mdot_fluid_map_output_idx]}]
            self.finalize(net, results, result_fluid_mix)
        else:
            self.finalize(net, results)
        self.applied = True
