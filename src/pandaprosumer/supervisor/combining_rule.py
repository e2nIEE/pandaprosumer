from typing import List
from .rule import *


class CombiningRules:
    """
    A class that allows combining multiple rules using logical operators (AND, OR).
    """

    def __init__(self, rules: List[Rule], logical_operator: str = "AND"):
        """
        Initializes a CombiningRules.

        Args:
            rules (List[Rule]): A list of Rule instances.
            logical_operator (str): The logical operation to apply ("AND" or "OR").
        """
        self.rules = rules
        self.logical_operator = logical_operator.upper()

        if self.logical_operator not in ["AND", "OR"]:
            raise ValueError("Logical operator must be 'AND' or 'OR'.")

    def add_to_prosumer(self, prosumer):
        n = len(self.rules)
        if prosumer["rules"].empty:
            index_list = list(range(n))
        else:
            max_id = prosumer["rules"].index.max()
            index_list = list(range(max_id + 1, max_id + 1 + n))

        for rule, index in zip(self.rules, index_list):
            rule.set_index(index)
            fill_dict = {
                "object": self,
                "controlled_columns": rule.controlled_columns,
                "operator": rule.operator_str,
                "threshold_value": rule.threshold_value,
                "controller_index": rule.controller,
                "attribute": rule.attr,
                "new_value": rule.new_value,
                "value_if_false": rule.value_if_false,
                "logical_operator": self.logical_operator,
                "linked_rules": [idx for idx in index_list if idx != index]
            }
            for k, v in fill_dict.items():
                prosumer["rules"].at[index, k] = v
        # Todo : If the user modifies the prosumer (df), then modify the rule ?
        return index

    def __str__(self):
        return "CombiningRule"

    def evaluate(self, input_data: dict):
        """
        Evaluates the combined rules.

        Args:
            input_data (dict): A dictionary with values for each rule's input column.

        Returns:
            bool: True if the composite rule is met, False otherwise.
        """
        results = [rule.evaluate(input_data) for rule in self.rules]

        if self.logical_operator == "AND":
            return all(results)
        elif self.logical_operator == "OR":
            return any(results)

    def execute_action(self, prosumer, supervisor):
        """
        Executes the action of all the rules if the condition is met.
        """

        for rule in self.rules:
            rule.execute_action(prosumer, supervisor)

    def execute_opposite(self, prosumer, supervisor):
        for rule in self.rules:
            rule.execute_opposite(prosumer, supervisor)
