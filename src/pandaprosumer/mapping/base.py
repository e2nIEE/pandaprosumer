import logging
from pandapower.io_utils import JSONSerializableClass

logger = logging.getLogger("PandaProsumer")


class BaseMapping(JSONSerializableClass):
    """
    Base class for mapping between controllers.
    """

    def __init__(self, container, initiator_id, initiator_column, responder_id, responder_column, order, no_chain=False, index=None):
        """
        Initializes the BaseMapping.

        :param container: The prosumer object
        :param initiator_id: The initiating controller
        :param initiator_column: The column in the initiating controller
        :param responder_id: The responding controller
        :param responder_column: The column in the responding controller
        :param order: The order of mapping application
        :param index: The index of the mapping
        """
        fill_dict = {
            "initiator": initiator_id,
            "responder": responder_id,
            "order": order
        }
        self.initiator_column = initiator_column
        self.responder_column = responder_column

        added_index = super().add_to_net(net=container, element='mapping', index=index, overwrite=False,
                                         fill_dict=fill_dict, preserve_dtypes=True)
        self.index = added_index
        self.no_chain = no_chain

    def _validate(self):
        """
        Validates the mapping.
        """
        pass

    def map(self, initiator_controller, responder_controller):
        """
        Applies the mapping between the initiator and responder controllers.

        :param initiator_controller: The initiating controller
        :param responder_controller: The responding controller
        """
        logger.info("Applying mapping")

    def check_controllers_orders(self, initiator_ctrl, responder_ctrl):
        """
        Check that the initiator controller is scheduled to run
        before the responder controller by comparing their order attributes.
        Raises:
            ValueError: If any mapping violates the initiator-before-responder rule.
        """

        if (initiator_ctrl.level > responder_ctrl.level) or (
                (initiator_ctrl.level == responder_ctrl.level) and (initiator_ctrl.order >= responder_ctrl.order)):
            raise ValueError(
                f"Controller order error: Initiator '{initiator_ctrl.name}' (order: {initiator_ctrl.order}) "
                f"must be executed before responder '{responder_ctrl.name}' (order: {responder_ctrl.order})."
            )
