import operator
from pandapower.auxiliary import get_free_id
import pandas as pd


class Rule:
    """
    A class representing a rule that applies conditional logic to data and executes an action
    based on the evaluation of the condition. The rule compares an input value against a
    threshold using an operator and, if the condition is met, modifies a specified attribute
    of a prosumer's data.
    """
    # Mapping operator strings to Python operator functions
    OPERATORS = {
        "<": operator.lt,
        "<=": operator.le,
        ">": operator.gt,
        ">=": operator.ge,
        "==": operator.eq,
        "!=": operator.ne
    }

    def __init__(self, controlled_columns, operator_str, threshold_value, controller, attr, new_value, value_if_false = None, mapping = None):
        """
        Initializes a Rule object with the necessary parameters to define a rule condition.

        Args:
            controlled_columns (str): The column to evaluate.
            operator_str (str): The comparison operator as a string (e.g., '>', '<=', '==').
            threshold_value (float): The threshold value for comparison.
            controller (int or List[int]): The controller index or list of indices.
            attr (str or List[str]): Attributes to modify if the condition is met.
            new_value (float or List[float]): Values to assign if the condition is met.
            value_if_false (float or List[float], optional): Values to assign if the condition is not met.
            mapping (bool or List[bool], optional): Whether the rule applies to a mapping object.

        Raises:
            ValueError: If an unsupported operator is provided.
        """
        self.controlled_columns = controlled_columns
        self.operator_str = operator_str
        self.threshold_value = threshold_value
        self.index = None

        #controllers index
        if isinstance(controller, list):
            self.controller = controller
        elif controller is not None:
            self.controller = [controller]

        #attr
        if isinstance(attr, list):
            self.attr = attr
        else:
            self.attr = [attr]

        #new_value
        if isinstance(new_value, list):
            self.new_value = new_value
        else:
            self.new_value = [new_value]

        #value_if_false
        if isinstance(value_if_false, list):
            self.value_if_false = value_if_false
        elif value_if_false is not None:
            self.value_if_false = [value_if_false]
        else:
            self.value_if_false = None

        #mapping
        if isinstance(mapping, list):
            self.mapping = mapping
        elif mapping is not None:
            self.mapping = [mapping]
        # Complete mapping with False if not provided
        if not mapping:
            self.mapping = [False] * len(self.controller)

        if not (len(self.attr) == len(self.new_value) == len(self.controller)):
            raise ValueError("attr, new_value, and controller must have the same length.")

        if self.value_if_false and len(self.value_if_false) != len(self.controller):
            raise ValueError("value_if_false must have the same length as controller if provided.")

        if len(self.mapping) != len(self.controller):
            raise ValueError("mapping must have the same length as controller if provided.")

    def __str__(self):
        return "Rule"

    def set_index(self,index):
        self.index = index

    def add_to_prosumer(self, prosumer):
        """
        Adds the rule to the prosumer's 'Rules' DataFrame.
        """
        if "rules" not in prosumer:
            prosumer["rules"] = pd.DataFrame(columns=[
                "object", "controlled_columns", "operator", "threshold_value",
                "controller_index", "attribute", "new_value", "value_if_false"])

        index = get_free_id(prosumer["rules"])
        self.set_index(index)

        prosumer["rules"].loc[index] = {
            "object": self,
            "controlled_columns": self.controlled_columns,
            "operator": self.operator_str,
            "threshold_value": self.threshold_value,
            "controller_index": self.controller,
            "attribute": self.attr,
            "new_value": self.new_value,
            "value_if_false": self.value_if_false
        }
        #Todo : If the user modifies the prosumer (df), then modify the rule.


    def evaluate(self, input):
        """
        Evaluates the rule using the input data.
        """
        # Compare the input value to the threshold using the provided operator.
        if self.operator_str not in self.OPERATORS:
            raise ValueError(f"Unsupported operator: {self.operator_str}")

        return self.OPERATORS[self.operator_str](input[self.controlled_columns], self.threshold_value)

    def evaluate_assert(self,new_value, stored_value, attr, is_max=True):
        if is_max and new_value > stored_value:
            raise ValueError(f"The new value {new_value} should not exceed the original {attr} value ({stored_value}).")
        elif not is_max and new_value < stored_value:
            raise ValueError(f"The new value {new_value} should not be smaller than the original {attr} value ({stored_value}).")

    def execute_action(self, prosumer, supervisor):
        """
        Executes the action(s) on the controller(s).
        """
        if not self.attr or not self.new_value:
            return

        for a, v, c, m in zip(self.attr, self.new_value, self.controller, self.mapping):
            if not m:
                df = getattr(prosumer, prosumer.controller.iloc[c].object.obj.element_name)
                element_index = prosumer.controller.iloc[c].object.obj.element_index[0]

                if hasattr(df.iloc[element_index], a):
                    current_value = df.at[element_index, a]
                    if a.startswith("max_") or a.startswith("min_"):
                        if (c not in supervisor.assert_rule) or (a not in supervisor.assert_rule[c]):
                            supervisor.add_assert_rule(c, a, current_value)
                        is_max = a.startswith("max_")
                        self.evaluate_assert(v, supervisor.assert_rule[c][a], a, is_max)
                    df.at[element_index, a] = v

                elif hasattr(prosumer.controller.iloc[c], a):
                    prosumer.controller.at[c, a] = v
                else:
                    raise AttributeError(f"'{a}' not found in {df}")

            else:
                df = prosumer.mapping.iloc[c].object
                if hasattr(df, a):
                    prosumer.mapping.at[c, a] = v
                else:
                    raise AttributeError(f"'{a}' not found in {df}")

    def execute_opposite(self, prosumer, supervisor):
        if self.value_if_false is None:
            return

        for a, v_false, c, m in zip(self.attr, self.value_if_false, self.controller, self.mapping):
            if v_false is None:
                continue
            if not m:
                df = getattr(prosumer, prosumer.controller.iloc[c].object.obj.element_name)
                element_index = prosumer.controller.iloc[c].object.obj.element_index[0]

                if hasattr(df.iloc[element_index], a):
                    current_value = df.at[element_index, a]
                    if a.startswith("max_") or a.startswith("min_"):
                        if (c not in supervisor.assert_rule) or (a not in supervisor.assert_rule[c]):
                            supervisor.add_assert_rule(c, a, current_value)
                        is_max = a.startswith("max_")
                        self.evaluate_assert(v_false, supervisor.assert_rule[c][a], a, is_max)
                    df.at[element_index, a] = v_false

                elif hasattr(prosumer.controller.iloc[c], a):
                    prosumer.controller.at[c, a] = v_false
                else:
                    raise AttributeError(f"'{a}' not found in {df}")
            else:
                df = prosumer.mapping.iloc[c].object
                if hasattr(df, a):
                    prosumer.mapping.at[c, a] = v_false
                else:
                    raise AttributeError(f"'{a}' not found in {df}")
