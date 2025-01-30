.. _time_series:

===================================
Time_series
===================================

The time series module is designed for the simulation of time based operations and is linked to the control module.
Within a time series simulation controllers are used to update values of different elements in each time step in a loop.

Run Function
============

Simple prosumer time series simulation:

.. autofunction:: pandaprosumer.run_time_series.run_timeseries

:ref:`Energy systems <energy_systems>` time series simulation:

.. autofunction:: pandaprosumer.energy_system.timeseries.run_time_series_energy_system.run_timeseries

Results
============

Time series results are stored in the prosumer in prosumer.time_series for every controller in this prosumer
which has a period
