.. _electric_boiler_element:

==================
Electric Boiler
==================

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    An electric boiler consists of one element and one controller.
    The element defines its physical parameters, while the controller governs the operational logic.

Create Controlled Function
===============================

.. autofunction:: pandaprosumer.create_controlled_electric_boiler

Controller
===============================

.. figure:: ../elements/controller_pics/electric_boiler_controller.png
    :width: 50em
    :alt: Electric Boiler Controller logic
    :align: center


.. raw:: html

   <br>


Input Static Data
----------------------------
These are the physical parameters required for the Electric Boiler element to enable the model calculation:

.. csv-table::
   :header: "Parameter", "Description", "Unit"

   "name", "Unique name or identifier for the electric boiler element.", "N/A"
   "max_p_kw", "Maximum electrical power of the boiler.", "kW"
   "min_p_kw", "Minimum electrical power of the boiler. Only relevant when allow_stop is False.", "kW"
   "max_ramp_up_kw_per_s", "Maximum allowed increase of electrical power between two time steps.", "kW/s"
   "max_ramp_down_kw_per_s", "Maximum allowed decrease of electrical power between two time steps.", "kW/s"
   "efficiency_percent", "Boiler efficiency expressed as a percentage.", "%"
   "allow_stop", "Whether the boiler is allowed to stop completely (reach zero power) when there is zero demand. If False and min_p_kw is set, the boiler will operate at min_p_kw even with zero demand.", "Boolean"
   "max_t_out_c", "Maximum output temperature constraint. If the calculated output temperature exceeds this value, it will be limited to this temperature.", "Degree Celsius"
   "min_on_time_s", "Minimum running time. Once started, the boiler cannot stop before it has run for this duration: until then it behaves as with ``allow_stop=False``. Requires a positive ``min_p_kw``. See :ref:`electric_boiler_min_on_off_time`.", "s"
   "min_off_time_s", "Minimum stop time. Once stopped, the boiler cannot restart before it has been stopped for this duration: until then it delivers no heat, whatever the demand. See :ref:`electric_boiler_min_on_off_time`.", "s"
   "overflow_strategy", "How to dispatch surplus mass flow to responders when the boiler runs at ``min_p_kw`` but the demand asks for less. ``'dump_proportional'`` (default) splits the surplus across responders in proportion to their requests; ``'dump_on_last'`` pushes the surplus mass flow onto the last responder at the requested feed temperature; ``'cap'`` drops the surplus and raises ``t_out_c`` to keep energy balance. See :ref:`overflow_strategy`.", "str"


Input Time Series
---------------------------------

No input (GenericMapping) needed for this controller


Output Time Series
----------------------------

.. csv-table:: Output Time Series: Electric Boiler

   :header: "Parameter", "Description", "Unit"
   "q_kw", "The provided heat power.", "kW"
   "mdot_kg_per_s", "The water mass flow rate through the boiler.", "kg/s"
   "t_in_c", "The temperature at the inlet of the electric boiler (cold return pipe).", "Degree Celsius"
   "t_out_c", "The temperature at the outlet of the electric boiler (hot feed pipe).", "Degree Celsius"
   "p_kw", "The boiler consumed electrical power.", "kW"


Mapping
-----------------------

The Electric Boiler Controller can be mapped using :ref:`FluidMixMapping <FluidMixMapping>`.

- No inputs are mapped, as the electric boiler does not act as a responder.
- The following outputs are mapped:

  - ``mdot_kg_per_s``
  - ``t_out_c``


Model
=======================

.. autoclass:: pandaprosumer.controller.models.ElectricBoilerController
    :members:

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

The model also supports additional constraints:

- **Maximum output temperature constraint**: If :math:`T_\text{feed}` exceeds the ``max_t_out_c`` parameter,
  the output temperature is limited to this maximum value and the mass flow is adjusted accordingly.

- **Minimum power constraint**: If ``min_p_kw`` is set, the boiler will maintain at least this minimum power
  level, regardless of the ``allow_stop`` setting. When the calculated power would be below ``min_p_kw``,
  the boiler operates at ``min_p_kw``. The ``allow_stop`` parameter only affects whether the boiler can
  shut down completely when there is zero demand - if ``allow_stop=False``, the boiler will operate at
  ``min_p_kw`` even with zero demand. Without any demand (no mass flow and no temperature difference requested),
  the power is carried with the temperature difference of the previous time step.

.. _electric_boiler_min_on_off_time:

Minimum Running and Stop Times
------------------------------

``min_on_time_s`` and ``min_off_time_s`` prevent the boiler from cycling. The boiler is running at a time
step if it delivers heat (:math:`Q > 0`) and stopped otherwise.

- **Minimum running time**: if the boiler started at time step :math:`t_\text{start}`, it cannot stop at
  a time step :math:`t` such that :math:`t - t_\text{start} < \text{min\_on\_time\_s}`. When the demand
  drops to zero in this window, the boiler keeps running at ``min_p_kw``, as with ``allow_stop=False``.
- **Minimum stop time**: if the boiler stopped at time step :math:`t_\text{stop}`, it cannot restart at a
  time step :math:`t` such that :math:`t - t_\text{stop} < \text{min\_off\_time\_s}`. In this window
  the boiler delivers no heat, no mass flow and consumes no electricity, whatever the demand.

With hourly time steps and ``min_on_time_s = min_off_time_s = 6 * 3600``, a boiler started at 08:00 runs at
least until 13:00 included and may stop at 14:00; a boiler stopped at 14:00 stays off at least until 19:00
included and may restart at 20:00.

The state of the first time step of a run is assumed to have lasted long enough: only a start or a stop
during the run locks the boiler. The history is reset at the start of each ``run_timeseries``.

