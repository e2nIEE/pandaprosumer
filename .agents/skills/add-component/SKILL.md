---
name: add-component
description: Scaffold a brand-new pandaprosumer sector-coupling component (a new "model" such as a boiler, heat pump, chiller, storage, or converter) end to end. Invoke this whenever the user wants to add a new component/model/element to the library — it walks the ~6 files a model needs, wires a producer correctly into the FluidMix coupling so it does not leak energy, and points at the right sibling skills for parameters, tests, and docs. Use it even if the user only says "add a new model for X" without listing the files.
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Add a new component (model) to pandaprosumer

Adding a component is not one file — it is a consistent set of files plus the
coupling wiring that lets the component exchange heat with demands and storage
without leaking energy. Getting one file right and forgetting another produces a
component that imports fine but silently misbehaves at simulation time. This skill
is the checklist and the "why" behind each step.

Before starting, read an existing component of the closest type with the
**analyse-model** skill — you will copy its structure. Good templates:

- **Producer → demand** (boiler-like): `gas_boiler` or `electric_boiler`.
- **Heat pump family** (has a compressor floor `min_p_comp_kw`): `heat_pump`.
- **Storage**: `stratified_heat_storage`.
- **Cooling**: `chiller`, `dry_cooler`.

Copying the nearest sibling and adapting it is far safer than writing from scratch,
because it inherits the coupling wiring and the test scaffolding already proven for
that shape.

## The files to create (all of them)

For a new component `<model>`:

1. `src/pandaprosumer/element/<model>.py` — the static-parameter element definition.
2. `src/pandaprosumer/controller/data_model/<model>.py` — the inputs and outputs
   (time series the controller consumes/produces).
3. `src/pandaprosumer/controller/models/<model>.py` — the controller: the physics
   and control logic each timestep.
4. `src/pandaprosumer/create.py` → add `create_<model>` (arguments + full docstring
   giving each parameter's meaning, default, valid range, and optionality).
5. `src/pandaprosumer/create_controlled.py` → add `create_controlled_<model>`.
6. `doc/source/elements/<model>.rst` — physics, equations, references, and the
   Parameter / Description / Unit tables. Add it to the elements toctree.
7. `tests/models/test_<model>.py` — unit tests, plus at least one integration test
   in `tests/integrations/` if the component couples to others.

Name every parameter and IO per `doc/source/about/units.rst` (see analyse-model).
Use the **models-parameters** skill's rules when defining each element parameter —
in particular, remember new element columns are appended at the end and the
`test_define_element*` tests pin column order positionally.

## Wiring a producer into the FluidMix coupling (do not skip)

If the component is a producer that maps to a Heat Demand (or storage) via
`FluidMixMapping`, it must respect the coupling contract or it will leak or
misreport energy. The dispatch logic lives in
`BasicProsumerController._merit_order_mass_flow` in
`src/pandaprosumer/controller/mapped.py`. In the new controller you must:

1. **Honor `overflow_strategy`.** When the producer is pinned to its thermal floor
   (`min_q_kw` / `min_p_kw` / `min_p_comp_kw`) but the demand requests less mass
   flow, there is a surplus to dispatch. Read the element's `overflow_strategy` with
   `self._get_element_param(prosumer, 'overflow_strategy')` (default to `'cap'` on
   NaN/None) and pass it into `_merit_order_mass_flow`. The strategies:
   - `'dump_proportional'` (default) — split surplus across responders in proportion
     to their requests. No energy leak.
   - `'dump_on_last'` — all surplus to the lowest-priority responder.
   - `'cap'` (legacy) — drops the surplus silently. Boilers hide this by raising
     `t_out_c`; a heat pump cannot, so it leaks (and the warning fires).
2. **Add `overflow_strategy` as an element parameter** (step 1 above) so it can be
   configured, following the models-parameters ordering rules.
3. **Call `self._check_fluid_mix_balance(...)` right before `self.finalize(...)`**
   so that `EnergyLeakWarning` fires if the dispatched mass flow diverges from the
   producer's recorded mass flow. This is your safety net — never remove it.

The four interface invariants the coupling must satisfy every timestep
(feed/return temperature, mass flow, delivered power) are spelled out in the
**write-tests** skill and in `AGENTS.md`; your integration test must assert them
with `_assert_interface_consistent`.

## Register the component so it can be instantiated

`create_<model>` and `create_controlled_<model>` are how users build the component.
Follow the pattern of the sibling you copied for how the element, controller, and
any mappings are registered. Verify a minimal `create_<model>(...)` call works in
the venv before writing the physics-heavy tests.

## Recommended order of work

1. **analyse-model** on the closest existing component — learn the shape you will copy.
2. Design the physics and name the parameters/IO (`units.rst`).
3. Create the element, data_model, and controller files.
4. Add `create_<model>` / `create_controlled_<model>` (**models-parameters** rules).
5. Wire the FluidMix coupling (`overflow_strategy` + `_check_fluid_mix_balance`) if
   it is a producer.
6. **write-tests** — unit tests (including invalid/optional/0/negative/nan inputs)
   and an integration test asserting the interface invariants.
7. **write-documentation** — the `.rst` with physics, equations, and the IO/parameter
   tables; add it to the toctree.

## Done criteria

- The component imports and a minimal `create_<model>` succeeds in the venv.
- All six/seven files exist and are mutually consistent.
- If it is a producer: it honors `overflow_strategy`, calls `_check_fluid_mix_balance`,
  and its integration test asserts the four interface invariants with no unexpected
  `EnergyLeakWarning`.
- Unit + integration tests pass; docs build (`cd doc && make clean html`, no new
  warnings/errors).

If the user's component does not fit any existing shape (e.g. a genuinely new
coupling), stop and confirm the design with them before scaffolding — the coupling
wiring is the part most likely to need a human decision.
