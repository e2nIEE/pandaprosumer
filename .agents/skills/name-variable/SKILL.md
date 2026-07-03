---
name: name-variable
description: Find a name for a variable, parameter, or model input/output
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Naming Skill

For naming variables and parameters or model input/output, always read the conventions in /doc/source/about/units.rst.
In it 'parameter' is the meaning of the physical parameter for a human, 'variable' is the way it should be named in the parameters and variables names, 'unit' is the symbol that should be used for its unit.

## Error Handling
- If required files are missing, inform user and suggest creation
