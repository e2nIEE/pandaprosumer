---
name: write-tests
description: Write units, integrations or end to end tests
license: MIT
compatibility: Python 3.10+
user-invocable: true
---

# Write tests Skill

Use the virtual environment and pytest to run tests.

Each pandaprosumer model is tested in /tests/models/test_<model>.py and is tested in connection with other models in some integrations tests in /tests/integrations/.

For individual model testing, try to be exhaustive in the test cases: testing large number of cases for the parameters and inputs values, including invalid ones.
There is exactly one file for testing each model in this folder /tests/models/.

For integrations tests, also try to be exhaustive and to find edge cases.

Add some asserts that check that the physics is correct (balance of energy and mass, same temperature on both end of a connection).

You can use parametrized tests to test with different values, especially for the tests test_define_element_with_parameters to tests with different parameters values, including invalid ones and optional ones, and for the tests test_controller_run_control with different inputs, including invalid ones, Generic or Fluid inputs, 0, negative or nan values...

Ask the user if unsure about something.

## Error Handling
- If required files are missing, inform user and suggest creation
- If tests fail during write-tests, provide specific error messages

## Validation Requirements

- All new tests must pass
- Test coverage must not decrease
- Tests must include edge cases
- Tests must verify physical consistency
