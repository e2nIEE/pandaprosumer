---
name: write-documentation
description: Write documentation for pandaprosumer
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Write documentation Skill

Pandaprosumer is an open-source library for modeling energy systems.
It should be easy to understand for new contributors, as well as for energy engineers who want to model a system without being expert in programming.

Thus the documentation of the library should be exhaustive and still clear for someone not yet familiar with it.

The documentation is located in /doc/source in .rst files.
It is build with sphinx and hosted on readthedocs.

Before writing the documentation for a model, always use the skill /analyse-model first to understand how it is implemented.

In /doc/sources/elements, there is the documentation of every models of the library.
Each models should be documented in details, especially the models parameters and the equations used to model the physics.
The description of the models parameters should include which values are valid for each parameters, which one are optional and if some combinations of parameters are invalid (for example the capacity of the storage should be given either in kg or in kWh).
The description of the models physics should include how are managed the edge cases (for example what happens in the case the maximum power / maximum temperature is reached).
Also include what can cause potential errors and limits like potential issues or not implemented features.

Describe the models as they are implemented.
Do not compare different versions of the model ('before fix' / 'after fix') but describe the latest implementation only.

The tables listing the Input static data, Input times series and Output time series should have the columns: "Parameter", "Description", "Unit".

Be especially cautious when working with math formulas and subscripts: for example :math:`T_{\text{out}_\text{cond}}`

To write bullet points, you need to include a blank line before and after. For example:


```
The parameters are:

- ``min_q_kw = 20`` (minimum power)
- ``max_t_out_c = 70`` (maximum output temperature)

```

Do not write example usage code in the documentation, but include a link to the interactive tutorial on Binder: https://mybinder.org/v2/gh/e2nIEE/pandaprosumer/develop?urlpath=%2Fdoc%2Ftree%2Ftutorials

Edit the existing documentation. Do not duplicate it in the same file.


After editing the documentation source, build it with sphinx:

* use the virtual environment: if sphinx is not installed in it, warn the user that the optional dependencies should be installed.
* In the /doc folder, execute `make clean; make html` and check for any errors and warnings in the build process and try to correct them.
* When successful, inform the user that they can open the file /doc/build/index.html in their browser to see the doc.

## Error Handling
- If required files are missing, inform user and suggest creation
- If documentation build fails, suggest sphinx dependency installation
