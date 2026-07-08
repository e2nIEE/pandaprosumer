---
name: models-parameters
description: Add, edit, or remove a static parameter (or an input/output) of a pandaprosumer model. Invoke this whenever the user wants to introduce a new element parameter, change a default or valid range, rename a parameter, or delete one — because a parameter is defined in several files at once and they must all stay in sync, and the test suite pins column order positionally so a naive add breaks it.
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Add / edit / remove a model parameter

A model parameter is not defined in one place — it appears in the element
definition, the create functions, the docs, and the tests. If you change it in
some but not all of them, the model becomes inconsistent (or the test suite
breaks). First read the model with the **analyse-model** skill to see its full
anatomy and the file map; this skill assumes you know where each piece lives.

When adding or editing a parameter, choose its name using the conventions in
`doc/source/about/units.rst` (see analyse-model for the parameter/variable/unit
distinction).

## The files that must change together

For a static element parameter of `<model>`:

1. `src/pandaprosumer/element/<model>.py` — the element definition (the column).
2. `src/pandaprosumer/create.py` → `create_<model>` — argument, docstring, and the
   value written into the element.
3. `src/pandaprosumer/create_controlled.py` → `create_controlled_<model>` — the same
   parameter must be threaded through here too. Read and update both create files.
4. `doc/source/elements/<model>.rst` — the parameter table (Parameter / Description /
   Unit) and, if the physics changes, the equations.
5. `tests/models/test_<model>.py` — see the ordering trap below.

An input or output (rather than a static parameter) lives instead in
`src/pandaprosumer/controller/data_model/<model>.py` and is produced/consumed in
`src/pandaprosumer/controller/models/<model>.py`.

## The column-ordering trap (this is where adds break)

A new parameter column is **appended to the end** of the element DataFrame (after
`in_service`), because the underlying `_set_entries` preserves dict insertion
order. The `test_define_element*` tests pin the exact column order **and** values
**positionally** — they compare against an `expected_columns` list and an
`expected_values` list by position. So when you add a parameter you must:

- Append the new column name to the end of `expected_columns`.
- Append its expected value at the same position in `expected_values`.

Putting the new entry anywhere but the end, or updating only one of the two lists,
makes these tests fail with a confusing off-by-one mismatch. When removing a
parameter, delete its entry from both lists (and mind the shift). When renaming,
update the name in `expected_columns` but leave positions alone.

## Reading a parameter back in the controller

Read the value in the controller via
`self._get_element_param(prosumer, '<name>')`. It can return `None`, a float, a
string, or `np.nan` depending on how the element was created — handle all of those
defensively rather than assuming a float.

## What "done" looks like

- The parameter has a sensible default, unless the user is required to supply it.
- It is correctly typed and documented (with valid range / optionality noted in the
  docstring and the `.rst` table).
- It is present and consistent in every file above.
- `tests/models/test_<model>.py` passes, including the positional `test_define_element*`
  cases. Add or update tests with the **write-tests** skill, and update docs with
  **write-documentation**.

If an expected file is missing for the model, say so rather than guessing — it
usually means the model is incomplete.
