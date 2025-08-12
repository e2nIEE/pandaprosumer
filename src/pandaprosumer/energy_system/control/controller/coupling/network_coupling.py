import numpy as np
from pandaprosumer.controller.mapped import MappedController
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K


class NetworkCouplingControl(MappedController):
    """
    NetworkCouplingControl
    Mapped input: user defined
    Control step: Write the power to the element 'p_mw' property (converting kW to MW)
    Can be used to create a coupling between a prosumer and a pandapipes or pandapower network
    """

    @classmethod
    def name(cls):
        return "network_coupling_controller"

    def __init__(self, net, load_ctrl_object, in_service=True,
                 recycle=False, order=0, level=0,
                 temp_fluid_map_input_col=None, mdot_fluid_map_input_col=None,
                 temp_fluid_map_output_idx=None, mdot_fluid_map_output_idx=None, **kwargs):
        super().__init__(net, load_ctrl_object, in_service=in_service, order=order, level=level,
                         temp_fluid_map_idx=None, mdot_fluid_map_idx=None, **kwargs)
        self.temp_fluid_map_input_col = temp_fluid_map_input_col
        self.mdot_fluid_map_input_col = mdot_fluid_map_input_col
        self.temp_fluid_map_output_idx = temp_fluid_map_output_idx
        self.mdot_fluid_map_output_idx = mdot_fluid_map_output_idx
        if self.temp_fluid_map_output_idx is not None and self.mdot_fluid_map_output_idx is not None:
            assert len(self.result_columns) > temp_fluid_map_output_idx
            assert len(self.result_columns) > mdot_fluid_map_output_idx

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
