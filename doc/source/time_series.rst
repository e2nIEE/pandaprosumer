.. _time_series:

===================================
Time_series
===================================

The time series module is designed for the **simulation of time-based operations**
and is closely linked to the control module. This module is inspired by **pandapipes** and **pandapower**, and extends its capabilities for handling prosumer
systems and energy simulations. `Pandapower controller documentation <https://pandapower.readthedocs.io/en/latest/control.html>`_


In a time series simulation, **controllers** are used to update values of different elements in each time step within a loop.


Run Function
============

Simple prosumer time series simulation:

.. autofunction:: pandaprosumer.run_time_series.run_timeseries

:ref:`Energy systems <energy_systems>` time series simulation:

.. autofunction:: pandaprosumer.energy_system.timeseries.run_time_series_energy_system.run_timeseries

Initialization and Finalization
===============================

The time series simulation includes initialization and finalization steps, inspired by the `pandapipes` time series module:

- **Initialization**: Sets up the necessary controllers and data sources before the time series loop begins.

  .. code-block:: python

     time_series_initialization(controller_order)

  This ensures that all relevant data and settings are in place before running the simulation.

- **Finalization**: Cleans up after the simulation, ensuring that all controllers and time series data are properly handled and stored.

  .. code-block:: python

     time_series_finalization(controller_order)

Results
=======

After running a time series simulation, the results for each prosumer are stored in `prosumer.time_series`.

These results contain the **output of every controller** in the prosumer during the simulation period.
Each controller stores its time-based results, allowing detailed tracking and post-simulation analysis.

For energy systems with integrated pandapipes networks, time series results are synchronized across the system, ensuring controllers receive accurate inputs from other systems or networks for each time step.

