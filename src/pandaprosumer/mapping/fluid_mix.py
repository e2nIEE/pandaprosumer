import numpy as np

from .base import BaseMapping


class FluidMixMapping(BaseMapping):
    """
    Fluid mapping between controllers.

    Each prosumer controller has special input_mass_flow_with_temp and result_mass_flow_with_temp attributes.

    input_mass_flow_with_temp is a dictionary containing the temperature and mass flow of the fluid

    result_mass_flow_with_temp is a list of dictionaries (to allow 1 to many mapping)
    """

    TEMPERATURE_KEY = 't_c'
    MASS_FLOW_KEY = 'mdot_kg_per_s'

    def __init__(self, container=None, initiator_id=None, responder_id=None,
                 order=None, application_operation="add", weights=None, no_chain=False, index=None):
        """
        Initializes the GenericWiseMapping.

        :param container: The prosumer object
        :param initiator_id: The initiating controller
        :param responder_id: The responding controller
        :param order: The order of mapping application
        :param application_operation: The operation to apply (default: "add")
        :param weights: Weights for the mapping
        :param index: The index of the mapping
        """
        super().__init__(container, initiator_id, None, responder_id, None, order, no_chain, index)
        self.application_operation = application_operation
        self.weights = weights
        self.responder_net = container
        self.order = order
        self.initiator = initiator_id
        self.responder = responder_id

    def __str__(self):
        return "FluidMixMapping"

    @property
    def name(self):
        return "FluidMixMapping"

    def _validate(self):
        """
        Validates the generic mapping.
        """
        super()._validate()

    def _check_order(self):
        return hasattr(self.responder_net, "check_order") and self.responder_net.check_order

    def map(self, initiator_controller, responder_controller):
        """
        Applies the element-wise mapping between the initiator and responder controllers.

        :param initiator_controller: The initiating controller
        :param responder_controller: The responding controller
        """
        # FixMe: Will break if the order are not 0, 1, 2, ...
        if self._check_order(): self.check_controllers_orders(initiator_controller, responder_controller)

        initiator_mapped_results = initiator_controller.result_mass_flow_with_temp[self.order]
        initiator_temperature = initiator_mapped_results[self.TEMPERATURE_KEY]
        initiator_mass_flow = initiator_mapped_results[self.MASS_FLOW_KEY]

        if (np.isnan(responder_controller.input_mass_flow_with_temp[self.TEMPERATURE_KEY]) or
                np.isnan(responder_controller.input_mass_flow_with_temp[self.MASS_FLOW_KEY])):
            mix_mass_flow = initiator_mass_flow
            mix_temp = initiator_temperature
        else:
            responder_temperature = responder_controller.input_mass_flow_with_temp[self.TEMPERATURE_KEY]
            responder_mass_flow = responder_controller.input_mass_flow_with_temp[self.MASS_FLOW_KEY]
            mix_mass_flow = responder_mass_flow + initiator_mass_flow
            if mix_mass_flow == 0:
                # If it happens that both mass flow are null, the temperature value doesn't matter
                mix_temp = (responder_temperature + initiator_temperature) / 2
            else:
                mix_temp = (responder_temperature * responder_mass_flow + initiator_temperature * initiator_mass_flow) / mix_mass_flow

        # mix_mass_flow = initiator_mass_flow
        # mix_temp = initiator_temperature
        #
        mix_res = {self.TEMPERATURE_KEY: mix_temp, self.MASS_FLOW_KEY: mix_mass_flow}
        # x = responder_controller.inputs[0].tolist()
        # x[resp_col_idx] = mix_res
        responder_controller.input_mass_flow_with_temp = mix_res
