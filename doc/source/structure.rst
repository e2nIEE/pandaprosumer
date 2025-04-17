.. _structure:

Structure
==============================


pandaprosumer as a software tool is developed to model custom prosumer components within multi-energy systems.
The figure illustrates the envisioned future application of pandaprosumer in simulating the interaction of electricity, heat, and gas grids, along with sector-coupling infrastructures such as Power-to-Gas (P2G) and Combined Heat and Power (CHP) systems. 

.. figure:: /pics/MES.png
    :width: 120em
    :alt:  Conceptualized integration of the pandaprosumer with multi-energy grids and infrastructures
    :align: center


    Conceptualized integration of the pandaprosumer with multi-energy grids and infrastructures

A prosumer in the pandarosumer is a container object that encapsulates the controller, elements, period and mapping required to model the sector coupling component. The core of this setup is the prosumer controller, which facilitates the interactions between elements containing the static data, time-series data inputs (e.g., heat demand profiles, source temperature profiles), and natural constants (e.g., conversion efficiencies).

In the context of pandaprosumer, the ConstProfileController is a specialized controller that is configured to be initialized and executed first to read from a data source (in a user-defined file format e.g., CSV, Excel etc.) and generate a time-series profile. This ensures that the downstream controllers receive time-series inputs to invoke their respective controller logic. The ConstProfileController does not perform internal calculations and simply inherits the prosumer's mapping logic to direct it's output to other controllers. 

pandaprosumer leverages the control loop of pandapower and builds upon it to manage controller interactions for energy systems. At its core, the run_timeseries function handles the execution of the controllers over a defined period. It initializes time series variables, runs the control logic in the control step of each controller and the loop repeatedly evaluates whether each controller has converged. The loop executes control steps and recalculates power flow until convergence is reached or a set iteration limit is crossed. Controller-specific initialization and finalization routines are also supported.

Mappings define data connections between controllers and are described in detail in :ref:`Mappings <mappings>`.

.. figure:: /pics/prosumer_structure.PNG
    :width: 120em
    :alt: Prosumer Structure
    :align: center

    Prosumer Structure



.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - **Prosumer**
     - **Example Content**

   * - **controller (3 entries)**
     - • ConstProfileController  
       • HeatPump  
       • HeatDemand

   * - **mapping (3 entries)**
     - • `0`: Element-wise map (0 → 1)  
       • `1`: Element-wise map (0 → 2)  
       • `2`: Fluid mix (1 → 2)

   * - **period (1 entry)**
     - • name: `default`  
       • start: `YYYY-MM-DD HH:MM:SS`  
       • end: `YYYY-MM-DD HH:MM:SS`  
       • step: `3600s`  
       • timezone: `UTC`

   * - **heat_pump (1 entry)**
     - **heat_pump**:  
       delta_t_evap_c = 5.0,  
       carnot_efficiency = 0.5,  
       cond_fluid = water  
       - Time 00:00 → output_kw = A  
       - Time 01:00 → output_kw = B

   * - **heat_demand (1 entry)**
     - **heat_demand**:  
       scale = X,  
       temp_in = Y,  
       temp_out = Z  
       - Time 00:00 → demand_kw = M  
       - Time 01:00 → demand_kw = N

   * - **time_series (2 entries)**
     - • `time series[0]`: heat_pump  
       • `time series[1]`: heat_demand


**Flowchart: Heat Pump and Heat Demand Element Interaction**

.. figure:: /pics/hp_hd.png
    :width: 40em
    :alt: Operation of heat pump and heat demand controllers within the pandaprosumer framework
    :align: center

    Operation of heat pump and heat demand controllers within the pandaprosumer framework



