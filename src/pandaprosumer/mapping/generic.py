import numpy as np

from .base import BaseMapping


def _apply_mapping(mapping, initiator_controller, responder_controller, initiator_column, responder_column,
                   conversion_function, sign):
    """Apply one Generic add/subtract mapping, idempotently across reapply re-fires.

    Within a time step, the convergence (reapply) loop can make the initiator
    finalize — and hence re-fire this mapping — several times
    (`_unapply_initiators` sets `applied = False` and pandapower re-runs the
    controller). The responder input must hold the LATEST contribution of each
    mapping, not the sum over passes: summing passes doubled the mapped power
    (exact ×2/×3 `qext_w` on a network write controller at schedule transitions
    in the Paris BET coupled run — a ~1000 kW phantom extraction). So each
    mapping's last contribution is remembered on the responder
    (`_generic_mapping_contribs`) and REPLACED on re-fire, while distinct
    mappings (several initiators feeding one input) still sum as 'add' intends.

    The book entry is stamped with the initiator's time step and only subtracted
    while that stamp matches: idempotence applies strictly WITHIN a time step
    (the reapply case), and cross-step behaviour is bit-identical to the
    historical `nan_to_num(previous) + mapped` regardless of where the responder
    resets its inputs. That matters because not every controller resets inputs
    in `finalize_control` — e.g. the Supervisor consumes and re-NaNs its own
    inputs inside `control_step`, and a stale (un-stamped) book entry would then
    be wrongly subtracted from the next step's fresh value.
    """
    init_col_idx = initiator_controller.result_columns.index(initiator_column)  # ToDo: add detailed error if IndexError
    resp_col_idx = responder_controller.input_columns.index(responder_column)
    initiator_result = initiator_controller.step_results[:, init_col_idx]
    mapped_value = sign * conversion_function(initiator_result)
    book = responder_controller.__dict__.setdefault("_generic_mapping_contribs", {})
    key = (id(mapping), responder_column)
    now = getattr(initiator_controller, "time", None)
    stamp, previous_contrib = book.get(key, (None, 0.))
    if stamp is None or now is None or stamp != now:
        previous_contrib = 0.
    previous_value = np.nan_to_num(responder_controller.inputs[:, resp_col_idx], nan=0.)
    responder_controller.inputs[:, resp_col_idx] = previous_value - previous_contrib + mapped_value
    book[key] = (now, mapped_value)


def _add_mapping(initiator_controller, responder_controller, initiator_column, responder_column,
                 conversion_function=lambda x: x, mapping=None):
    _apply_mapping(mapping, initiator_controller, responder_controller,
                   initiator_column, responder_column, conversion_function, sign=1.0)


# ToDo: test subtract mapping and exception, do we need subtract (for el coupling)?
def _subtract_mapping(initiator_controller, responder_controller, initiator_column, responder_column,
                      conversion_function=lambda x: x, mapping=None):
    _apply_mapping(mapping, initiator_controller, responder_controller,
                   initiator_column, responder_column, conversion_function, sign=-1.0)


class GenericMapping(BaseMapping):
    """
    Generic mapping between controllers.

    Map the data in initiator_column in the step results of the initiator to the responder_column input
    columns of the responder.
    initiator_column and responder_column can be strings or lists of strings with the same length
    """

    def __init__(self, container, initiator_id, initiator_column, responder_id, responder_column,
                 order=0, application_operation="add", no_chain=True, conversion_function=None, index=None):
        """
        Initializes the GenericWiseMapping.

        :param container: The container object (network, prosumer, energy system)
        :param initiator_id: int - The initiating controller
        :param initiator_column: The column in the initiating controller (string or list of strings)
        :param responder_id: The responding controller
        :param responder_column: The column in the responding controller (string or list of strings)
        :param order: The order of mapping application
        :param application_operation: The operation to apply ("add" or "subtract" - default: "add")
        :param no_chain: Boolean (default: True)
        :param conversion_function: function to apply to the mapping results (default if None: identity function)
        :param index: The index of the mapping
        """
        super().__init__(container, initiator_id, initiator_column, responder_id, responder_column, order, no_chain, index)
        self.application_operation = application_operation
        self.responder_net = container
        self.initiator = initiator_id
        self.responder = responder_id
        if conversion_function is None:
            self.conversion_function = lambda x : x
        else:
            self.conversion_function = conversion_function

    def __str__(self):
        return "GenericMapping"

    @property
    def name(self):
        return "GenericMapping"

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
        if self._check_order(): self.check_controllers_orders(initiator_controller, responder_controller)
        if self.application_operation == 'add':
            # if initiator_controller.has_elements and initiator_controller._nb_elements >= 2:
            if isinstance(self.initiator_column, list):
                for initiator_column, responder_column in zip(self.initiator_column, self.responder_column):
                    _add_mapping(initiator_controller, responder_controller,
                                 initiator_column, responder_column,
                                 self.conversion_function, mapping=self)
            else:
                _add_mapping(initiator_controller, responder_controller,
                             self.initiator_column, self.responder_column,
                             self.conversion_function, mapping=self)
        elif self.application_operation == 'subtract':
            # if initiator_controller.has_elements and initiator_controller._nb_elements >= 2:
            if isinstance(self.initiator_column, list):
                for initiator_column, responder_column in zip(self.initiator_column, self.responder_column):
                    _subtract_mapping(initiator_controller, responder_controller,
                                      initiator_column, responder_column,
                                      self.conversion_function, mapping=self)
            else:
                _subtract_mapping(initiator_controller, responder_controller,
                                  self.initiator_column, self.responder_column,
                                  self.conversion_function, mapping=self)
        else:
            raise ValueError(f"Application operation '{self.application_operation}' not supported for GenericMapping"
                             f"from controller '{initiator_controller.name}' on column '{self.initiator_column}' "
                             f"to controller '{responder_controller.name}' on column '{self.responder_column}'")
