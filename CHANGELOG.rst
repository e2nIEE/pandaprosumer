[0.1.3] - 2025-05-02
-------------------------------
- [ADDED] `check_levels` function: ensures that all controllers in a prosumer have the same execution level (with exceptions for ConstProfile and pandapower/pandapipes).
- [ADDED] `check_controllers_orders` function: validates that initiator controllers execute before responder controllers, based on level and order attributes.
- [ADDED] `check_mappings_orders` function: checks that controller mapping orders are continuous and start from zero.
- [ADDED] `check_order` argument to the prosumer constructor: allows enabling or disabling all order validation mechanisms.
- [UPDATED] Tests and tutorials to comply with new order checking mechanisms (minor fixes for compatibility).
- [FIXED] Incorrect reference to "pandapipes" in `CONTRIBUTING.rst` now correctly mentions "pandaprosumer".
- [CHANGED] Unit correction in `dry_cooler.rst` documentation.

[0.1.2] - 2025-04-22
-------------------------------
- [FIXED] ice chp documentation
- [FIXED] period handling in documentation
- [FIXED] compatible python version in pyproject.toml
- [CHANGED] directory of tests folder - so standard installation does not install tests
- [ADDED] Contributing.rst - contribution guidelines

[0.1.1] - 2025-04-21
-------------------------------
- [FIXED] image and text in chiller demand tutorial
- [ADDED] added known issues
- [ADDED] added link to tutorials in README
- [FIXED] missing images and formatting in documentation

[0.1.0] - 2025-04-17
-------------------------------
- first release of pandaprosumer



