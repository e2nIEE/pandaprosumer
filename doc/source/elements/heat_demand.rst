.. _heat_demand_element:

=============
Heat Demand
=============

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A heat demand element should be associated to a :ref:`heat demand controller <heat_demand_controller>` to map it
    to other prosumers elements

Create Function
=====================

.. autofunction:: pandaprosumer.create_heat_demand

Input Parameters
=========================

*prosumer.heat_demand*
 
   
Model
=================

The heat demand model take four inputs :math:`Q`, :math:`\dot{m}`, :math:`T_\text{feed}` and :math:`T_\text{return}`

Only three of these inputs should be provided, typically from timeseries data through a
:ref:`ConstProfile controller <const_profile_controller>`. The fourth one will be inferred from the relation

.. math::
    :nowrap:

    \begin{align*}
        Q = \dot{m} * Cp * (T_\text{feed} - T_\text{return})
    \end{align*}


Result Parameters
=========================
