.. _uniform_heat_storage_element:

========================
Uniform Heat Storage
========================


.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A Uniform Heat Storage consists of an element and a controller. The element defines its physical parameters,
    while the controller governs the operational logic.

    The create_controlled function creates both and connects them.

A Uniform Heat Storage is a hot-water tank whose content is fully mixed: the whole tank is at a single temperature.
It exchanges water with its sources and its demands through a :ref:`FluidMixMapping <FluidMixMapping>`, like the
:ref:`Stratified Heat Storage <stratified_heat_storage_element>`, and shares its coupling logic (what the tank asks
its sources for, how it splits what it receives, the external setpoints). It is the right model for a small or
strongly stirred buffer tank, or when the stratification does not matter; it needs no geometry and is cheap to
solve. For a tank whose stratification matters (a large tank charged from the top), use the Stratified Heat Storage.

To model a storage with powers only (no temperature, no mass flow), use the
:ref:`Simple Heat Storage <heat_storage_element>` with a :ref:`GenericMapping <GenericMapping>`.

An interactive tutorial is available on Binder:
https://mybinder.org/v2/gh/e2nIEE/pandaprosumer/develop?urlpath=%2Fdoc%2Ftree%2Ftutorials

Create Controlled Function
=============================

.. autofunction:: pandaprosumer.create_controlled_uniform_heat_storage

.. autofunction:: pandaprosumer.create_uniform_heat_storage

Controller
===========================

Input Static Data
--------------------

The size of the tank is given either as a mass of water (``mass_kg``) or as an energy capacity
(``e_capacity_kwh``), not both. An energy capacity needs ``t_full_c``: it is the heat the tank holds between
``min_useful_temp_c`` and ``t_full_c``, converted to a mass with the heat capacity of the prosumer's fluid at the
mean of the two temperatures, :math:`M = E_{\text{capacity}} / (c_p \, (T_{\text{full}} - T_{\text{min useful}}))`.

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "name", "A custom name for this Uniform Heat Storage (optional)", "N/A"
    "mass_kg", "Mass of water in the tank. Must be positive. Mandatory unless ``e_capacity_kwh`` is given", "kg"
    "e_capacity_kwh", "Heat the tank holds between ``min_useful_temp_c`` and ``t_full_c``. Must be positive. Mandatory unless ``mass_kg`` is given; needs ``t_full_c``. Computed from ``mass_kg`` when ``t_full_c`` is given, NaN otherwise", "kWh"
    "min_useful_temp_c", "Lowest tank temperature (minus 0.5 K) the tank still discharges from; also the charge temperature asked to the sources when no demand is mapped. Default 65", "°C"
    "t_full_c", "Tank temperature at which the tank counts as full, the reference of ``e_capacity_kwh``. Must be above ``min_useful_temp_c``. Optional (NaN); it does not limit the charge", "°C"
    "u_w_per_m2k", "Heat transfer coefficient of the tank wall to the ambient air. Must be non-negative. Default 0 (no loss)", "W/(m²K)"
    "area_wall_m2", "Area of the tank wall exchanging with the ambient air. Must be non-negative. Default 0", "m²"
    "t_ext_c", "Ambient temperature for the heat losses, and the default initial tank temperature. Default 22.5", "°C"
    "max_remaining_capacity_kwh", "Heat the tank can still take below which it is full and asks its sources for no charge. Default 1", "kWh"
    "t_discharge_out_tol_c", "Largest difference between the demand feed temperature and the tank temperature for which the tank water alone serves the demand. Default 0.001", "°C"
    "max_charge_mdot_kg_per_s", "Optional cap on the charge mass flow the tank asks its sources for (NaN: no cap)", "kg/s"
    "t_charge_target_c", "Optional temperature the tank asks its sources to charge it at (NaN: the demand's feed temperature)", "°C"
    "in_service", "True for in service, False for out of service", "N/A"

The controller takes one more parameter, ``t_tank_init_c``, the initial tank temperature (default ``t_ext_c``).

Input Time Series
-------------------

Both inputs are optional dispatch setpoints for an external controller (e.g. a supervisor, or an optimiser result
replayed through a :ref:`ConstProfileController <const_profile_controller>` and a
:ref:`GenericMapping <GenericMapping>`). When an input is not mapped (NaN) or negative, no setpoint applies and the
storage uses its own charge / discharge logic for that time step. ``0.0`` is a setpoint (force no charge / no
discharge). They act as for the :ref:`Stratified Heat Storage <stratified_heat_storage_element>`.

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "mdot_charge_setpoint_kg_per_s", "Imposed charge mass flow. Clamped to the mass flow actually received from upstream, ignored when the tank is full. The discharge (if free) then covers the remaining demand energy.", "kg/s"
    "mdot_discharge_setpoint_kg_per_s", "Imposed discharge mass flow. Clamped to zero when the tank is not warmer than the demand return. The bypass (if free) then covers the remaining demand energy and the surplus received charges the tank.", "kg/s"

Output Time Series
-------------------

Four flows are reported: received from the sources, charge (the part of it that goes through the tank), discharge
(drawn from the tank for the demands) and delivered (sent to the demands: discharge and bypass mixed). The bypass is
the part of the received water sent straight to the demands.

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "mdot_received_kg_per_s", "Mass flow received from the sources", "kg/s"
    "t_received_in_c", "Temperature of the water received from the sources", "°C"
    "t_received_out_c", "Temperature of the water returned to the sources (charge return and bypass return mixed)", "°C"
    "q_received_kw", "Heat taken from the water received", "kW"
    "mdot_charge_kg_per_s", "Mass flow through the tank on the source side", "kg/s"
    "t_charge_in_c", "Charge inlet temperature (the received temperature)", "°C"
    "t_charge_out_c", "Mean temperature of the charge water the tank gave back over the step", "°C"
    "q_charge_kw", "Heat the charge brought into the tank", "kW"
    "mdot_discharge_kg_per_s", "Mass flow drawn from the tank for the demands", "kg/s"
    "t_discharge_in_c", "Return temperature of the demands entering the tank", "°C"
    "t_discharge_out_c", "Mean temperature of the water drawn from the tank over the step", "°C"
    "q_discharge_kw", "Heat the discharge took out of the tank", "kW"
    "mdot_delivered_kg_per_s", "Mass flow sent to the demands (discharge and bypass)", "kg/s"
    "t_delivered_in_c", "Return temperature of the demands", "°C"
    "t_delivered_out_c", "Temperature of the water sent to the demands", "°C"
    "q_delivered_kw", "Heat delivered to the demands (discharge and bypass)", "kW"
    "e_stored_kwh", "Heat stored compared to the initial tank temperature (negative when the tank is colder than it started)", "kWh"
    "e_usable_kwh", "Heat the demands can still draw: the tank's heat above their return while the tank is not colder than ``min_useful_temp_c`` minus 0.5 K, 0 otherwise", "kWh"
    "t_tank_c", "Tank temperature at the end of the step", "°C"
    "q_loss_kw", "Mean heat lost through the wall over the step", "kW"

Mapping
-----------------------

The Uniform Heat Storage Controller can be mapped using :ref:`FluidMixMapping <FluidMixMapping>`:

- as a responder, receiving hot water from one or several sources (gas or electric boiler, heat pump, heat
  exchanger, ...);

- as an initiator, sending hot water to one or several demands. A demand can also be fed directly by the tank's
  own source (source → demand and source → tank → demand): the tank then asks its source for no flow for that demand.

Its two setpoint inputs can be mapped with a :ref:`GenericMapping <GenericMapping>`.

Model
=================

.. autoclass:: pandaprosumer.controller.models.UniformHeatStorageController
    :members:

.. autofunction:: pandaprosumer.controller.models.uniform_heat_storage.mixed_tank_step

Tank temperature over a step
-----------------------------

The tank holds a mass :math:`M` of water at the temperature :math:`T`. Over a time step of length
:math:`\Delta t` the charge (mass flow :math:`\dot{m}_{\text{ch}}` at :math:`T_{\text{ch,in}}`) and the return of the
demands (:math:`\dot{m}_{\text{dch}}` at :math:`T_{\text{dch,in}}`) enter the tank and mix instantly with its content,
the same mass flows leave it at the tank temperature, and the wall loses heat to the ambient air at
:math:`T_{\text{ext}}` with the coefficient :math:`UA = U \cdot A_{\text{wall}}`. With a heat capacity :math:`c_p`
taken at the tank temperature at the start of the step:

.. math::
    M \frac{dT}{dt} = \dot{m}_{\text{ch}} (T_{\text{ch,in}} - T) + \dot{m}_{\text{dch}} (T_{\text{dch,in}} - T)
    + \frac{UA}{c_p} (T_{\text{ext}} - T)

The flows being constant over the step, this linear equation is solved exactly. The tank relaxes towards the
mixing temperature

.. math::
    T_{\infty} = \frac{\dot{m}_{\text{ch}} T_{\text{ch,in}} + \dot{m}_{\text{dch}} T_{\text{dch,in}}
    + \frac{UA}{c_p} T_{\text{ext}}}{\dot{m}_{\text{ch}} + \dot{m}_{\text{dch}} + \frac{UA}{c_p}}

at the rate :math:`b = (\dot{m}_{\text{ch}} + \dot{m}_{\text{dch}} + UA / c_p) / M`. With :math:`x = b \, \Delta t`,
the temperature at the end of the step and its mean over the step are

.. math::
    T_{\text{end}} = T_{\infty} + (T_{\text{start}} - T_{\infty}) \, e^{-x}

.. math::
    \bar{T} = T_{\infty} + (T_{\text{start}} - T_{\infty}) \, \frac{1 - e^{-x}}{x}

The water leaving the tank (back to the sources, to the demands) leaves at the tank temperature, so over the step it
carries :math:`\bar{T}`: ``t_charge_out_c`` and ``t_discharge_out_c`` are :math:`\bar{T}`, and the wall loses
:math:`UA \, (\bar{T} - T_{\text{ext}})` (``q_loss_kw``). The energy balance of the tank,

.. math::
    M (T_{\text{end}} - T_{\text{start}}) = \Delta t \left[ \dot{m}_{\text{ch}} (T_{\text{ch,in}} - \bar{T})
    - \dot{m}_{\text{dch}} (\bar{T} - T_{\text{dch,in}}) - \frac{UA}{c_p} (\bar{T} - T_{\text{ext}}) \right]

holds exactly, for any time step: the solution has no stability limit and does not depend on how a period is cut
into steps (up to the heat capacity, evaluated at each step's start temperature). In kWh the booked heats close the
balance within a fraction of a percent, each flow being booked with the heat capacity at its own temperatures and the
stored energy with the one at the tank temperature.

Charge, bypass and discharge
-----------------------------

The coupling with the sources and the demands is the one of the
:ref:`Stratified Heat Storage <stratified_heat_storage_element>` (``FluidMixHeatStorageController``), the uniform
tank being a tank of a single layer whose four connections are on that layer:

- **Request to the sources.** The tank asks its sources for the bypass that serves its demands (iso-energy: the
  flow that carries the demand's heat at the received temperature) plus the charge that fills it. The charge
  temperature is the demand's feed temperature, ``t_charge_target_c`` when it is higher, or ``min_useful_temp_c``
  without demand. The charge mass flow fills the tank within one step: the flow that brings it within 0.5 K of the
  charge temperature, :math:`M \ln(\Delta T / 0.5\ \text{K}) / \Delta t`, but at most one tank volume per step
  (:math:`M / \Delta t`, which closes :math:`1 - 1/e \approx 63\ \%` of the gap; the next steps close the rest).
  ``max_charge_mdot_kg_per_s`` caps it further. The return promised to the sources is the bypass return mixed with the
  mean tank temperature the charge would give back (:math:`\bar{T}` with that charge alone).
- **Split.** The water received goes first to the demands (bypass), the rest charges the tank. When the received
  water cannot carry the demand's heat, the tank discharges the rest, sized on the tank temperature.
- **Discharge.** The discharge keeps the heat the split sized: its mass flow is solved (by bisection) together with
  the charge and the losses so that :math:`\dot{m}_{\text{dch}} (\bar{T} - T_{\text{dch,in}})` is that heat. A
  draining tank therefore delivers more mass at a lower temperature than its start-of-step temperature.
- **Reapply.** When the return the tank really gives back differs from the one it promised, it asks its sources
  again, anchored on the energy they delivered, until both agree (the sources then book exactly the heat the tank
  received). When the source is asked again for the very stream it delivered, the tank promises the return it
  measured on that stream: a mixed tank that charges while it discharges (with setpoints) gives the charge back at
  a temperature the demand's return lowers.

Edge cases and limits
-----------------------

- **Tank full.** When the heat the tank can still take at the charge temperature,
  :math:`M c_p \max(0, T_{\text{charge}} - T)`, is below ``max_remaining_capacity_kwh`` and a demand is mapped, the
  tank asks for no charge and the whole received stream goes to the demand (over-serving it slightly rather than
  losing the energy). Without a demand the tank is never "full": a surplus would have nowhere to go.
- **Charge colder than the tank.** A charge no warmer than the tank would only cool it: it passes by, back to the
  source, without exchange. The source then delivers no heat to the tank.
- **Tank too cold to serve.** Below ``min_useful_temp_c`` minus 0.5 K, or not 0.5 K warmer than the demand
  return, the tank does not discharge: the demand goes uncovered (``q_uncovered_kw`` of the heat demand). The test is
  done at the start of the step: a tank just above the threshold can serve a whole step and end below it.
- **Large draws.** A discharge never draws more than the mass that brings the tank within 0.5 K of the demand
  return in one step; a heat larger than what that mass carries is not delivered.
- **No stratification.** The water sent to the demands is at the tank temperature, never hotter: a tank charged
  at 80 °C and drawn at the same time with a 35 °C return delivers the mixture. Use the Stratified Heat Storage when
  the hot water on top of a stratified tank matters.
- **Constant mass.** The mass of water is constant (the density change with the temperature is neglected) and the
  heat capacity is evaluated at the tank temperature at the start of each step.
- **Gas boiler at its maximum power with several responders.** A gas boiler at its maximum power that serves the
  tank and a demand in parallel can fail to converge (``Gas Boiler ...: did not converge``) when the tank, close to its
  charge temperature, returns water above ~70 °C. This comes from the gas boiler's own iteration on the return of
  its responders and happens as well with two heat demands.
