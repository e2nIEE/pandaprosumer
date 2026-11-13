---
name: analyse-model
description: Understand how a pandaprosumer model (component) is implemented — its physics, parameters, inputs/outputs, and where every piece lives across the codebase. Invoke this before explaining a model to the user, before editing its parameters or physics, before documenting it, and before writing tests for it. It is the canonical map of a model's anatomy that the other pandaprosumer skills build on.
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Analyse a model

A pandaprosumer "model" (a sector-coupling component such as a Gas Boiler, Heat
Pump, Chiller, Stratified Heat Storage, ...) is not a single file. Its definition
is spread across five locations that must stay consistent. To understand a model
`<model>`, read all of them — each answers a different question:

| File | What it defines |
|------|-----------------|
| `src/pandaprosumer/controller/models/<model>.py` | The **physics / control logic**: how inputs become outputs each timestep. |
| `src/pandaprosumer/controller/data_model/<model>.py` | The **inputs and outputs**: time-series data the controller consumes and produces. |
| `src/pandaprosumer/element/<model>.py` | The **static parameters**: the element's fixed configuration columns. |
| `src/pandaprosumer/create.py` (`create_<model>`) and `create_controlled.py` (`create_controlled_<model>`) | How a model is **instantiated**. The docstrings are the source of truth for each parameter's meaning, default, valid range, and whether it is mandatory or optional. |
| `doc/source/elements/<model>.rst` | The **Sphinx documentation**: physics, equations, references, and the parameter/IO tables. |

Tests are the sixth place a model is pinned down, and reading them is often the
fastest way to learn the *actual* contract:

- `tests/models/test_<model>.py` — unit tests for the model in isolation.
- `tests/integrations/` — the model coupled to others (demands, storage, ...).

## Naming conventions

Parameter, variable, and input/output names follow the conventions in
`doc/source/about/units.rst`. In that table: **parameter** is the human meaning of
the physical quantity, **variable** is how it must be spelled in code (the column /
attribute name), and **unit** is the symbol used for its unit (e.g. `_kw`, `_c`,
`_kg_per_s`). Consult it whenever you read or introduce a name so the model stays
consistent with the rest of the library.

## The coupling contract (read this for any producer)

Most producers deliver heat to a demand (or to a storage) across a **FluidMix**
interface, and there are hard invariants on that boundary every timestep (feed/
return temperatures, mass flow, delivered power). If the model you are analysing
maps to a `FluidMixMapping`, the coupling rules — the four interface invariants,
`overflow_strategy`, `_merit_order_mass_flow`, and `EnergyLeakWarning` — are
documented in the repository's `AGENTS.md` under "Producer / responder
consistency". Read that section; it explains behaviour that the per-model files
alone do not make obvious.

## If files are missing

If one of the expected files does not exist for a model, say so explicitly rather
than guessing — a missing `data_model` or `.rst` usually means the model is
incomplete, and that is worth reporting to the user.
