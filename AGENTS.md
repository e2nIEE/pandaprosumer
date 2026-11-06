# Pandaprosumer

## About pandaprosumer

pandaprosumer is an open-source modeling tool, that enables modeling of sector-coupling prosumer components in energy systems.
The framework comes with a library of different predefined sector-coupling components, but also enables users to create
own components based on the pandaprosumer framework.
It also comes with a logic to simulate different combinations of these components with each other and different
inputs (e.g. a heat demand timeseries) and outputs (e.g. power load timeseries on the powergrid).

It extends the libraries `pandapower` and `pandapipes`.

For running python code, always use the virtual environment at `.venv/` in this
checkout (Python 3.10 or 3.11 — `requires-python` excludes 3.12+). Create it once with
every optional extra:

```bash
uv venv --python 3.11 .venv          # or: python3.11 -m venv .venv
uv pip install --python .venv/bin/python -e ".[all,docs,plotting,test]"
.venv/bin/python -m pytest -n auto -q
```

**SenergyNets platform note.** In the SenergyNets platform workspace this checkout sits
next to `panda-energy-system` (cloned as `pandaprosumer` or `pandaprosumer_os`), and this
same `.venv` is the shared test environment for both repos — `panda-energy-system` is
editable-installed into it (`--no-deps`; recipe in `panda-energy-system/CLAUDE.md`). Keep
the checkout on the `senergynets-platform` branch there: the install is editable, so the
checked-out branch is what `panda-energy-system` imports, and `develop` lacks APIs it needs
(e.g. `create_controlled_plant_pump_coupling`).

## Codebase patterns to know

### Producer / responder consistency at the FluidMix interface

Every producer (Gas Boiler, Electric Boiler, Heat Pump, Heat Exchanger,
Stratified Heat Storage, ...) that maps to a Heat Demand via
`FluidMixMapping` must satisfy four invariants on every timestep:

- `producer.t_out_c    == demand.t_in_c`        (feed temperature)
- `producer.t_in_c     == demand.t_out_c`       (return temperature)
- `producer.mdot_*_kg_per_s == demand.mdot_kg_per_s`  (mass flow)
- `producer.q_*_kw     == demand.q_received_kw` (delivered thermal power)

For multi-responder dispatch, the mass-flow invariant generalises to
`producer.mdot == sum(responder.mdot)`. When working on a producer
controller, write at least one integration test asserting all four
invariants (see `tests/integrations/test_overflow_strategy_consistency.py`
for the helper `_assert_interface_consistent` and examples).

### Coupled district-heating networks (energy system)

SenergyNets runs this library inside pandapipes networks through
`panda-energy-system` (its `CLAUDE.md` → "One time step"). Behaviours a change
here must keep, each pinned by a test:

- **A writing network coupling re-converges** (`NetworkCouplingControl.is_converged`):
  a prosumer controller may run again after the coupling wrote its outputs into the
  network, within the same level (an exchanger answers first with a guessed return,
  then reruns once its demand answers). The coupling is unconverged until its mapped
  inputs are the ones it wrote. `tests/energy_system/test_network_coupling_rewrite.py`.
- **Heat exchanger hot-end approach** (`HeatExchangerController.control_step`): the
  secondary outlet slides down with the feed from `min(delta_t_hot_default_c, 5)` above
  the requested outlet, never pinches (a 0.2 K approach wanted 10× the nominal primary
  flow). `tests/models/test_heat_exchanger_cold_feed.py::TestFeedJustAboveTheOutlet`.
- **A starved exchanger keeps its valve open**: a feed too cold to heat with draws the
  flow its demand would need at the nominal primary temperatures, unheated
  (`_starved_primary_flow_kg_per_s`, from what the secondary asked on the step's
  *first* pass — `_first_ask`; later passes of the control loop are not `prosumer.rerun`).
  Closed, a cooled network drew no flow and a heat-led plant never restarted.
  `TestStarvedValveOpen`.
- **A tank charging and discharging at once** through the same connections
  short-circuits (`StratifiedHeatStorageController._short_circuits`, used in
  `_calculate_heat_storage` and `_forced_charge_reapply_request`): the common flow goes
  charge → discharge and return → source, only the net flow crosses the layers, when
  the charge is no colder than the outlet layer. Each outlet booked without the other
  stream lost ~1.7 MWh a day in a game tank.
  `tests/integrations/test_shs_charge_discharge_short_circuit.py`.
- **A forced charge setpoint is the producers' whole flow** to the tank (bypass = the
  rest of what arrives): a fill-rate setpoint caps the source. Leave the charge free
  (`-1`/NaN) when the source should also serve the demand.
- **A tank's remaining capacity is measured on its current layers**
  (`StratifiedHeatStorageController._get_remaining_capacity_kwh`, used by `_is_tank_full` and
  `_reapply_request`), never from `init_layer_temps_c`: a tank that starts full and is drained
  below `min_useful_temp_c` read 0 kWh left and never charged again.
  `tests/models/test_shs_drained_start_full.py`.
- **Solar collectors heat the water their responder gives back**
  (`SolarThermalController._inlet_temperature_c`), not their `inlet_temperature_C` input
  (only a fallback): their pump sets the flow, so on a tank's reapply they take the
  return it really gave back (`t_previous_out_charge_c`), settle a two-value cycle on its
  midpoint, and expose it as `t_booked_return_c` for `_check_return_contract`. Heating
  from a fixed 30 °C inlet, a tank received 327 kWh from collectors that made 212.
  `tests/integrations/test_solar_thermal_stratified_tank_balance.py`.
- **The plant pump coupling fixes the plant's heat on the first pass it delivered on**
  (`PlantPumpCouplingControl`, `MAX_PLANT_WAIT_PASSES`), not the step's first pass.

Check energy balances, not only the KPIs, when touching any of these: plant heat =
circulation-pump heat, `res_heat_consumer.qext_w` = the substations' `q_exchanged_kw`,
a tank's Σ(received − delivered) = its `e_stored_kwh` change (+ small losses). A
discriminating test needs game-like steps (15 min to 1 h): at 5 min most of these
effects vanish.

### `overflow_strategy` and `_merit_order_mass_flow`

When a producer is pinned to its thermal floor (`min_q_kw` / `min_p_kw`
/ `min_p_comp_kw`) but the demand requests less mass flow, there is a
surplus to dispatch. The `overflow_strategy` element parameter on every
producer selects:

- `'dump_proportional'` (default) - split the surplus across responders
  proportionally to their requests. **No energy leak.**
- `'dump_on_last'` - all surplus goes to the last (lowest-priority) responder.
- `'cap'` (legacy) - silently drops the surplus. Boilers compensate by
  raising `t_out_c`; the HP cannot and leaks energy (warning fires).

The dispatch logic lives in
`BasicProsumerController._merit_order_mass_flow` in
`src/pandaprosumer/controller/mapped.py`. Any new producer that maps to
FluidMix responders must:

1. Pass `overflow_strategy` from its element to `_merit_order_mass_flow`
   (read with `self._get_element_param(prosumer, 'overflow_strategy')`,
   default to `'cap'` on NaN/None).
2. Call `self._check_fluid_mix_balance(...)` right before `self.finalize(...)`
   so the `EnergyLeakWarning` fires if dispatched mdot diverges from the
   producer's recorded mdot.

### `EnergyLeakWarning`

Defined in `src/pandaprosumer/controller/mapped.py`. Emitted when energy
is booked on one side of a FluidMix boundary only:

- `_check_fluid_mix_balance` (producer side): `producer.mdot !=
  sum(dispatched_mdot)` (HP + `overflow_strategy='cap'` + `min_p_comp_kw`),
  or the booked `q_kw` differs from what the labelled outlet stream
  carries, `mdot * cp * (t_out - t_in)` (checked when the caller passes
  the fluid's cp).
- `_check_return_contract` (responder side): a responder finalizes on a
  return temperature other than the one it promised (`t_keep_return_c`),
  e.g. a stratified storage whose reapply loop stagnated, or a source on
  another level. A storage wired in parallel with its source (HP -> demand
  and HP -> storage -> demand) must not leak: it requests nothing for a
  responder its source already feeds directly
  (`_responders_served_in_parallel`).

Models must book with the temperatures really exchanged: the received
`input_mass_flow_with_temp`, and returns their responders really give back
(the reapply / `t_previous_*` mechanism), never the requested feed or the
promised return. If you write a test that intentionally exercises a
leaking combination, assert on it (`pytest.warns(EnergyLeakWarning)`) or
silence it (`warnings.simplefilter("ignore", EnergyLeakWarning)`).

### Adding a new parameter to a producer element

When you add a parameter via `create.py`:

- The new column is **appended to the end** of the DataFrame (after
  `in_service`) because `_set_entries` preserves dict insertion order.
- The `test_define_element*` tests pin the exact column order and
  values positionally - you must update both the `expected_columns`
  list and the `expected_values` list, with the new entry at the end.
- Read the parameter in the controller via
  `self._get_element_param(prosumer, '<name>')`. The returned value can
  be `None`, a float, a string, or `np.nan` - handle defensively.

### `create_period` keyword-argument trap

In integration tests, call `create_period` with **positional** args:

```python
period = create_period(prosumer, resol, start, end, 'utc', 'default')
```

Passing `name='default'` as a kwarg fails on pandapower 3.x because
`_set_entries` no longer accepts arbitrary kwargs. The repo's pinned
versions (`pandapower==2.14.11`, `pandapipes==0.10.0`) match the
positional-arg style throughout the test suite.

### Dependency pin gotcha

`pyproject.toml` declares `pandapower>=2.14.11` and `pandapipes==0.12.0`,
but the installed package metadata in some environments asks for
`pandapower>=3.3.0,<3.4.0`. If `_set_entries() got an unexpected
keyword argument 'name'` shows up on import, your venv has the
incompatible version. Roll back with:

```bash
pip install "pandapower==2.14.11" "pandapipes==0.10.0"
```

### Driving a controller directly (model tests)

Many model-level tests bypass mappings by setting

```python
controller.t_m_to_deliver = lambda x: (t_out_c, t_in_c, [mdot1, mdot2, ...])
```

and then calling `controller.time_step(...)` followed by
`controller.control_step(...)`. Use this for unit-testing controller
internals; use full `run_timeseries` for integration tests.

### Sphinx `mapping.rst` title-style quirk

`doc/source/mapping.rst` mixes title underline styles. New sections
inside it should use `===` underline only (h2 level, peer of
"Fluid Mix Mapping"); using `---` underline-only introduces a new
level and triggers `ERROR: Inconsistent title style: skip from level
2 to 4` on the *existing* sections. Run `cd doc && make clean html`
and grep for `warning|error` to validate after doc edits.

## Skills

### STRICT SKILL USAGE REQUIRED

**MUST invoke skills when trigger conditions match** — do not skip based on perceived task simplicity.

Always use your tools when you need more information or to perform a task.
Do not hesitate to invoke skills if it helps answer the user's query.

1. **Mandatory Skill Invocation**: For any task matching a skill's trigger conditions, you MUST explicitly invoke the corresponding skill using the proper JSON format.

2. **Multiple Skills Allowed**: When a task matches multiple skill triggers, you MUST invoke all relevant skills in sequence.

3. **No Direct Implementation**: You are prohibited from implementing skill-related tasks directly without first attempting skill invocation.

### Available skills

| Skill | Trigger |
|-------|---------|
| `/add-component` | If the user wants to add a brand-new component/model/element to the library (e.g. "add a new model for X"): must invoke the skill. It scaffolds all the files and the FluidMix coupling. |
| `/models-parameters` | If the user request to edit/add/remove a parameter to any model: must invoke the skill. (Naming conventions from `units.rst` are handled inside this skill.) |
| `/write-tests` | If the task requires to write some tests,  Adding new test cases, Modifying existing test cases, Updating test expectations or assertions:  must invoke the skill. |
| `/analyse-model` | If the task requires to understand how a specific model is implemented, for example to be use for an other task, to explain how it works to the user, to check/update the documentation:  must invoke the skill. It is the canonical map of a model's anatomy and covers naming conventions. |
| `/write-documentation` | User requests to "document the model", or User asks to "update documentation", or User mentions "add to docs" or "documentation is missing:  must invoke the skill. |

See `.agents/skills/` for skill implementation details.

## Workflow Examples

### Common Task Workflows

The scenarios are just examples of what the users could ask, not actual tasks to perform

#### Adding a New Parameter to a Model

**Scenario**: User wants to add a `safety_factor` parameter to the gas boiler model

**Workflow**:

```mermaid
flowchart TD
    A[User Request: Add safety_factor parameter] --> B[/analyse-model]
    B --> C[/models-parameters]
    C --> D[/write-tests]
    D --> E[/write-documentation]
```

**Step-by-Step**:

1. **Analyse Model**: `/analyse-model` → Understand current gas boiler implementation
2. **Add Parameter**: `/models-parameters` → Choose the name per `units.rst`, then add to element, both create functions, and mind the positional `test_define_element*` column order
3. **Write Tests**: `/write-tests` → Add parameter validation tests and edge cases
4. **Document**: `/write-documentation` → Update RST docs with parameter description

**Expected Output**:

- New parameter available in gas boiler model
- Properly documented with examples
- Fully tested with edge cases covered
- Follows all naming and unit conventions

#### Fixing a Bug

**Scenario**: User reports gas boiler power drops below minimum when temperature constrained

**Workflow**:

```mermaid
flowchart TD
    A[User Report: Power drops below min_q_kw] --> B[/analyse-model]
    B --> C[/write-tests]
    C --> D[Implement Fix]
    D --> E[/write-tests]
    E --> F[/write-documentation]
```

**Step-by-Step**:

1. **Analyse Model**: `/analyse-model` → Understand constraint interaction logic
2. **Reproduce Bug**: `/write-tests` → Create test case that reproduces the issue
3. **Implement Fix**: Modify controller logic to maintain minimum power
4. **Expand Tests**: `/write-tests` → Add parametrized tests for edge cases
5. **Document Fix**: `/write-documentation` → Optional if relevant: Add edge cases section to docs

**Expected Output**:

- Bug fixed in controller logic
- Comprehensive test coverage for the edge case
- Documentation updated with constraint interaction details
- Example scenarios added to help users understand behavior

#### Creating a New Model

**Scenario**: User wants to add a solar thermal collector model

**Workflow**:

```mermaid
flowchart TD
    A[User Request: New solar collector model] --> B[/add-component]
    B --> C[/analyse-model closest sibling]
    C --> D[Scaffold files + FluidMix wiring]
    D --> E[/write-tests for all functionality]
    E --> F[/write-documentation complete physics]
```

**Step-by-Step**:

1. **Scaffold**: `/add-component` → It drives the whole flow: read the closest sibling with `/analyse-model`, create the element/data_model/controller/create files, and wire the FluidMix coupling (`overflow_strategy` + `_check_fluid_mix_balance`) for a producer
2. **Write Tests**: `/write-tests` → Comprehensive test suite (unit, integration asserting the interface invariants, edge cases)
3. **Document**: `/write-documentation` → Complete physics description, parameters, examples

**Expected Output**:

- Fully functional new model
- Complete test coverage (≥ 90%)
- Comprehensive documentation with equations and references
- Follows all framework conventions

#### Updating Documentation

**Scenario**: User finds documentation is missing edge case explanations

**Workflow**:

```mermaid
flowchart TD
    A[User Report: Missing edge case docs] --> B[/analyse-model]
    B --> C[/write-tests for edge cases]
    C --> D[/write-documentation]
```

**Step-by-Step**:

1. **Analyse Model**: `/analyse-model` → Understand edge case behavior
2. **Add Test Cases**: `/write-tests` → Create tests that demonstrate edge cases
3. **Document**: `/write-documentation` → Add edge cases section with examples

**Expected Output**:

- Clear explanation of edge case behavior
- Code examples showing proper usage
- Test cases that verify edge case handling
- Cross-references to related parameters

## Skill Sequencing Guidelines

### When to Use Multiple Skills

1. **Complex Changes**: Use multiple skills in sequence for major modifications
2. **New Components**: Use `/add-component` — it orchestrates `/analyse-model`, file scaffolding, `/write-tests`, and `/write-documentation`
3. **Documentation**: Always use `/analyse-model` before `/write-documentation`
4. **Testing**: Use `/write-tests` both before (reproduction) and after (validation) fixes

### Skill Dependency Rules

- **Prerequisite Skills**: Some skills depend on others being completed first
  - `/models-parameters` and `/add-component` build on `/analyse-model` (understand the model first); naming per `units.rst` is handled inside them
  - `/write-documentation` requires `/analyse-model` for accuracy
  - `/write-tests` benefits from `/analyse-model` for comprehensive coverage

- **Independent Skills**: These can be used standalone
  - `/analyse-model` (pure analysis; also the canonical model-anatomy and naming reference)

### Error Recovery Workflows

**If a skill fails**:

1. Check skill-specific error messages
2. Use `/analyse-model` to understand current state
3. Fix issues manually if needed
4. Re-invoke the failed skill
5. Continue with next skill in workflow

**Example**: Test writing fails due to missing imports

1. `/write-tests` fails with "ImportError: missing module"
2. `/analyse-model` → Identify missing dependency
3. Add required import manually
4. Re-run `/write-tests` → Success
5. Continue workflow

## Best Practices

### Skill Invocation

- **Be Specific**: Provide clear, detailed task descriptions
- **Include Context**: Reference relevant files, parameters, or issues
- **Follow Conventions**: Use framework's naming and structure conventions

### Workflow Design

- **Start Small**: Begin with `/analyse-model` for complex tasks
- **Test Early**: Use `/write-tests` to create reproduction cases first
- **Document Last**: Update documentation after implementation is stable
- **Validate Often**: Run tests after each major change

### Quality Standards

- **Test Coverage**: Aim for ≥ 80% coverage for new features
- **Documentation**: Every parameter and edge case should be documented
- **Naming**: Follow conventions in `/doc/source/about/units.rst`
- **Error Handling**: Skills should provide clear error messages

## Advanced Workflows

### Refactoring Existing Models

**Scenario**: Major refactoring of heat pump controller logic

```mermaid
flowchart TD
    A[Plan Refactoring] --> B[/analyse-model current]
    B --> C[/write-tests current behavior]
    C --> D[Implement Changes]
    D --> E[/write-tests new behavior]
    E --> F[Performance Testing]
    F --> G[/write-documentation changes]
```

### Adding Integration Tests

**Scenario**: Add tests for gas boiler + heat storage interaction

```mermaid
flowchart TD
    A[Design Integration] --> B[/analyse-model both models]
    B --> C[/write-tests individual models]
    C --> D[/write-tests integration scenario]
    D --> E[Run integration tests]
```

### Creating Tutorials

**Scenario**: Create step-by-step tutorial for new users

```mermaid
flowchart TD
    A[Identify Topic] --> B[/analyse-model relevant parts]
    B --> C[/write-tests simple examples]
    C --> D[/write-documentation tutorial]
    D --> E[Review with /analyse-model]
```
