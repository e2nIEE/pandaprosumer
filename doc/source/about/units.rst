.. _conventions:

============================    
Unit System and Conventions
============================

.. toctree::
   :maxdepth: 2

It is advised to keep consistent with these conventions when extending the framework.

Parameters, Variables and Units
------------

- Each variable name should have the corresponding unit at the end and a clear reference.
    * Use: **t_fluid_k**
    * Avoid: only **t** or **t_k**
- Unit and variable names should only use small letters.
    * Use: **kw**
    * Avoid: **kW**
- Parameter name is followed by the adjective. Separation of parameter and adjective in the variable name using underscore.
    * Use: **mdot_nom** as nominal mass flow
    * Avoid: **mdotnom**
- Appropriate length of adjectives in variable names. (examples in the second table)
    * Use: **_ch** , **_nom**
    * Avoid **_charge** , **_n**
- Constraints should always be named with max or min as the prefix.
    * Use: **t_max**
    * Avoid: **max_t**
- When a variable has both adjective and unit, the unit should always come last in the variable name.
    * Use: **mdot_nom_kg_per_s**
    * Avoid: **mdot_kg_per_s_nom**
- For ratios, the numerator and denominator should be part of the variable name.
    * Use: **ratio_q_q_nom_percent**
    * Avoid: **q_ratio**


- **Convention on units**:
.. csv-table::
   :header: "parameter","variable","unit"

    "mass flow","mdot","kg_per_s"
    "thermal energy","q","kj"
    "thermal power","q_dot","kw"
    "electric energy","q_el","kwh"
    "electric power","p_el","kw"
    "temperature","t","k/c"
    "drybulb temperature","t_drybulb","k/c"
    "wetbulb temperature","t_wetbulb","k/c"
    "pressure","p","bar"
    "ratio","ratio","percent"

- **Convention on adjectives**:
.. csv-table::
   :header: "adjective","given name"

    "nominal","_nom"
    "charge","_ch"
    "discharge","_dch"
    "requirement","required"

Functions
----------
- Functions should not have units in the name, this is only advised for variables.
    * Use: **get_t**
    * Avoid: **get_t_k**
- Avoid leading underscores in function names.
    * Use: **calculate_dry_cooler**
    * Avoid: **_calculate_dry_cooler**
- When two separate parameters are calculated by a function, those should be separated with an "and".
    * Use: **t_and_mdot_to_deliver**
    + Avoid: **t_mdot_to_deliver**
- Functions that calculate something should begin with calculate.
    * Use: **calculate_t**
    * Avoid: other descriptions like **compute_t**
- Calling functions should be described with **get** and **set**
    * Use: **get_t**
    * Avoid: other names like **feed_t**
- Function names of parameters that are required should include that information as so.
    * Use: **mdot_required_kg_per_s**
    * Avoid: other adjectives like **mdot_demanded_kg_per_s** or **mdot_toprovide_kg_per_s**
- Function names should avoid redundancies.
    * Use: **t_get_degc**
    * Avoid: **t_feedin_supplied_degc**

Files
------

For file names the conventions are yet to be made.
Until then you can refer to the standard python conventions
`here <https://peps.python.org/pep-0008/#naming-conventions>`_ and those of pandapipes.

One thing to note already is the advice to include what controller model your component is based on,
as in **base_booster_heat_pump** for example.