.. _solar_thermal_element:

=================
Solar Thermal
=================

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A solar thermal system consists of an element and a controller.
    The element defines the collector’s physical parameters, while the controller governs the thermodynamic logic.

    The ``create_controlled`` function creates both and connects them.

Create Controlled Function
=============================

.. autofunction:: pandaprosumer.create_controlled_solar_thermal


Input Static Data
--------------------

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "collector_area", "Area of a single collector", "m²"
    "number_collectors", "Number of collectors in the field", "N/A"
    "optical_efficiency (a₀)", "Optical efficiency factor", "-"
    "thermal_losses (a₁)", "First-order thermal loss coefficient", "W/(m²·K)"
    "second_thermal_losses (a₂)", "Second-order thermal loss coefficient", "W/(m²·K²)"
    "flow_rate", "Nominal mass flow rate per collector", "kg/h"
    "test_specific_heat", "Specific heat used in test conditions", "kJ/(kg·K)"
    "use_specific_heat", "Specific heat of working fluid", "kJ/(kg·K)"
    "piping_length", "Length of connecting pipes", "m"
    "piping_diameter", "Inner diameter of pipes", "m"
    "piping_thickness", "Pipe wall thickness", "m"
    "piping_conductivity", "Thermal conductivity of pipe material", "W/(m·K)"
    "incidence_angle", "Incidence angle modifier at 50°", "-"
    "collector_slope", "Slope of the collector field", "deg"
    "series", "Number of collectors in series", "N/A"
    "in_service", "Indicates if the solar thermal system is in service", "N/A"


Input Time Series
-------------------

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "beam_solar_radiation_w_m2", "Beam solar radiation on collector surface", "W/m²"
    "diffuse_solar_radiation_w_m2", "Diffuse solar radiation", "W/m²"
    "ground_solar_radiation_w_m2", "Ground-reflected solar radiation", "W/m²"
    "radiation_incidence_angle_deg", "Angle of incidence of solar radiation", "deg"
    "ambient_temperature_C", "Ambient temperature", "°C"
    "inlet_temperature_C", "Inlet fluid temperature", "°C"
    "inlet_mass_flow_rate_kg_h", "Inlet mass flow rate", "kg/h"


Output Time Series
-------------------

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "outlet_temperature_C", "Outlet fluid temperature", "°C"
    "outlet_flow_rate_kg_h", "Outlet mass flow rate", "kg/h"
    "energy_gain_W", "Thermal energy gain of the collector field", "W"


Mapping
-----------------------

The Solar Thermal model can be mapped using :ref:`GenericMapping <GenericMapping>` and :ref:`FluidMixMapping <FluidMixMapping>`.


Model
=======

.. autoclass:: pandaprosumer.controller.models.SolarThermalController
    :members:

The Solar Thermal controller implements the thermodynamic model of a collector field.
It accounts for **optical efficiency**, **thermal losses**, and **correction factors** for capacitance, series connection, and piping.

    **Collector Initial Parameters**

    The effective parameters are derived from test values:

    .. math::

       FR(\tau \alpha)_n = \frac{a_0}{1 + \frac{3.6 \cdot a_1}{2 \cdot m_{test} \cdot c_{p,test}}}

    .. math::

       FRU_L = \frac{a_1}{1 + \frac{3.6 \cdot a_1}{2 \cdot m_{test} \cdot c_{p,test}}}

    .. math::

       FRU_{L2} = \frac{a_2}{1 + \frac{3.6 \cdot a_1}{2 \cdot m_{test} \cdot c_{p,test}}}

    **Capacitance Correction Factor**

    .. math::

       r_{cap} = \frac{m \cdot c_p}{n_c \cdot a_c} \cdot \frac{1 - \exp\left(-\frac{3.6 \cdot n_c \cdot a_c \cdot f_{finul}}{m \cdot c_p}\right)}{3.6 \cdot FRU_L}

    with

    .. math::

       f_{finul} = -\frac{m \cdot c_p}{3.6 \cdot a_c} \ln\left(1 - \frac{3.6 \cdot FRU_L \cdot a_c}{m \cdot c_p}\right)

    **Series Connection Correction Factor**

    .. math::

       r_{series} = \frac{1 - (1 - k)^{n_{series}}}{n_{series} \cdot k}, \quad k = \frac{3.6 \cdot n_c \cdot a_c \cdot FRU_L}{m \cdot c_p}

    **Piping Correction Factor**

    .. math::

       U_p = \frac{2 k_{ins}}{(d_{pipe} + 2 t_{ins}) \ln\left(1 + \frac{2 t_{ins}}{d_{pipe}}\right)}

    .. math::

       U_{ap} = U_p \cdot l_{pipe} \cdot (d_{pipe} + 2 t_{ins})

    .. math::

       r_0 = \frac{1}{1 + \frac{3.6 U_{ap}}{m c_p}}, \quad
       r_1 = \frac{1 - \frac{3.6 U_{ap}}{m c_p} + \frac{2 U_{ap}}{a_c FRU_L}}{1 + \frac{3.6 U_{ap}}{m c_p}}, \quad
       r_2 = r_1

    **Radiation Incidence (IAM Effect)**

    The absorbed solar radiation is corrected by incidence angle modifiers:

    .. math::

       b_0 = \frac{1 - k_{t,\alpha,50}}{1 - \cos(50^\circ) - 1}

    .. math::

       k_{t,\alpha} = 1 - b_0 \left(\frac{1}{\cos(\theta)} - 1\right)

    .. math::

       k_{t,\alpha,diff} = 1 - b_0 \left(\frac{1}{\cos(\theta_{diff})} - 1\right)

    .. math::

       k_{t,\alpha,gr} = 1 - b_0 \left(\frac{1}{\cos(\theta_{gr})} - 1\right)

    .. math::

       G_t = k_{t,\alpha} I_{beam} + k_{t,\alpha,diff} I_{diff} + k_{t,\alpha,gr} I_{gr}

    **Energy Gain**

    Finally, the useful thermal energy is:

    .. math::

       \dot{Q}_{gain} = \dot{m} \cdot c_p \cdot (T_{out} - T_{in})