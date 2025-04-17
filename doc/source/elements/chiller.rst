.. _chiller_element:

=================
Chiller
=================

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A chiller consists of an element and a controller. The element defines it's physical parameters,
    while the controller governs the operational logic.

    The create_controlled function creates both and connects them.

Create Controlled Function
=============================

.. autofunction:: pandaprosumer.create_controlled_chiller

Controller
==============
graphical representation here

Input Static Data
-------------------

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "fluid_cp", "Fluid specific heat capacity", "kJ/kg.K"
    "superheating_temp", "Superheating temperature", "°C"
    "subcooling_temp", "Subcooling temperature", "°C"
    "condenser_pinch", "Condenser Pinch point", "delta °C"
    "evaporator_pinch", "Evaporator Pinch point", "delta °C"
    "cd_coefficient", "Cd Coefficient", "-"
    "evap_pump_power", "Evaporator pump power", "kJ/h"
    "cond_pump_power", "Condenser pump power", "kJ/h"
    "motor_efficiency", "Motor efficiency", "-"
    "refrigerant_fluid", "Refrigerant fluid", "-"



Input Time Series
--------------------

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "time_series_file", "Name of the file containing the time histories", "-"
    "setpoint_temp_col", "Column header of Set point temperature", "K"
    "evap_inlet_temp_col", "Column header of Evaporator inlet temperature", "K"
    "cond_inlet_temp_col", "Column header of Condenser inlet temperature", "K"
    "cond_temp_increase_col", "Column header of Condenser temp. increase", "delta °C"
    "cooling_demand_col", "Column header of Cooling demand", "kJ/h"
    "isentropic_eff_col", "Column header of Isentropic efficiency", "-"
    "max_chiller_power_col", "Column header of Maximum chiller power", "kJ/h"
    "control_signal_col", "Column header of Control signal", "-"



Output Time Series
---------------------


.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "delivered_power_chiller", "Delivered power by chiller", "kJ/h"
    "unmet_demand", "Unmet cooling demand", "kJ/h"
    "compressor_power", "Compressor power consumption", "kJ/h"
    "eer", "Energy Efficiency Ratio", "-"
    "plr", "Part Load Ratio", "-"
    "evaporator_temp", "Evaporator temperature", "K"
    "condenser_temp", "Condenser temperature", "K"
    "evaporator_flow", "Evaporator flow rate", "kg/h"
    "condenser_flow", "Condenser flow rate", "kg/h"
    "evaporator_power", "Evaporator power consumption", "kJ/h"



Mapping
----------

The Compression Chiller model uses Generic Mapping Scheme.


Model
=================

The model first checks whether the chiller is **on**. For the chiller to be on, all of the following conditions must be met:

1. The control signal is greater than 0.5.
2. The cooling demand is greater than 0.
3. The evaporator set point temperature is greater than the evaporator inlet temperature.

If these conditions are satisfied, a simple refrigeration cycle is calculated from the input data.

Evaporating Temperature
-----------------------

The model considers four possible pinch points — two in the evaporator and two in the condenser — located as shown in the referenced figure (Figure 8). In this figure:

- :math:`Q_c` refers to the cooling energy.
- :math:`Q_h` refers to the heating energy.

The evaporating temperature is determined by evaluating the two evaporator pinch points (inlet and outlet):

.. math::

    T_{evap} = \min(T_{set} - PP_{evap}, T_i - T_{SH} - PP_{evap}) \tag{15}

Where:

- :math:`T_{set}` : heat pump set point temperature
- :math:`PP_{evap}` : pinch point in the evaporator
- :math:`T_i` : evaporator inlet water temperature
- :math:`T_{SH}` : superheating temperature

With this temperature and saturation conditions, the evaporating pressure :math:`P_{evap}` is obtained via CoolProp.

Condensing Temperature
----------------------

The condensing temperature is calculated based on the pinch point at the condenser outlet:

.. math::

    T_{cond} = T_{in,cond} + \Delta T_{cond} + PP_{cond} + T_{SC} \tag{16}

Where:

- :math:`T_{in,cond}` : water temperature at condenser inlet
- :math:`\Delta T_{cond}` : temperature increase in condenser
- :math:`PP_{cond}` : pinch point on the condenser
- :math:`T_{SC}` : subcooling temperature

This temperature may later be corrected to ensure pinch conditions on the steam saturation line are met.

Compressor Inlet and Isentropic Compression
-------------------------------------------

The refrigerant conditions at the compressor inlet are determined using:

- :math:`T = T_{evap} + T_{SH}`
- :math:`P = P_{evap}`

From this, CoolProp is called to compute thermodynamic properties.

To determine the isentropic compression conditions, CoolProp is called with the inlet entropy and condensing pressure.

The enthalpy at the compressor discharge is calculated as:

.. math::

    h_{dis} = h_{suc} + \frac{h_{is} - h_{suc}}{\eta_{is}} \tag{17}

Where:

- :math:`h_{dis}` : enthalpy at compressor discharge
- :math:`h_{suc}` : enthalpy at compressor inlet
- :math:`h_{is}` : enthalpy of isentropic compression
- :math:`\eta_{is}` : isentropic efficiency of the compressor

CoolProp is again called with this discharge enthalpy and condensing pressure to obtain the discharge conditions.

Condenser Outlet Conditions
---------------------------

Condenser outlet conditions are computed with:

- :math:`T = T_{cond} - T_{SC}`
- :math:`P = P_{cond}`

Where :math:`T_{SC}` is the degrees of subcooling.

Heat Production and Flow Rates
------------------------------

To calculate condenser and refrigerant flow rates, the demand is limited to the available pump power:

.. math::

    \dot{Q}_{loadef} = \min(\dot{Q}_{load}, P_{nom}) \tag{18}

Where:

- :math:`\dot{Q}_{load}` : heat demand (input 5)
- :math:`P_{nom}` : effective power of the heat pump under current conditions (input 7)
- :math:`\dot{Q}_{loadef}` : heat production at the current timestep

The refrigerant flow rate is then calculated using this effective load.

.. math::

   \dot{m}_{ref} = \frac{\dot{Q}_{load\_ef}}{h_{suc} - h_{cond\_out}} \tag{19}

where:
 - :math:`\dot{m}_{ref}`: refrigerant flow rate
 - :math:`h_{suc}`: enthalpy at compressor inlet
 - :math:`h_{cond\_out}`: enthalpy at condenser outlet

Condenser-side water mass flow rate is:

.. math::

   \dot{m}_{cond} = \frac{\dot{Q}_{load\_ef}}{C_{p,water} \cdot \Delta T_{cond}} \tag{20}

where:
 - :math:`\dot{m}_{cond}`: condenser water flow rate
 - :math:`\Delta T_{cond}`: temperature rise in the condenser (water side)

To verify the condenser-side pinch point above the dew line, the refrigerant enthalpy at saturation vapor (dew) point is obtained using:

 - :math:`P = P_{cond}`
 - :math:`Q = 1`

to get enthalpy :math:`h_{bub}`. Then, water temperature at this pinch point is:

.. math::

   T_{bub} = T_{in,cond} + \frac{\dot{m}_{ref} \cdot (h_{bub} - h_{cond\_out})}{C_{p,agua} \cdot \dot{m}_{cond}} \tag{21}

The pinch condition is then checked:

.. math::

   T_{bub} + PP_{cond} > T_{cond}

If this condition is met, the condenser temperature is redefined:

.. math::

   T_{cond} = T_{bub} + PP_{cond} \tag{22}

The cycle is then recalculated starting again from the compressor inlet.

Compressor power consumption:

.. math::

   W_{in,c} = \frac{\dot{m}_{ref} \cdot (h_{dis} - h_{suc})}{\eta_{mec}} \tag{23}

where:
 - :math:`\eta_{mec}`: motor or frequency converter efficiency

Partial load ratio:

.. math::

   PLR = \frac{\dot{Q}_{load}}{\dot{Q}_{max}} \tag{24}

Partial load factor (UNE14825 correction):

.. math::

   PLF = PLR \cdot (PLF_{CC} \cdot PLR) + (1.0 - PLF_{CC}) \tag{25}

Final heat pump power consumption:

.. math::

   W_{in} = W_i \cdot PLF \tag{26}

Pump consumption:

.. math::

   W_{Pu} = PLR \cdot (EvPuPw + CondPuPw) \tag{27}

Total consumption:

.. math::

   W_i = W_{in} + W_{Pu} \tag{28}

Condenser and evaporator powers:

.. math::

   \dot{q}_{cond} = \dot{m}_{ref} \cdot (h_{dis} - h_{cond}) \tag{29}

.. math::

   \dot{q}_{evap} = \dot{m}_{ref} \cdot (h_{suc} - h_{cond}) \tag{30}

Flow rates from energy balances:

.. math::

   \dot{m}_{cond} = \frac{\dot{q}_{cond}}{C_{p,water} \cdot T_{in}} \tag{31}

.. math::

   \dot{m}_{evap} = \frac{\dot{q}_{evap}}{C_{p,water} \cdot (T_{in} - T_{set})} \tag{32}

Output temperatures:

.. math::

   T_{out,cond} = T_{in,cond} + \frac{\dot{q}_{cond}}{C_{p,water} \cdot \dot{m}_{cond}} \tag{33}

.. math::

   T_{out,evap} = T_{in,evap} - \frac{\dot{q}_{evap}}{C_{p,water} \cdot \dot{m}_{evap}} \tag{34}

Unmet demand:

.. math::

   Unmet\ demand = \dot{q}_{load} - \dot{q}_{evap} \tag{35}

Compressor thermal losses:

.. math::

   Q_t = \frac{\dot{m}_{ref} \cdot (h_{dis} - h_{suc})}{\eta_{mec}} \cdot q_{loss} \tag{36}

Energy Efficiency Ratio (EER):

.. math::

   EER = \frac{\dot{q}_{evap}}{W_i} \tag{37}

