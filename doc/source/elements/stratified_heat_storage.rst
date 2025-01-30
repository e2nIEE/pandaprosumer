.. _stratified_heat_storage_element:

========================
Stratified Heat Storage
========================

.. seealso::
    :ref:`Unit Systems and Conventions <conventions>`

.. note::
    A stratified heat storage element should be associated to a
    :ref:`stratified heat storage controller <stratified_heat_storage_controller>` to map it to other prosumers elements

Create Function
=====================

.. autofunction:: pandaprosumer.create_stratified_heat_storage

Input Parameters
=========================

*prosumer.stratified_heat_storage*
 
   
Model
=================

Thermal energy storage means heating or cooling a medium to use the energy when needed later. In its simplest form,
this could mean using a water tank for heat storage, where the water is heated at times when there is a lot of energy,
and the energy is then stored in the water for use when energy is less plentiful. Thermal energy storage can also be
used to balance energy consumption between day and night. Storage solutions include water or storage tanks of ice-slush,
earth or bedrock accessed via boreholes and large bodies of water deep below ground. The Stratified thermal energy
storage model developed is a sensible thermal energy storage that uses a water tank for storing and releasing heat energy.
The stratification inside the storage tank between the hot and the cold water is illustrated in Figure 1 :cite:`Untrau2023`.

.. figure:: stratified_heat_storage_profile.png
    :width: 30em
    :alt: Thermocline region and the temperature profile inside the tank
    :align: center

    The thermocline region and the temperature profile inside the tank :cite:`Untrau2023`

Assuming constant thermo-physical properties for the storage fluid and no heat source inside the storage tank,
the conservation of energy in 1D leads to the following Partial Differential Equation (P.D.E.) with the temperature T as unknown:

.. math::
    :nowrap:

    \begin{align*}
        \rho \cdot \mathrm{C}_{\mathrm{p}} \cdot \mathrm{~A} \frac{\partial \mathrm{~T}(\mathrm{z}, \mathrm{t})}{\partial \mathrm{t}}+\dot{\mathrm{m}} \cdot \mathrm{C}_{\mathrm{p}} \frac{\partial \mathrm{~T}(\mathrm{z}, \mathrm{t})}{\partial \mathrm{z}}=\mathrm{A} \cdot \mathrm{k} \frac{\partial^2 \mathrm{~T}(\mathrm{z}, \mathrm{t})}{\partial \mathrm{z}^2}+\mathrm{U} \cdot \mathrm{P}\left(\mathrm{~T}_{\mathrm{amb}}(\mathrm{t})-\mathrm{T}(\mathrm{z}, \mathrm{t})\right)
    \end{align*}

The first term is the energy accumulation, the second term represents the enthalpy fluxes due to the charge or discharge,
the third term represents diffusion inside the tank and the final term models the heat losses to the environment.
In this equation, the unknown variable is the storage fluid temperature T(z, t) varying in space,
along the vertical coordinate z, and in time t; ρ represents the stored fluid density, Cp the stored fluid
heat capacity and k the stored fluid thermal conductivity.
They are all assumed uniform and constant. A is the tank cross-sectional area, P is its perimeter.
U is the heat transfer coefficient with the environment.

Boundary conditions at the top and bottom of the storage tank:

When Charging:

.. math::
    :nowrap:

    \begin{align*}
        \left.\frac{\partial \mathrm{T}}{\partial \mathrm{z}}\right|_{z=\mathrm{H}}=0 &; T_{z=H}=T_{\text {charge }}
    \end{align*}

When Discharging:

.. math::
    :nowrap:

    \begin{align*}
        \left.\frac{\partial \mathrm{T}}{\partial \mathrm{z}}\right|_{z=\mathrm{0}}=0 &; T_{z=0}=T_{\text {discharge }}
    \end{align*}

During idle time:

.. math::
    :nowrap:

    \begin{align*}
        \left.\frac{\partial \mathrm{T}}{\partial \mathrm{z}}\right|_{z=\mathrm{0}}=0 &; \left.\frac{\partial \mathrm{T}}{\partial \mathrm{z}}\right|_{z=\mathrm{H}}=0
    \end{align*}

.. figure:: stratified_heat_storage_discretization.png
    :width: 25em
    :alt: Finite volume discretization scheme
    :align: center

    Finite volume discretization scheme for the stratified thermal energy storage model :cite:`Untrau2023`

The previous Partial Differential Equation is discretized explicitly with the Euler-forward scheme.
The equations used to solve for the new temperature for the different layers i are presented hereafter:

For the first layer at the bottom of the storage tank:

.. math::
    :nowrap:

    \begin{align*}
        \rho C_p A \Delta z \frac{d T_1}{d t} &= U_1 S_1\left(T_{amb}-T_1\right) + \frac{4}{3} \frac{k^* A} {\Delta z}\left(T_2-T_1\right)               + \dot{m}_c C_p\left(T_2-T_1\right)               + \dot{m}_d C_p\left(T_{\text{return}}-T_1\right)
    \end{align*}

For an intermediate layer i, for i varying from 2 to N-1:

.. math::
    :nowrap:

    \begin{align*}
        \rho C_p A \Delta z \frac{d T_i}{d t} &= U S_l\left(T_{amb}-T_i\right)   + \frac{k^* A}             {\Delta z}\left(T_{i-1}-2*T_i+T_{i+1}\right) + \dot{m}_c C_p\left(T_{i+1}-T_i\right)           + \dot{m}_d C_p\left(T_{i-1}-T_i\right)  \\
    \end{align*}

For the last layer N at the top of the storage tank:

.. math::
    :nowrap:

    \begin{align*}
        \rho C_p A \Delta z \frac{d T_N}{d t} &= U_N S_N\left(T_{amb}-T_N\right) + \frac{4}{3} \frac{k^* A} {\Delta z}\left(T_{N-1}-T_N\right)           + \dot{m}_c C_p\left(T_{\text{charge}}-T_N\right) + \dot{m}_d C_p\left(T_{N-1}-T_N\right)
    \end{align*}

..
    The stratified thermal energy storage model developed by EIFER is based on the model provided by Untrau et al.
    available in literature :cite:`Untrau2023`. The model developed considers a water based thermal energy storage in
    liquid phase and, to simplify the calculation, it approximates in 1-dimensional model. Untrau et al. describe “a new
    discretization scheme applied to the storage tank vertical axis in order to make numerical diffusion negligible and
    better represent the storage tank”.

    The discretization scheme chosen is called Orthogonal Collocation (OC) and it approximates the unknown state variable
    within a differential equation by representing it as a sum of selected trial functions of the integration variable.
    In this scenario, the unknown variable is the temperature inside the storage tank, denoted as :math:`T(z)`, while the
    integration variable refers to the vertical space coordinate z.

    .. math::
        :nowrap:

        \begin{align*}
            T(z) \approx \tilde{T}(z) &= \Sigma_{i=1}^{N} a_i f_i^\text{trial} (z)  \\
        \end{align*}

    Using this method, computing the derivative of the temperature becomes straightforward as it relies on the known
    analytical derivatives of the trial functions. The satisfaction of the differential equation is enforced at carefully
    chosen N collocation points. These points are strategically selected to transform the differential equation into a
    system of algebraic equations, where the coefficients ai associated with each trial function in the sum are the
    unknowns. Usually, polynomials serve as trial functions, and the collocation points are often selected as the roots
    of orthogonal polynomials, hence the name "Orthogonal Collocation." The selection of these collocation points
    significantly influences the convergence and accuracy of the results. Polynomial interpolation ensures a continuous
    representation of the variable across the integration domain. In contrast, finite volumes only yield values at
    discrete discretization points, necessitating linear interpolation to obtain a continuous solution. Notably, for the
    same level of accuracy, fewer points are required and, consequently, less computational time is needed for OC.

    The unknown temperature along the z axis is represented by a linear combination of N interpolating Lagrange polynomials
    lj which are numbered from j = 1 to N. The vertical axis is discretized with N collocation points :math:`z_j`.
    The benefit of Lagrange polynomials lies in their distinctive property: :math:`l_j(z_j) = \delta_{ji}`,
    which is 1 if j = i and 0 if j ≠ i. Thus equation 9 can be written as follows:

    .. math::
        :nowrap:

        \begin{align*}
            T(z) \approx \tilde{T}(z) &= \Sigma_{i=1}^{N} T_i l_i(z)  \\
        \end{align*}

    Then, the steps from :cite:`Ebrahimzadeh2012` are followed for the implementation of Orthogonal
    Collocation for the stratified thermal energy storage.

    1. Normalize the height of the stratified thermal energy storage tank between 0 and 1.
    2. Choose a number :math:`N_\text{int}` of internal collocation points as roots for the orthogonal polynomials.
       The entire collection of collocation points consists of the :math:`N_\text{int}` interior points along with
       the boundary points 0 and 1.


Result Parameters
=========================
