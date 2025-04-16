.. _gas_boiler_element:

==================
Gas Boiler
==================

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A gas boiler element should be associated to a :ref:`gas boiler controller <gas_boiler_controller>`
    to map it to other prosumers elements

Create Function
=====================

.. autofunction:: pandaprosumer.create_controlled_gas_boiler

Input Parameters
=========================

*prosumer.gas_boiler*


Model
=================

The gas boiler model calculate the thermal power produced of the boiler and the mass flow of the gas to heat up the fluid to the demand power.


.. math::
    :nowrap:

    \begin{align*}
        Q &= \dot{m} * Cp * (T_\text{feed} - T_\text{return})   \\
    \end{align*}

.. math::
        \dot{m}_\text{gas} = \frac{Q}{HV * \eta}


If the power consumption is higher than the maximum power of the boiler, the power
consumption is set to the maximum power, and the actual output temperature  :math:`T_\text{feed}` that can
be reached is calculated based on the maximum power.
For a gas boiler, the maximum power is defined as the maximum thermal power output, representing the highest amount of heat energy the boiler can produce.


Result Parameters
=========================
