.. _electric_boiler_element:

==================
Electric Boiler
==================

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A electric boiler element should be associated to a :ref:`electric boiler controller <electric_boiler_controller>` 
    to map it to other prosumers elements

Create Function
=====================

.. autofunction:: pandaprosumer.create_controlled_electric_boiler

Input Parameters
=========================

*prosumer.electric_boiler*


Model
=================

The electric boiler model calculate the power consumption of the boiler to heat up the fluid to the demand power.
It is a tankless electric water heater that heats water on demand.

.. math::
    :nowrap:

    \begin{align*}
        P_\text{el} = \frac{Q}{\eta} &= \frac{\dot{m} * Cp * (T_\text{feed} - T_\text{return})}{\eta}  \\
    \end{align*}

If the power consumption is higher than the maximum power of the boiler P_{\text{el}_\text{max}}, the power 
consumption is set to the maximum power, and the actual output temperature  :math:`T_\text{feed}` that can
be reached is calculated based on the maximum power.


Result Parameters
=========================
