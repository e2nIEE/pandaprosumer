===================================
Mappings
===================================

.. _mappings:

In pandaprosumer, mappings allow to create connections between controllers in a prosumer,
or between controller in a prosumer and in a controller in pandapower or pandapipes network.

Each mapping has an initiator controller and a responder controller

Mappings are executed at the end of the initiator controller control_step to map the relevant data to
the input of the responder controller.


Generic Mapping
===================================

.. _GenericMapping:

**GenericMapping** provides a flexible way to map numerical data between controllers. It allows adding or subtracting values from one controller's step results to another controller's inputs.

.. figure:: /pics/generic.png
    :width: 150em
    :alt: Controller interaction with Generic Mapping within prosumer
    :align: center

    Controller interaction with Generic Mapping within prosumer


**Key Features:**
- Supports both scalar and vector mappings.
- Allows element-wise addition and subtraction operations.
- Handles missing values with default replacements.

Implementation Details**

.. automodule:: pandaprosumer.mapping.generic
    :special-members:
    :exclude-members: __str__
    :members:

**Methods and Functionalities**

- **_add_mapping(initiator_controller, responder_controller, initiator_column, responder_column)**
    - Adds the values from the initiator controller's result column to the responder controller's input column.
    - Replaces NaN values with zero before applying the operation.

- **_subtract_mapping(initiator_controller, responder_controller, initiator_column, responder_column)**
    - Subtracts the values from the initiator controller's result column from the responder controller's input column.
    - Uses similar handling for NaN values as in `_add_mapping`.

- **GenericMapping** sets the argument ``no_chain=True`` by default. The `no_chain` attribute is a key flag that defines whether a mapping participates in controller chaining.

Fluid Mix Mapping
===================================

.. _FluidMixMapping:

Fluid Mix Mapping in PandaProsumer is designed to perform mapping operations for fluid properties between controllers.
Each prosumer controller is expected to maintain specific attributes for fluid data:

- **input_mass_flow_with_temp**: A dictionary containing the fluid's temperature and mass flow.
- **result_mass_flow_with_temp**: A list of dictionaries (to allow one-to-many mappings) with computed fluid properties.

.. figure:: /pics/fluid_mix.png
    :width: 150em
    :alt: Controller interaction with Fluid Mix Mapping within prosumer
    :align: center

    Controller interaction with Fluid Mix Mapping within prosumer



The FluidMixMapping operation performs the following steps:
- Retrieves the initiator's fluid properties (temperature and mass flow) from the `result_mass_flow_with_temp` list based on the specified order.
- If the responder's fluid input values (temperature or mass flow) are NaN, the initiator's fluid properties are used directly.
- Otherwise, it computes a new fluid state by:

  - Summing the mass flows.
  - Calculating the temperature as a weighted average. If the total mass flow is zero, the simple average of the temperatures is used.

- The resulting mixed fluid properties are stored back in the responder's ``input_mass_flow_with_temp``.

.. automodule:: pandaprosumer.mapping.fluid_mix
    :special-members:
    :exclude-members: __str__
    :members:


- **FluidMixMapping** sets the argument ``no_chain=False`` by default. The `no_chain` attribute is a key flag that defines whether a mapping participates in controller chaining.

.. _overflow_strategy:

Overflow Strategy: Dispatching Surplus Mass Flow
=================================================

When a producer (Gas Boiler, Electric Boiler, Heat Pump) is forced onto a
thermal floor (``min_q_kw`` / ``min_p_kw`` / ``min_p_comp_kw``) but the
mapped responder(s) request less mass flow than that floor implies, the
``_merit_order_mass_flow`` helper has to decide what to do with the
surplus mass flow it cannot place. The ``overflow_strategy`` parameter on
each producer element selects between three behaviours:

- ``'dump_proportional'`` (default):
    The surplus is split across all responders in proportion to their
    original requests. If every request is zero, the surplus is split
    equally. Responders receive more mass flow than they requested, at
    the producer's nominal ``t_out_c`` / ``t_cond_out_c``. The downstream
    heat demand recomputes ``q_received_kw`` from the received mass flow
    and reports a **negative** ``q_uncovered_kw`` to signal over-delivery.
    With this default, every producer keeps mass and energy balance at
    the FluidMix interface - **no energy leak**.

- ``'dump_on_last'``:
    The surplus mass flow is added to the **last** responder (lowest
    merit-order priority) only. Use this when one specific load is
    designated to absorb the over-supply (a buffer tank, a return loop,
    a flexible heat demand) rather than spreading it evenly.

- ``'cap'`` (legacy backwards-compatible behaviour):
    The surplus mass flow is silently dropped. Each responder receives at
    most ``min(its_request, what_is_left)``. To keep the global energy
    balance, the boiler controllers compensate after the dispatch by
    raising ``t_out_c`` so the smaller mass flow still carries the
    producer's full thermal output - the responder ends up over-supplied
    via temperature (e.g. 123.7 °C instead of the requested 76.85 °C).
    The Heat Pump cannot raise ``t_cond_out_c`` (it must respect the
    demand's setpoint), so under ``'cap'`` the surplus is lost: the HP
    records ``q_cond_kw = min_p_comp_kw * COP`` while the responder
    receives only what it asked for. **An** :class:`EnergyLeakWarning`
    **is emitted on every step where this happens** (see below).

In every case, **mass and energy balances are recomputed consistently on
both sides of the FluidMix interface**: ``producer.t_out == demand.t_in``,
``producer.t_in == demand.t_out``, ``producer.mdot == demand.mdot``, and
``producer.q == demand.q_received``.

.. note::
    A responder may not physically be able to absorb extra mass flow
    (e.g. a radiator at a fixed setpoint). The ``'dump_on_last'`` /
    ``'dump_proportional'`` strategies do not model this - they assume
    the responder accepts whatever is pushed onto it. If you sum
    ``q_uncovered_kw`` to compute "unmet demand", clamp it at zero or
    that metric will be polluted by the over-delivery signal.

.. note::
    When the demand exceeds what the producer can supply
    (``sum(requested) >= available``), the surplus is zero and the three
    strategies behave identically (standard FIFO merit order).

Implementation: the strategy is read from the producer element via
``_get_element_param(prosumer, 'overflow_strategy')`` and forwarded to
``BasicProsumerController._merit_order_mass_flow``.

EnergyLeakWarning
=================

Every producer controller (Gas Boiler, Electric Boiler, Heat Pump) calls
``_check_fluid_mix_balance`` at the end of its ``control_step``,
comparing the recorded mass flow to the mass flow actually dispatched to
the FluidMix responders. When they differ - i.e. when energy is silently
dropped at the interface - an :class:`EnergyLeakWarning` is emitted on
that timestep with:

- the producer class and controller name,
- the timestep where the leak occurred,
- the leak size in kW,
- the producer's recorded mdot, the dispatched mdot, and the recorded q_kw,
- the active ``overflow_strategy``,
- a hint pointing to ``'dump_on_last'`` or ``'dump_proportional'`` as the fix.

In practice this warning currently fires only when an element is
explicitly configured with the legacy ``overflow_strategy='cap'`` AND
its thermal-floor constraint is active (Heat Pump pinned at
``min_p_comp_kw`` with a demand that requires less). Under the default
``'dump_proportional'`` (or ``'dump_on_last'``) it never fires. The
boilers also reconcile via ``t_out_c`` under ``'cap'``, so they stay
silent under every strategy.

Example warning message::

    heat_pump_controller 'hp1' at timestep 2020-01-01 03:00:00+00:00:
    energy leak of 20.627 kW at the FluidMix interface (producer
    mdot=0.258348 kg/s, dispatched=0.153090 kg/s, q_kw=50.627 kW,
    overflow_strategy='cap'). Consider setting
    overflow_strategy='dump_on_last' (or 'dump_proportional') on this
    producer to dispatch the surplus to a responder instead.

If you understand and accept the leak (e.g. the surplus models a
recirculated bypass loop not visible to your accounting), silence the
warning explicitly::

    import warnings
    from pandaprosumer.controller.mapped import EnergyLeakWarning
    warnings.simplefilter("ignore", EnergyLeakWarning)

Generic Energy System Mapping
===================================
Generic Energy System Mapping enables mapping between controllers that belong to different prosumer networks or producers.
This mapping extends the functionality of GenericMapping by allowing the responder controller to be located in a separate
prosumer. The attribute ``responder_net`` represents the target prosumer, from which the responder controller is retrieved
by its identifier.

.. automodule:: pandaprosumer.mapping.generic_energy_system
    :special-members:
    :exclude-members: __str__
    :members:

Fluid Mix Energy System Mapping
===================================

Fluid Mix Energy System Mapping enables mapping between controllers that belong to different prosumer networks or producers.
This mapping extends the functionality of FluidMixMapping by allowing the responder controller to be located in a separate
prosumer. The attribute ``responder_net`` represents the target prosumer, from which the responder controller is retrieved
by its identifier.

.. automodule:: pandaprosumer.mapping.fluid_mix_energy_system
    :special-members:
    :exclude-members: __str__
    :members:



----------------------------------------
Order of Mapping vs Controller Order
----------------------------------------

It is important to distinguish between the `order` attribute in mappings and the `order` of controllers:

- **Mapping `order`**:
    - Defines the **sequence in which mappings are applied** for a given initiator controller.
    - When a controller has multiple responder mappings, the `order` ensures that mappings are executed in a **predictable and controlled order**.
    - This is especially relevant in fluid mixing scenarios, where the final state of a responder depends on the **accumulation of multiple mappings**.

    .. note::
        The mapping `order` is **local to the initiator**. Each initiator can have mappings with `order = 0, 1, 2, ...`, controlling the order in which its mappings are applied to different responders.

- **Controller `order`**:
    - Defines the **execution order of controllers themselves** during the simulation.
    - Controllers are calculated in order of their `order` attribute during each simulation step, regardless of any mapping logic.

-----------------------------------
Key Differences
-----------------------------------

+---------------------+---------------------------------------------+
| **Concept**         | **What It Controls**                        |
+=====================+=============================================+
| Mapping `order`     | Order of mapping applications per initiator |
+---------------------+---------------------------------------------+
| Controller `order`  | Execution sequence of controllers globally  |
+---------------------+---------------------------------------------+

These two types of order **do not influence each other directly**, but together they allow for precise control over the flow and transformation of data within and across controllers.



-------------------------------
Order Checking in PandaProsumer
-------------------------------


To ensure consistency in the execution of controllers and data mappings within a prosumer, PandaProsumer implements **order checking mechanisms**. These mechanisms prevent inconsistencies in controller execution levels and ensure proper mapping sequences between controllers.

Level Checking
----------------------------
The **level checking** process ensures that all controllers within a prosumer operate at the same level, with the following exceptions:

- Controllers of type **ConstProfile** are allowed to be executed first and are not required to have the same level as other controllers.
- Controllers from **pandapower** or **pandapipes** networks are excluded from this level check.

**Implementation Details**:
- All controllers (excluding the exceptions above) must share the same `level` attribute.
- If different levels are found, an error is raised to prevent unintended execution sequences.

This mechanism ensures that **controllers within a prosumer execute in a synchronized manner**, avoiding errors due to level mismatches.

Controller Execution Order Validation
------------------------------------------
The **controller order checking** mechanism ensures that:
- The **initiator controller** executes **before** the **responder controller**.
- The execution order respects both the `level` and `order` attributes of controllers.

**Validation Rules**:
1. If the **initiator controller has a higher level** than the responder, an error is raised.
2. If both controllers share the **same level**, the **initiator's order must be lower than the responder's order**.
3. If the execution order is incorrect, an error is raised.

Mapping Order Checking
-----------------------------
The **mapping order checking** mechanism ensures that the mappings between controllers are correctly structured.
Each initiator must be properly mapped to its responder(s), and the mapping order must be **continuous and start at zero**.

**Key Checks**:
- Each **initiator controller** should have a defined list of responder mappings.
- The order values of mappings must be consecutive integers starting from `0`.
- If gaps or inconsistencies in the mapping order are detected, an error is raised.

This process ensures that **data flows correctly between controllers**, avoiding situations where mappings
are applied in an undefined or incorrect order.

check_order Argument
-----------------------------
PandaProsumer provides a `check_order` argument when creating a prosumer.
This argument allows users to enable or disable order checking based on their needs.

- **check_order = True** (default):
  - Enforces level checking among controllers.
  - Ensures mapping orders are correctly structured.
- **check_order = False**:
  - Skips all order validation steps.
  - Can be useful in flexible configurations where strict order enforcement is not required.

By providing this option, **users can balance between strict order enforcement and flexible execution**, depending on their specific use case.

---
These order-checking mechanisms play a crucial role in maintaining the consistency and accuracy of controller operations and mappings within PandaProsumer networks.
