import numpy as np

from .generic import GenericMapping


class GenericEnergySystemMapping(GenericMapping):
    """
    Generic mapping between controllers in different containers.

    Allows to map a variable to a responder controller in another container responder_net.
    """

    def __init__(self, container=None, initiator_id=None, initiator_column=None,
                 responder_net=None, responder_id=None, responder_column=None,
                 order=None, application_operation="add", weights=None, no_chain=True, index=None):
        """
        Initializes the GenericWiseMapping.

        :param container: The prosumer object
        :param initiator_id: The initiating controller
        :param initiator_column: The column in the initiating controller
        :param responder_id: The responding controller
        :param responder_column: The column in the responding controller
        :param order: The order of mapping application
        :param application_operation: The operation to apply (default: "add")
        :param weights: Weights for the mapping
        :param index: The index of the mapping
        """
        super().__init__(container, initiator_id, initiator_column, responder_id, responder_column,
                         order, application_operation, weights, no_chain, index)

        self.responder_net = responder_net

    def __str__(self):
        return "GenericEnergySystemMapping"

    def _validate(self):
        """
        Validates the generic mapping.
        """
        super()._validate()

    def map(self, initiator_controller, responder_controller_id):
        """
        Applies the element-wise mapping between the initiator and responder controllers.

        :param initiator_controller: The initiating controller
        :param responder_controller_id: The responding controller id in the mapping's responder_net
        """
        responder_controller = self.responder_net.controller.loc[responder_controller_id].object
        super().map(initiator_controller, responder_controller)
