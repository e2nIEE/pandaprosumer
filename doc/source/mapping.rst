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
