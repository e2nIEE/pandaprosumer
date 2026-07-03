---
name: models-parameters
description: Add edit or remove parameters to a model
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Edit models parameters Skill

Pandaprosumer has a library of physical models defined in /src/pandaprosumer/controller/models/<model>.py.

Each models have a number of inputs and outputs defined in /src/pandaprosumer/controller/data_model/<model>.py

Each models have a number of static parameters defined /src/pandaprosumer/element/<model>.py

The parameters values can be define when instantiating them via the create and create_controlled functions defined in /src/pandaprosumer/create.py (with a function `create_<model>`) and /src/pandaprosumer/create_controlled.py (with a function `create_controlled_<model>`).
Each model have an associated function in both files and both should be read.
Those functions also have docstrings that describe each parameters and the documentation, the default values, and which parameters are mandatory or optional. 

Each model is documented with Sphinx in /doc/source/elements/. The documentation include the description of the physics and equations used and cite references, but also the inputs/outputs and the static elements parameters.

Each model is also tested with pytest in /tests/models/test_<model>.py and is tested in connection with other models in some integrations tests in /tests/integrations/.

When the request from a user required to add or edit or remove a parameter, you need to make sure to update it at all these locations.

For adding a new parameter, choose its name with the skill name-variable.

## Error Handling
- If required files are missing, inform user and suggest creation

## Validation Requirements

- Parameter must have proper default value, unless a value must be provided by the user
- Parameter must be properly typed
- Parameter must be added to all relevant files
- Parameter must be documented