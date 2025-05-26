.. _supervisor_controller:

=========================
Supervisor Controller
=========================

Controller Data
==================

.. autoclass:: pandaprosumer.supervisor.supervisor.SupervisorData
    :members:

Controller
==============

Given a set of input columns, the `Supervisor` checks whether each defined rule is satisfied.
If the condition is met, the supervisor executes a corresponding action (such as modifying an attribute of the prosumer).
If the condition is not satisfied, a fallback action can optionally be applied.
This enables dynamic, logic-driven changes to the system inputs in response to time series data or simulation states.

.. autoclass:: pandaprosumer.supervisor.supervisor.Supervisor
    :members:


Rule Class
===========


Each rule evaluates one input column using a comparison operator (e.g., `<`, `>`, `==`, etc.) against a threshold.
If the condition is true, the rule executes an action that changes an attribute in the prosumer or a mapped object.
If false, it can optionally execute an alternative action.


.. autoclass:: pandaprosumer.supervisor.rule.Rule
    :members:


Example
-------

Suppose you want to reduce the maximum power output of a generator if the price column exceeds a certain threshold:

.. code-block:: python

   rule = Rule(
       controlled_columns="price",
       operator_str=">",
       threshold_value=100,
       controller=0,
       attr="max_p_kw",
       new_value=50.0,
       value_if_false=100.0
   )
   supervisor.add_rule(rule)

Combining Rule
===============
The `CombiningRules` class allows multiple `Rule` instances to be evaluated together using logical operators such as **AND** or **OR**.
This enables more complex, composite logic to govern control decisions in a `Supervisor`.

.. autoclass:: pandaprosumer.supervisor.combining_rule.CombiningRules
    :members:


Example
-------

.. code-block:: python

   rule1 = Rule("price", ">", 100, controller=0, attr="max_p_kw", new_value=50)
   rule2 = Rule("demand", "<", 30, controller=0, attr="max_p_kw", new_value=50)

   combo = CombiningRules([rule1, rule2], logical_operator="AND")
   supervisor.add_rule(combo)

This example applies a limit to power output only if **both** the `price` is above 100 and `demand` is below 30.


Notes
-----

- The composite rule stores logical linkage information in the prosumer's internal rule structure.
- Even though all rules are evaluated individually, they are treated as one logic unit for decision-making.
