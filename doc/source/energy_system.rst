.. _energy_systems:

=============
Energy System
=============

In pandaprosumer, energy systems allow to combine prosumers, pandapower electrical networks, and pandapipes
fluid network in one multi-energy system

Create Function
===============

An empty energy system is created with this function:

.. autofunction:: pandaprosumer.energy_system.create_energy_system.create_empty_energy_system

An existing pandapipes fluid net or pandapower net can be added with this function:

.. autofunction:: pandaprosumer.energy_system.create_energy_system.add_net_to_energy_system

The nets are stored with a unique key in a dictionary in energy_system['nets'].

An existing pandaprosumer prosumer can be added with this function:

.. autofunction:: pandaprosumer.energy_system.create_energy_system.add_pandaprosumer_to_energy_system

The prosumers are stored with a unique key in a dictionary in energy_system['prosumer'].
