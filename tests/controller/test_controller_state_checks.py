"""Consistency checks of the controllers raise ControllerStateError, never a bare ``assert``.

A bare ``assert`` vanishes when Python runs with ``-O``: the check is skipped and the simulation goes on with a
NaN or an inverted temperature. ``MappedController._check`` raises ``ControllerStateError`` instead, which
subclasses ``AssertionError`` so that code catching ``AssertionError`` keeps working.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_gas_boiler
from pandaprosumer.controller.mapped import ControllerStateError

SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "pandaprosumer"


@pytest.fixture
def inverted_gas_boiler():
    """A gas boiler asked to heat water from 30 °C down to 25 °C, an impossible request."""
    prosumer = create_empty_prosumer_container(name="test_prosumer")
    period = create_period(prosumer, 3600, "2020-01-01 00:00:00", "2020-01-01 11:59:59", "utc", "default")
    index = create_controlled_gas_boiler(prosumer, period=period, max_q_kw=100, name="boiler_a")
    boiler = prosumer.controller.iloc[index].object
    boiler.t_m_to_deliver = lambda _prosumer: (25.0, 30.0, [0.2])
    boiler.time_step(prosumer, "2020-01-01 00:00:00")
    return prosumer, boiler


def test_controller_state_error_is_an_assertion_error():
    assert issubclass(ControllerStateError, AssertionError)


def test_check_passes_silently_when_the_condition_holds(inverted_gas_boiler):
    prosumer, boiler = inverted_gas_boiler
    boiler._check(True, "never shown", prosumer)


def test_check_message_names_the_controller_the_timestep_and_the_prosumer(inverted_gas_boiler):
    prosumer, boiler = inverted_gas_boiler
    with pytest.raises(ControllerStateError) as exc_info:
        boiler.control_step(prosumer)
    message = str(exc_info.value)
    assert boiler.name_class() in message
    assert "'boiler_a'" in message
    assert "2020-01-01 00:00:00" in message
    assert "'test_prosumer'" in message
    assert "lower than t_in_required_c" in message


def test_check_without_prosumer_omits_it(inverted_gas_boiler):
    _prosumer, boiler = inverted_gas_boiler
    with pytest.raises(ControllerStateError) as exc_info:
        boiler._check(False, "something is wrong")
    assert str(exc_info.value).endswith(": something is wrong")
    assert "prosumer" not in str(exc_info.value)


def test_check_still_raises_under_python_optimize():
    """With ``python -O`` a bare assert is stripped; the check must still raise."""
    script = (
        "from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_gas_boiler\n"
        "from pandaprosumer.controller.mapped import ControllerStateError\n"
        "prosumer = create_empty_prosumer_container()\n"
        "period = create_period(prosumer, 3600, '2020-01-01 00:00:00', '2020-01-01 11:59:59', 'utc', 'default')\n"
        "boiler = prosumer.controller.iloc[create_controlled_gas_boiler(prosumer, period=period, max_q_kw=100)].object\n"
        "boiler.t_m_to_deliver = lambda _prosumer: (25.0, 30.0, [0.2])\n"
        "boiler.time_step(prosumer, '2020-01-01 00:00:00')\n"
        "try:\n"
        "    boiler.control_step(prosumer)\n"
        "except ControllerStateError:\n"
        "    print('raised')\n"
    )
    result = subprocess.run([sys.executable, "-O", "-c", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "raised"


def test_no_bare_assert_left_in_the_library():
    offenders = [f"{path.relative_to(SRC_DIR)}:{node.lineno}"
                 for path in sorted(SRC_DIR.rglob("*.py"))
                 for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                 if isinstance(node, ast.Assert)]
    assert not offenders, f"Use self._check(...) or raise ControllerStateError instead of assert: {offenders}"
