.. _heat_storage_element:

==================
Heat Storage
==================

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A heat storage element should be associated to a :ref:`heat storage controller <simple_heat_storage_controller>`
    to ensure it interacts correctly with other system components.

Create Function
=====================

.. autofunction:: pandaprosumer.create_controlled_heat_storage

Input Parameters
=========================

*prosumer.heat_storage*

Model
=================

The heat storage model computes the heat received and delivered by the storage element, and updates the state of charge (SOC) accordingly.

.. math::
    :nowrap:

    \begin{align*}
        E_\text{received} &= \dot{Q}_\text{received} \cdot \frac{\Delta t}{3600} \\
        E_\text{delivered} &= \dot{Q}_\text{delivered} \cdot \frac{\Delta t}{3600} \\
        \text{SOC}_{t+1} &= \frac{E_\text{stored}}{Q_\text{capacity}} = \frac{E_\text{stored, t} + E_\text{received} - E_\text{delivered}}{Q_\text{capacity}} \\
    \end{align*}

The SOC is adjusted each timestep to reflect the energy balance within the storage unit.
If the requested heat exceeds available storage, the delivery is capped to the actual available energy.

Result Parameters
=========================

The following results are stored in the output:

* **State of Charge (SOC)** – The current energy level relative to storage capacity.
* **Delivered Power** – The amount of heat delivered during the timestep.