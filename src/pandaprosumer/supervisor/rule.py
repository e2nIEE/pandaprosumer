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

    def __init__(self, controlled_columns, operator_str, threshold_value, controller, attr= None, new_value= None, value_if_false = None, mapping = False):
        """
              Initializes the Rule with the necessary parameters to define the rule condition.

              Args:
                  controlled_columns (str): The column to evaluate.
                  operator_str (str): The operator to use for comparison.
                  threshold_value (float): The threshold value to compare against.
                  controller (int): The index of the controller for the prosumer.
                  attr (str): The attribute to modify if the rule condition is met.
                  new_value (float): The value to assign to the attribute when the rule is satisfied.
                  value_if_false (float, default None): The value to assign to the attribute when the rule is not satisfied.
                  mapping (bool, default False): Whether the rule should be applied an a controller (False) or on a GenericMixMapping/FluidMixMapping object.

              Raises:
                  ValueError: If an unsupported operator is provided.
              """
        self.controlled_columns = controlled_columns
        self.operator_str = operator_str
        self.threshold_value = threshold_value
        self.controller = controller
        self.attr = attr
        self.new_value = new_value
        self.value_if_false = value_if_false
        self.index = None
        self.mapping = mapping

    def __str__(self):
        return "Rule"

    def set_index(self,index):
        self.index = index

    def add_to_prosumer(self, prosumer):
        """
        Adds the rule to the prosumer's 'Rules' DataFrame.
        """
        if "Rules" not in prosumer:
            prosumer["Rules"] = pd.DataFrame(columns=[
                "object", "controlled_columns", "operator", "threshold_value",
                "controller_index", "attribute", "new_value", "value_if_false"])

        index = get_free_id(prosumer["Rules"])
        self.set_index(index)

        prosumer["Rules"].loc[index] = {
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

    def evaluate_assert(self,new_value, stored_value, is_max=True):
        if is_max and new_value > stored_value:
            raise ValueError(f"The new value {new_value} should not exceed the original {self.attr} value ({stored_value}).")
        elif not is_max and new_value < stored_value:
            raise ValueError(f"The new value {new_value} should not be smaller than the original {self.attr} value ({stored_value}).")

    def execute_action(self, prosumer,supervisor):
        """
        Executes the action on the controller.
        """
        if not self.mapping:
            df = getattr(prosumer, prosumer.controller.iloc[self.controller].object.obj.element_name)
            element_index = prosumer.controller.iloc[self.controller].object.obj.element_index[0]

            if self.attr is None or self.new_value is None:
                return
            if hasattr(df.iloc[element_index], self.attr):
                current_value = df.at[element_index, self.attr]

                # Ensure that max_ attributes are not exceeded
                if self.attr.startswith("max_") or self.attr.startswith("min_"):
                    if (self.controller not in supervisor.assert_rule) or (self.attr not in supervisor.assert_rule[self.controller]):
                        supervisor.add_assert_rule(self.controller, self.attr, current_value)
                    is_max = self.attr.startswith("max_")
                    self.evaluate_assert(self.new_value, supervisor.assert_rule[self.controller][self.attr], is_max)

                df.at[element_index, self.attr] = self.new_value

            elif hasattr(prosumer.controller.iloc[self.controller], self.attr):
                prosumer.controller.at[self.controller, self.attr] = self.new_value
            else:
                raise AttributeError(f"'{self.attr}' not found in {df}")
        else:
            df = prosumer.mapping.iloc[self.controller].object
            if hasattr(df, self.attr):
                prosumer.mapping.at[self.controller, self.attr] = self.new_value
            else:
                raise AttributeError(f"'{self.attr}' not found in {df}")


    def execute_opposite(self, prosumer, supervisor):
        if self.value_if_false is not None:
            if not self.mapping:
                df = getattr(prosumer, prosumer.controller.iloc[self.controller].object.obj.element_name)
                element_index = prosumer.controller.iloc[self.controller].object.obj.element_index[0]
                if self.attr is None:
                    return
                if hasattr(df.iloc[element_index], self.attr):
                    current_value = df.at[element_index, self.attr]

                    # Ensure that max_ attributes are not exceeded
                    if self.attr.startswith("max_") or self.attr.startswith("min_"):
                        if (self.controller not in supervisor.assert_rule) or (
                                self.attr not in supervisor.assert_rule[self.controller]):
                            supervisor.add_assert_rule(self.controller, self.attr, current_value)
                        is_max = self.attr.startswith("max_")
                        self.evaluate_assert(self.value_if_false, supervisor.assert_rule[self.controller][self.attr], is_max)

                    df.at[element_index, self.attr] = self.value_if_false

                elif hasattr(prosumer.controller.iloc[self.controller], self.attr):
                    prosumer.controller.at[self.controller, self.attr] = self.value_if_false
                else:
                    raise AttributeError(f"'{self.attr}' not found in {df}")
            else:
                df = prosumer.mapping.iloc[self.controller].object
                if hasattr(df, self.attr):
                    prosumer.mapping.at[self.controller, self.attr] = self.value_if_false
                else:
                    raise AttributeError(f"'{self.attr}' not found in {df}")