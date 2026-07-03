---
name: analyse-model
description: Understand a model is working
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Analyse Model Skill

Pandaprosumer has a library of physical models defined in /src/pandaprosumer/controller/models/<model>.py.

Each models have a number of inputs and outputs defined in /src/pandaprosumer/controller/data_model/<model>.py

Each models have a number of static parameters defined /src/pandaprosumer/element/<model>.py

The parameters values can be define when instantiating them via the create and create_controlled functions defined in /src/pandaprosumer/create.py and /src/pandaprosumer/create_controlled.py. Those functions also have docstrings that describe each parameters and the documentation, the default values, and which parameters are mandatory or optional. 

Each model is documented with Sphinx in /doc/source/elements/. The documentation include the description of the physics and equations used and cite references, but also the inputs/outputs and the static elements parameters.

Each model is also tested with pytest in /tests/models/test_<model>.py and is tested in connection with other models in some integrations tests in /tests/integrations/.

Read all those files to understand the implementation of a model.

## Error Handling
- If required files are missing, inform user and suggest creation
