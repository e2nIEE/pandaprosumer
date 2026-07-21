============
Mixing Valve
============

A 3-way mixing valve between a hot producer and a demand wishing a lower feed
temperature. Part of the hot supply is mixed with recirculated cold return
fluid so the downstream responders receive their wished feed temperature,
while the producer keeps its own (hotter) supply temperature. Mass and energy
are conserved exactly.

Physics
=======

Each timestep the downstream responders request a feed temperature
:math:`T_{out}`, a return temperature :math:`T_{ret}` and a mass flow
:math:`\dot m_{out}`. The valve receives hot fluid at :math:`T_{in}` from the
upstream producer (FluidMix mapping) and draws only the hot-leg flow

.. math::
   \dot m_{in} = \dot m_{out} \cdot \frac{T_{out} - T_{ret}}{T_{in} - T_{ret}}

recirculating the rest of the return flow
:math:`\dot m_{rec} = \dot m_{out} - \dot m_{in}`.

Mass conservation holds by construction. Under the constant-:math:`c_p`
mixing rule (:math:`c_p` evaluated at the mean temperature), energy is
conserved exactly:

.. math::
   \dot m_{in} c_p (T_{in} - T_{ret}) = \dot m_{out} c_p (T_{out} - T_{ret})

The producer sees the return temperature :math:`T_{ret}` and the mass flow
:math:`\dot m_{in}` only, so the delivered thermal power is identical on both
sides of the valve. The model assumes a single fluid (the prosumer's fluid),
no heat loss and no pressure modeling.

Special cases
=============

- **Cold supply** (:math:`T_{in} \le T_{out}`): the valve opens fully and
  passes the flow through unchanged (no recirculation); the responders
  receive fluid colder than wished.
- **Excess supply** (the producer forces more mass flow than the hot leg
  needs): the recirculation shrinks and the mixed temperature rises above the
  wished feed temperature; once the received flow exceeds the total demand,
  everything passes through at :math:`T_{in}` and the mass surplus is
  dispatched per ``overflow_strategy``.
- **Short supply** (the producer delivers less than the hot leg needs): the
  wished feed temperature is held and the delivered mass flow is scaled down.
- **Dead supply** (:math:`T_{in} \le T_{ret}`): nothing is delivered.

Element parameters
==================

.. csv-table::
   :header: "Parameter", "Description", "Unit", "Default"

   "name", "Name of the element", "", "None"
   "t_in_nom_c", "Nominal hot-inlet temperature requested from the upstream producer. Only used for the initial upstream request; the mixing uses the temperature actually received", "°C", "95"
   "overflow_strategy", "Dispatch of a forced mass-flow surplus: 'dump_proportional', 'dump_on_last' or 'cap'", "", "'dump_proportional'"
   "in_service", "In-service status", "", "True"

Input and result time series
============================

The controller has no required input time series: the received temperature
and mass flow come from the upstream ``FluidMixMapping``.

.. csv-table::
   :header: "Result column", "Description", "Unit"

   "q_delivered_kw", "Thermal power delivered to the responders", "kW"
   "mdot_in_kg_per_s", "Hot-leg mass flow drawn from the producer", "kg/s"
   "t_in_c", "Received supply temperature", "°C"
   "mdot_recirc_kg_per_s", "Recirculated return mass flow", "kg/s"
   "mdot_out_kg_per_s", "Mixed mass flow delivered downstream", "kg/s"
   "t_out_c", "Mixed feed temperature delivered downstream", "°C"
   "t_return_c", "Return temperature (identical toward producer and from responders)", "°C"

Creation
========

.. autofunction:: pandaprosumer.create_mixing_valve

.. autofunction:: pandaprosumer.create_controlled_mixing_valve
