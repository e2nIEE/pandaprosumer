.. _known_issues:

*************
Known Issues
*************
The following points are identified challenges, which are currently a work in progress and under active development.

Supervisory Control 
=======================
Implementing a supervisory control logic that selects the appropriate prosumer controller—such as a heat pump or gas boiler—based on predefined rules (e.g., gas prices and energy demand. In the future, this logic will be extended to also incorporate generic mapping, considering both fluid properties (:ref:`FluidMixMapping <FluidMixMapping>`) as well as energy flow based mappings (:ref:`GenericMapping <GenericMapping>`)to connect prosumer controllers.
This approach enables flexible switching between prosumer controllers to effectively meet demand.

.. figure:: /pics/Supervisor.png
   :width: 50em
   :align: center

   Conceptualized Supervisory Control Logic


Connection to DH network
=============================================

Integrating multiple thermal energy producers—such as heat pumps, gas boilers, PV units etc. to model a single pandapipes network presents challenges such as setting fluid parameters and implementing a control strategy.


.. figure:: /pics/pp_mapping.png
   :width: 50em
   :align: center

   Conceptualized connection with pandapipes network (Source: EIFER)


Parallel Control Logic with Generic Mapping
==================================================

As part of the ongoing development, a parallel control logic designed to coordinate energy flows by flexibly switching between multiple prosumer controllers is under development. This setup relies on a **generic 1:1 mapping** that models the transfer of energy (**thermal and electric**) between interconnected components.

Currently, this logic is being applied in a use case handled by the **University of Ljubljana**, where the system must decide which **prosumer controller** (and which mode of energy input) should be used to satisfy the heat demand using a combination of a **Combined Heat and Power (CHP)** unit and a **Booster Heat Pump (BHP)**. The control must determine whether to:

- Use the **thermal output from the CHP** to meet the heating demand directly and supplement it with the **BHP** as needed.
- Use the **electrical output from the CHP** to power the **BHP**.
- Draw **electricity from the external grid** to power the **BHP** independently.

This decision-making is enabled by **mode-based logic within the BHP**, which selects the operating mode depending on the type and source of input energy.

A flexible parallel logic would allow for **dynamic switching between thermal and electrical energy paths** to meet demand in an intelligent way considering system constraints, energy prices, and energy availability.

.. figure:: /pics/parallel.png
   :width: 50em
   :align: center

   Conceptualized parallel use case implementation 




