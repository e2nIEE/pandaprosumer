---
name: write-tests
description: Write or extend unit, integration, or end-to-end tests for pandaprosumer. Invoke this whenever the task involves adding test cases, reproducing a bug as a test, modifying existing tests, or updating expectations/assertions — especially for a model's physics, a producer→demand coupling, or a new element parameter. Knows the repo's test conventions (physical-consistency asserts, the FluidMix interface helper, the create_period positional trap, EnergyLeakWarning).
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Write tests

Run tests inside the project's virtual environment with pytest. Each model has
exactly one unit-test file at `tests/models/test_<model>.py`; couplings between
models live in `tests/integrations/`. Use **analyse-model** first if you are not
sure how the model under test behaves.

## Aim for exhaustiveness

- **Unit (`tests/models/`)**: cover many parameter and input combinations,
  including invalid ones. Parametrize `test_define_element_with_parameters` over
  valid, invalid, and optional parameter values; parametrize
  `test_controller_run_control` over inputs including Generic vs Fluid inputs and
  `0`, negative, and `nan` values.
- **Integration (`tests/integrations/`)**: connect the model to demands, storage,
  or other producers and hunt for edge cases.

## Always assert physical consistency

Tests should not just check that code runs — they should check the physics holds:
energy balance, mass balance, and equal temperature on both ends of a connection.

For a producer mapped to a demand across the **FluidMix** interface, four
invariants must hold every timestep:

- `producer.t_out_c == demand.t_in_c`   (feed temperature)
- `producer.t_in_c  == demand.t_out_c`   (return temperature)
- `producer.mdot_*_kg_per_s == demand.mdot_kg_per_s`  (mass flow; for multiple
  responders, `producer.mdot == sum(responder.mdot)`)
- `producer.q_*_kw  == demand.q_received_kw`  (delivered thermal power)

Do not re-derive these by hand — `tests/integrations/test_overflow_strategy_consistency.py`
provides the helper `_assert_interface_consistent`; use it and follow the examples
there. Any test for a new producer that maps to FluidMix responders should assert
all four via that helper.

## EnergyLeakWarning

`EnergyLeakWarning` (defined in `src/pandaprosumer/controller/mapped.py`) fires when
a producer's mass flow diverges from the sum dispatched at the FluidMix interface.
Today it only triggers for a Heat Pump with `overflow_strategy='cap'` when
`min_p_comp_kw` is hit. If you write a test that intentionally exercises that
combination, expect the warning: either assert on it with
`pytest.warns(EnergyLeakWarning)` or silence it with
`warnings.simplefilter("ignore", EnergyLeakWarning)`. Getting an unexpected
`EnergyLeakWarning` in any *other* test usually means a real coupling bug, not a
test that needs silencing.

## The `create_period` positional-argument trap

In integration tests, call `create_period` with **positional** arguments:

```python
period = create_period(prosumer, resol, start, end, 'utc', 'default')
```

Passing `name='default'` as a keyword fails on the pinned pandapower because
`_set_entries` no longer accepts arbitrary kwargs. Match the positional style used
throughout the existing suite.

## Unit-testing controller internals directly

To test a controller's logic without building full mappings, stub the demand and
drive the controller by hand:

```python
controller.t_m_to_deliver = lambda x: (t_out_c, t_in_c, [mdot1, mdot2, ...])
controller.time_step(...)
controller.control_step(...)
```

Use this for model-level unit tests; use full `run_timeseries` for integration
tests.

## Done criteria

- All new tests pass in the venv, and coverage does not decrease.
- Edge cases (invalid/optional/0/negative/nan) are covered.
- Physical consistency (energy, mass, temperatures, FluidMix invariants) is
  asserted, not assumed.

Ask the user when a physical expectation is genuinely ambiguous rather than
guessing an assertion.
