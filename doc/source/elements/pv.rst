.. _pv_element:

=========================
PV Production
=========================

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A PV Production unit consists of an element and a controller.
    The element defines its static / physical parameters,
    while the controller governs the operational logic and enforces
    basic physical constraints on the time series (e.g. horizon, peak power).

    The ``create_controlled_`` function creates both and connects them.

Create Controlled Function
===========================

.. autofunction:: pandaprosumer.create_controlled_pv_production



Input Static Data
-------------------

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "name", "Custom name for the PV system", "N/A"
    "in_service", "Indicates if the PV system is in service", "N/A"
    "latitude", "Site latitude", "deg"
    "longitude", "Site longitude", "deg"
    "peakpower", "Installed PV peak power", "kW"
    "loss", "System losses (e.g. cables, inverter)", "%"


Input Time Series
--------------------

The PV controller expects the following time-series inputs,
typically obtained from PVGIS / pvlib or another external PV model.

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "p_w", "Raw PV active power (before constraints)", "W"
    "poa_direct_w_m2", "Plane-of-array direct irradiance", "W/m²"
    "poa_sky_diffuse_w_m2", "Diffuse sky irradiance", "W/m²"
    "poa_ground_diffuse_w_m2", "Diffuse ground irradiance", "W/m²"
    "solar_elevation_deg", "Solar elevation angle", "deg"
    "temp_air_c", "Ambient air temperature", "°C"
    "wind_speed_m_s", "Wind speed at site", "m/s"
    "solar_rad_reconstr_bool", "Flag indicating reconstructed irradiance", "-"


Output Time Series
---------------------

The PV controller writes a corrected power output and passes through
the other variables. The main difference between input and output is that
``p_w`` is guaranteed to respect physical and system constraints.

.. csv-table::
    :header: "Parameter", "Description", "Unit"

    "p_w", "Corrected PV active power (clamped and clipped)", "W"
    "poa_direct_w_m2", "Plane-of-array direct irradiance", "W/m²"
    "poa_sky_diffuse_w_m2", "Diffuse sky irradiance", "W/m²"
    "poa_ground_diffuse_w_m2", "Diffuse ground irradiance", "W/m²"
    "solar_elevation_deg", "Solar elevation angle", "deg"
    "temp_air_c", "Ambient air temperature", "°C"
    "wind_speed_m_s", "Wind speed at site", "m/s"
    "solar_rad_reconstr_bool", "Flag indicating reconstructed irradiance", "-"


Mapping
----------

The PV production model can be mapped using :ref:`GenericMapping <GenericMapping>`.

Typical usage:

* A :ref:`ConstProfileController <GenericMapping>` (or another data source)
  feeds the above time series into the PV controller.
* The corrected ``p_w`` output can then be mapped to other controllers,
  e.g. a heat demand controller via ``q_received_kw`` (with an optional
  conversion from W to kW).


Model
=================

.. autoclass:: pandaprosumer.controller.models.pv.PvProductionController
    :members:


The PV production controller does **not** compute detailed PV physics itself.
Instead, it receives a pre-calculated active power time series and enforces
basic constraints based on system size and solar geometry.

For each time step, the raw input power :math:`p_\text{raw}` is transformed into
a physically consistent output :math:`p_\text{out}` as follows:

.. math::
    :nowrap:

    \begin{align*}
        &\text{If } \theta_\text{elev} < 0^\circ \quad \Rightarrow \quad p_\text{out} = 0 \\
        &\text{Else } \\
        &\quad p_\text{out} = \max(0,\; p_\text{raw}) \\
        &\quad p_\text{out} = \min\left(p_\text{out},\; P_\text{peak} \cdot 1000\right)
    \end{align*}

Where:

- :math:`\theta_\text{elev}` is the solar elevation angle (``solar_elevation_deg``).
- :math:`P_\text{peak}` is the installed peak power in kW (``peakpower`` element field).
- :math:`p_\text{out}` is written to the ``p_w`` output column.

This ensures that the PV output is always:

- zero when the sun is below the horizon,
- non-negative,
- and never exceeds the installed peak capacity.
