import numpy as np

from .base import BaseMapping


def _add_mapping(initiator_controller, responder_controller, initiator_column, responder_column):
    init_col_idx = initiator_controller.result_columns.index(initiator_column)  # ToDo: add detailed error if IndexError
    resp_col_idx = responder_controller.input_columns.index(responder_column)
    responder_controller.inputs[:, resp_col_idx] = np.nan_to_num(
        responder_controller.inputs[:, resp_col_idx], nan=0.0) + initiator_controller.step_results[:, init_col_idx]


# ToDo: test subtract mapping and exception, do we need subtract (for el coupling)?
def _subtract_mapping(initiator_controller, responder_controller, initiator_column, responder_column):
    init_col_idx = initiator_controller.result_columns.index(initiator_column)
    resp_col_idx = responder_controller.input_columns.index(responder_column)
    responder_controller.inputs[:, resp_col_idx] = np.nan_to_num(
        responder_controller.inputs[:, resp_col_idx], nan=0.0) - initiator_controller.step_results[:, init_col_idx]


class GenericMapping(BaseMapping):
    """
    Generic mapping between controllers.

    Map the data in initiator_column in the step results of the initiator to the responder_column input
    columns of the responder.
    initiator_column and responder_column can be strings or lists of strings of the same length
    """

    def __init__(self, container=None, initiator_id=None, initiator_column=None, responder_id=None, responder_column=None,
                 order=None, application_operation="add", weights=None, no_chain=True, index=None):
        """
        Initializes the GenericWiseMapping.

        :param container: The prosumer object
        :param initiator_id: The initiating controller
        :param initiator_column: The column in the initiating controller (string or list of strings)
        :param responder_id: The responding controller
        :param responder_column: The column in the responding controller (string or list of strings)
        :param order: The order of mapping application
        :param application_operation: The operation to apply (default: "add")
        :param weights: Weights for the mapping
        :param index: The index of the mapping
        """
        super().__init__(container, initiator_id, initiator_column, responder_id, responder_column, order, no_chain, index)
        self.application_operation = application_operation
        self.weights = weights
        self.responder_net = container

    def __str__(self):
        return "ElementWiseMapping"

    def _validate(self):
        """
        Validates the generic mapping.
        """
        super()._validate()

    def map(self, initiator_controller, responder_controller):
        """
        Applies the element-wise mapping between the initiator and responder controllers.

        :param initiator_controller: The initiating controller
        :param responder_controller: The responding controller
        """
        if self.application_operation == 'add':
            # if initiator_controller.has_elements and initiator_controller._nb_elements >= 2:
            if isinstance(self.initiator_column, list):
                for initiator_column, responder_column in zip(self.initiator_column, self.responder_column):
                    _add_mapping(initiator_controller, responder_controller, initiator_column, responder_column)
            else:
                _add_mapping(initiator_controller, responder_controller, self.initiator_column, self.responder_column)
        elif self.application_operation == 'subtract':
            # if initiator_controller.has_elements and initiator_controller._nb_elements >= 2:
            if isinstance(self.initiator_column, list):
                for initiator_column, responder_column in zip(self.initiator_column, self.responder_column):
                    _subtract_mapping(initiator_controller, responder_controller, initiator_column, responder_column)
            else:
                _subtract_mapping(initiator_controller, responder_controller, self.initiator_column, self.responder_column)
        else:
            raise ValueError(f"Application operation '{self.application_operation}' not supported for GenericMapping"
                             f"from controller '{initiator_controller.name}' on column '{self.initiator_column}' "
                             f"to controller '{responder_controller.name}' on column '{self.responder_column}'")
