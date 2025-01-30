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

.. automodule:: pandaprosumer2.mapping.generic
    :special-members:
    :exclude-members: __str__
    :members:

Fluid Mix Mapping
===================================

.. automodule:: pandaprosumer2.mapping.fluid_mix
    :special-members:
    :exclude-members: __str__
    :members:

Generic Energy System Mapping
===================================

.. automodule:: pandaprosumer2.mapping.generic_energy_system
    :special-members:
    :exclude-members: __str__
    :members:

Fluid Mix Energy System Mapping
===================================

.. automodule:: pandaprosumer2.mapping.fluid_mix_energy_system
    :special-members:
    :exclude-members: __str__
    :members:
