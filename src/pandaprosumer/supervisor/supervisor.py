"""
Module containing the Supervisor class.
"""

from dataclasses import dataclass
from typing import List
import numpy as np

from pandaprosumer.controller.mapped import MappedController
from .combining_rule import CombiningRules
from .rule import *

try:
    import pandaplan.core.pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)


@dataclass
class SupervisorData:
    """
    Data class for supervisor controller.

    Attributes
    ----------
    controlled_columns : List[str]
        List of input column names.
    """
    input_columns: List[str]
    result_columns: List[str]


class Supervisor(MappedController):
    """

    """

    @classmethod
    def name_class(cls):
        return "supervisor"

    def __init__(self, prosumer, supervisor_object, order=-1, level=-1, in_service=True, index=None,
                 drop_same_existing_ctrl=False, overwrite=False, name='supervisor', matching_params=None, **kwargs):
        """
        Initializes the Supervisor.
        """
        super().__init__(prosumer, supervisor_object, order, level, in_service, index,
                         drop_same_existing_ctrl, overwrite, name, matching_params, **kwargs)
        self.rules: List[Rule] = []  # List to store rules
        self.assert_rule = {}

        self.container = prosumer

    def is_supervisor(self):
        return True

    def add_rule(self, rule: Rule):
        """
        Adds a rule-based action to the supervisor.

        :param action: An instance of Action class containing rule and action to execute.
        """
        if not isinstance(rule, (Rule, CombiningRules)):
            raise ValueError("Rule must be an instance of the Rule class.")
        self.rules.append(rule)
        index = rule.add_to_prosumer(self.container)
        return index

    def add_assert_rule(self, controller, attr, value):
        if controller not in self.assert_rule:
            self.assert_rule[controller] = {}
        if attr not in self.assert_rule[controller]:
            self.assert_rule[controller][attr] = value

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if self.in_service:

            super().control_step(prosumer)
            input_data = {input_name: input for input_name, input in zip(self.input_columns, self.inputs[0])}
            for rule in self.rules:
                if rule.evaluate(input_data):
                    rule.execute_action(prosumer, self)
                else:
                    rule.execute_opposite(prosumer, self)

        self.applied = True
        self.inputs = np.full([self._nb_elements, len(self.input_columns)], np.nan)

    def finalize_control(self, container):
        """
        Finalizes the step for the controller.

        :param container: The container object
        :param time: The current time step
        """
