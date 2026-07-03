# Pandaprosumer

## About pandaprosumer

pandaprosumer is an open-source modeling tool, that enables modeling of sector-coupling prosumer components in energy systems.
The framework comes with a library of different predefined sector-coupling components, but also enables users to create
own components based on the pandaprosumer framework.
It also comes with a logic to simulate different combinations of these components with each other and different
inputs (e.g. a heat demand timeseries) and outputs (e.g. power load timeseries on the powergrid).

It extends the libraries `pandapower` and `pandapipes`.

For running python code, always use the virtual environment.

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

Defined in `src/pandaprosumer/controller/mapped.py`. Emitted by
`_check_fluid_mix_balance` when `producer.mdot != sum(dispatched_mdot)`
at the FluidMix interface. Currently fires only for HP +
`overflow_strategy='cap'` + `min_p_comp_kw` triggered. If you write a
test that intentionally exercises that combination, expect the warning
and either assert on it (`pytest.warns(EnergyLeakWarning)`) or silence
it (`warnings.simplefilter("ignore", EnergyLeakWarning)`).

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
| `/models-parameters` | If the user request to edit/add/remove a parameter to any model:  must invoke the skill. |
| `/name-variable` | If the task requires to choose a name or renaming for a variable, parameter, model input or output:  must invoke the skill. |
| `/write-tests` | If the task requires to write some tests,  Adding new test cases, Modifying existing test cases, Updating test expectations or assertions:  must invoke the skill. |
| `/analyse-model` | If the task requires to understand how a specific model is implemented, for example to be use for an other task, to explain how it works to the user, to check/update the documentation:  must invoke the skill. |
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
    B --> C[/name-variable]
    C --> D[/models-parameters]
    D --> E[/write-tests]
    E --> F[/write-documentation]
```

**Step-by-Step**:

1. **Analyse Model**: `/analyse-model` → Understand current gas boiler implementation
2. **Name Parameter**: `/name-variable` → Choose `safety_factor` (follows conventions)
3. **Add Parameter**: `/models-parameters` → Add to element, controller, and create functions
4. **Write Tests**: `/write-tests` → Add parameter validation tests and edge cases
5. **Document**: `/write-documentation` → Update RST docs with parameter description

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
    A[User Request: New solar collector model] --> B[Design Physics]
    B --> C[/name-variable for all parameters]
    C --> D[Implement Model]
    D --> E[/models-parameters for all parameters]
    E --> F[/write-tests for all functionality]
    F --> G[/write-documentation complete physics]
```

**Step-by-Step**:

1. **Design Physics**: Define mathematical model and parameters
2. **Name Parameters**: `/name-variable` → Choose names for all parameters following conventions
3. **Implement Model**: Create controller, element, and data model files
4. **Add Parameters**: `/models-parameters` → Add all parameters to create functions
5. **Write Tests**: `/write-tests` → Comprehensive test suite (unit, integration, edge cases)
6. **Document**: `/write-documentation` → Complete physics description, parameters, examples

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
2. **Parameter Management**: Always use `/name-variable` before `/models-parameters`
3. **Documentation**: Always use `/analyse-model` before `/write-documentation`
4. **Testing**: Use `/write-tests` both before (reproduction) and after (validation) fixes

### Skill Dependency Rules

- **Prerequisite Skills**: Some skills depend on others being completed first
  - `/models-parameters` requires `/name-variable` for new parameters
  - `/write-documentation` requires `/analyse-model` for accuracy
  - `/write-tests` benefits from `/analyse-model` for comprehensive coverage

- **Independent Skills**: These can be used standalone
  - `/analyse-model` (pure analysis)
  - `/name-variable` (naming only)

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
