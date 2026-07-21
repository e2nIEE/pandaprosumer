# Mixing Valve (3-way valve) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `mixing_valve` component that sits between a hot producer (e.g. 95 °C) and a demand wishing a lower feed temperature (e.g. 80 °C), recirculating cold return (e.g. 70 °C) with exact mass and energy conservation.

**Architecture:** New full pandaprosumer component (element + data model + controller + create functions + docs + tests). The controller copies the *intermediate component* shape of `HeatExchangerController` (upstream `FluidMixMapping` initiator → controller → downstream `FluidMixMapping` responders, reapply/convergence state), but the physics is plain constant-cp mixing algebra. Spec: `docs/superpowers/specs/2026-07-21-mixing-valve-design.md`.

**Tech Stack:** Python (repo venv `.venv`, Python ≤3.11), pandas/numpy, pytest, Sphinx.

## Global Constraints

- Always run Python/pytest through the repo venv: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest ...` (never a system python; never backend-api's venv).
- Working branch: `fix-for-paris`. Commit only the files each task touches (the tree has unrelated uncommitted changes in `src/pandaprosumer/controller/mapped.py` and `src/pandaprosumer/mapping/generic.py` — NEVER `git add` those).
- Version pins: `pandapower==2.14.11`, `pandapipes==0.10.0`. `create_period` must be called with **positional** args in tests: `create_period(prosumer, resol, start, end, 'utc', 'default')`.
- Naming per `doc/source/about/units.rst`: unit suffix last (`_c`, `_kw`, `_kg_per_s`), adjectives between (`t_in_nom_c`).
- New element columns are appended in dict order with `in_service` last; element-definition tests pin columns/values positionally.
- All commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Physics reference (used by Tasks 2–4)

Inputs each timestep: downstream request `(t_out_req_c, t_return_req_c, mdot_out_req)` from `t_m_to_deliver`; received supply temperature `t_in_c` (FluidMix, falls back to element `t_in_nom_c`); optionally a producer-fixed received mass flow `R` (`input_mass_flow_with_temp[MASS_FLOW_KEY]`, NaN if free).

Nominal mixing (`t_in_c > t_out_req_c` and non-degenerate):

```text
mdot_in     = mdot_out_req * (t_out_req_c - t_return_req_c) / (t_in_c - t_return_req_c)
mdot_recirc = mdot_out_req - mdot_in
t_out_c     = t_out_req_c
```

Case table for `calculate_mixing(t_in_c, t_out_req_c, t_return_req_c, mdot_out_req)` → `(mdot_in, mdot_recirc, mdot_out, t_out_c)`:

| Condition (checked in order) | mdot_in | mdot_recirc | mdot_out | t_out_c |
| --- | --- | --- | --- | --- |
| degenerate demand: `mdot_out_req < 1e-6` or `t_out_req_c - t_return_req_c < 1e-3` | 0 | 0 | 0 | `t_in_c` |
| dead supply: `t_in_c - t_return_req_c < 1e-3` | 0 | 0 | 0 | `t_in_c` |
| cold supply: `t_in_c <= t_out_req_c` | `mdot_out_req` | 0 | `mdot_out_req` | `t_in_c` (pass-through) |
| mixing (otherwise) | formula above | `mdot_out_req - mdot_in` | `mdot_out_req` | `t_out_req_c` |

Reconciliation when the producer fixed `R` (not NaN), hot-supply case only:

| Condition | Behaviour |
| --- | --- |
| `R >= mdot_out_req` | `mdot_recirc = 0`, `mdot_out = R`, `t_out_c = t_in_c`; the mass surplus `R - mdot_out_req` is dispatched by `_merit_order_mass_flow` per `overflow_strategy` |
| `mdot_in < R < mdot_out_req` | `mdot_recirc = mdot_out_req - R`, `mdot_out = mdot_out_req`, `t_out_c = (R*t_in_c + mdot_recirc*t_return_req_c) / mdot_out_req` (runs hotter than target, energy balanced) |
| `R <= mdot_in` | hold `t_out_c = t_out_req_c`, scale down: `mdot_out = R * (t_in_c - t_return_req_c) / (t_out_req_c - t_return_req_c)`, `mdot_recirc = mdot_out - R` |

In cold-supply/dead-supply cases with `R` fixed: `mdot_out = R`, `mdot_recirc = 0`, `t_out_c = t_in_c` (never recirculate to top up mass — that would only cool the mix further).

Delivered power: `q_delivered_kw = mdot_out * cp_kj_per_kgk * (t_out_c - t_return_req_c)` with `cp` from `prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + (t_out_c + t_return_req_c)/2) / 1000`. The same-cp mixing rule makes hot-leg energy `mdot_in*cp*(t_in_c - t_return_req_c)` equal `q_delivered_kw` exactly.

Result columns (fixed order): `["q_delivered_kw", "mdot_in_kg_per_s", "t_in_c", "mdot_recirc_kg_per_s", "mdot_out_kg_per_s", "t_out_c", "t_return_c"]`.

---

### Task 1: Element + `create_mixing_valve` + exports

**Files:**
- Create: `src/pandaprosumer/element/mixing_valve.py`
- Modify: `src/pandaprosumer/element/__init__.py` (append one line)
- Modify: `src/pandaprosumer/create.py` (import + new function after `create_heat_exchanger`, which ends at line ~473)
- Test: `tests/models/test_mixing_valve.py` (new)

**Interfaces:**
- Produces: `MixingValveElementData` (dataclass, `name="mixing_valve"`); `create_mixing_valve(prosumer, t_in_nom_c=95., overflow_strategy='dump_proportional', name=None, index=None, in_service=True, **kwargs) -> int`. Element columns in order: `name, t_in_nom_c, overflow_strategy, in_service`.

- [ ] **Step 1: Write the failing tests**

Create `tests/models/test_mixing_valve.py`:

```python
import pytest
import numpy as np
from pandaprosumer import create_empty_prosumer_container, create_period, create_mixing_valve


class TestMixingValveElement:
    """Tests the definition of a Mixing Valve element."""

    def test_define_element(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_mixing_valve(prosumer)
        assert hasattr(prosumer, "mixing_valve")
        assert len(prosumer.mixing_valve) == 1

        expected_columns = ['name', 't_in_nom_c', 'overflow_strategy', 'in_service']
        expected_values = [None, 95., 'dump_proportional', True]

        assert list(prosumer.mixing_valve.columns) == expected_columns
        assert prosumer.mixing_valve.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        mv_idx = create_mixing_valve(prosumer, t_in_nom_c=90, overflow_strategy='dump_on_last',
                                     name='foo', in_service=False, index=4, custom='test')
        assert len(prosumer.mixing_valve) == 1
        assert mv_idx == 4
        assert prosumer.mixing_valve.index[0] == mv_idx

        expected_columns = ['name', 't_in_nom_c', 'overflow_strategy', 'in_service', 'custom']
        expected_values = ['foo', 90., 'dump_on_last', False, 'test']

        assert list(prosumer.mixing_valve.columns) == expected_columns
        assert prosumer.mixing_valve.iloc[0].values == pytest.approx(expected_values)

    def test_define_element_invalid_overflow_strategy(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)
        with pytest.raises(ValueError):
            create_mixing_valve(prosumer, overflow_strategy='drop_it')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/models/test_mixing_valve.py -v`
Expected: FAIL/ERROR with `ImportError: cannot import name 'create_mixing_valve'`

- [ ] **Step 3: Implement**

Create `src/pandaprosumer/element/mixing_valve.py`:

```python
from dataclasses import dataclass, field
from typing import List
from numpy import dtype
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class MixingValveElementData:
    """
    Data class for MixingValveElementData.

    A 3-way mixing valve between a hot producer and a demand wishing a lower
    feed temperature. It recirculates cold return fluid into the supply so the
    responders receive their wished feed temperature, conserving mass and
    energy exactly (constant-cp mixing rule).

    Attributes
    ----------
    name : str
        Name of the element table.
    input : List[tuple]
        List of input attributes and their data types
    """
    name: str = "mixing_valve"
    input: List[tuple] = field(default_factory=lambda: [
        ('name', dtype(object)),

        ('t_in_nom_c', 'f8'),
        ('overflow_strategy', 'str'),

        ('in_service', bool)
    ])
```

Append to `src/pandaprosumer/element/__init__.py`:

```python
from .mixing_valve import *
```

In `src/pandaprosumer/create.py`, add `MixingValveElementData` to the `from pandaprosumer.element import (...)` block (alphabetical: after `IceChpElementData`), then add after `create_heat_exchanger` (after line ~473):

```python
def create_mixing_valve(prosumer,
                        t_in_nom_c=95.,
                        overflow_strategy='dump_proportional',
                        name=None,
                        index=None,
                        in_service=True,
                        **kwargs):
    """
        Creates a mixing valve element in prosumer["mixing_valve"]

    INPUT:
        **prosumer** - The prosumer within this mixing valve should be created

    OPTIONAL:
        **t_in_nom_c** (float, default 95) - Nominal hot-inlet temperature requested from the upstream \
        producer [C]. Only used for the initial upstream request; the actual mixing always uses the \
        temperature really received

        **overflow_strategy** (string, default 'dump_proportional') - How a forced mass-flow surplus \
        (producer delivers more than the demand takes, recirculation already at 0) is dispatched across \
        responders: 'dump_proportional', 'dump_on_last' or 'cap'

        **name** (string, default None) - The name for this mixing valve

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

    OUTPUT:
        **index** (int) - The unique ID of the created mixing valve

    EXAMPLE:
        create_mixing_valve(prosumer, t_in_nom_c=95)
    """
    add_new_element(prosumer, MixingValveElementData)

    if overflow_strategy not in ("cap", "dump_on_last", "dump_proportional"):
        raise ValueError(f"Unknown overflow_strategy '{overflow_strategy}'. "
                         "Expected one of: 'cap', 'dump_on_last', 'dump_proportional'.")

    index = _get_index_with_check(prosumer, "mixing_valve", index)

    entries = dict(zip(["name", "t_in_nom_c", "overflow_strategy", "in_service"],
                       [name, t_in_nom_c, overflow_strategy, in_service]))

    _set_entries(prosumer, "mixing_valve", index, **entries, **kwargs)
    return int(index)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/models/test_mixing_valve.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/pandaprosumer/element/mixing_valve.py src/pandaprosumer/element/__init__.py src/pandaprosumer/create.py tests/models/test_mixing_valve.py
git commit -m "feat(mixing_valve): element and create_mixing_valve

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Data model, controller with `calculate_mixing`, `create_controlled_mixing_valve`

**Files:**
- Create: `src/pandaprosumer/controller/data_model/mixing_valve.py`
- Create: `src/pandaprosumer/controller/models/mixing_valve.py`
- Modify: `src/pandaprosumer/controller/data_model/__init__.py`, `src/pandaprosumer/controller/models/__init__.py` (append one line each)
- Modify: `src/pandaprosumer/create_controlled.py` (imports + new function after `create_controlled_heat_exchanger`, line ~527)
- Test: `tests/models/test_mixing_valve.py` (extend)

**Interfaces:**
- Consumes: `create_mixing_valve` (Task 1).
- Produces: `MixingValveControllerData(element_index, element_name='mixing_valve', period_index=None, input_columns=[], result_columns=[7 columns from Physics reference])`; `MixingValveController(BasicProsumerController)` with method `calculate_mixing(self, t_in_c, t_out_req_c, t_return_req_c, mdot_out_req_kg_per_s) -> (mdot_in_kg_per_s, mdot_recirc_kg_per_s, mdot_out_kg_per_s, t_out_c)`; `create_controlled_mixing_valve(prosumer, t_in_nom_c=95., overflow_strategy='dump_proportional', name=None, index=None, in_service=True, level=0, order=0, period=0, **kwargs) -> int` (controller index).

- [ ] **Step 1: Write the failing tests**

Append to `tests/models/test_mixing_valve.py` (extend the import line at top: add `create_controlled_mixing_valve` to the `from pandaprosumer import ...`):

```python
def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestMixingValveController:
    """Tests the Mixing Valve controller definition and mixing algebra."""

    def test_define_controller(self):
        prosumer = create_empty_prosumer_container()
        create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        prosumer = create_empty_prosumer_container()
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        mv = prosumer.controller.iloc[mv_idx].object
        assert mv.input_columns == []
        assert mv.result_columns == ["q_delivered_kw", "mdot_in_kg_per_s", "t_in_c",
                                     "mdot_recirc_kg_per_s", "mdot_out_kg_per_s", "t_out_c", "t_return_c"]

    def test_calculate_mixing_nominal(self):
        """95 in, 80 wished, 70 return, 2 kg/s out: hot leg is 10/25 = 40%."""
        prosumer = create_empty_prosumer_container()
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        mv = prosumer.controller.iloc[mv_idx].object
        mdot_in, mdot_recirc, mdot_out, t_out_c = mv.calculate_mixing(95., 80., 70., 2.)
        assert mdot_in == pytest.approx(0.8)
        assert mdot_recirc == pytest.approx(1.2)
        assert mdot_out == pytest.approx(2.)
        assert t_out_c == pytest.approx(80.)
        # Mass and energy conservation
        assert mdot_in + mdot_recirc == pytest.approx(mdot_out)
        assert mdot_in * (95. - 70.) == pytest.approx(mdot_out * (t_out_c - 70.))

    def test_calculate_mixing_cold_supply(self):
        """Supply at 78 < wished 80: full pass-through, no recirculation."""
        prosumer = create_empty_prosumer_container()
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        mv = prosumer.controller.iloc[mv_idx].object
        assert mv.calculate_mixing(78., 80., 70., 2.) == pytest.approx((2., 0., 2., 78.))

    def test_calculate_mixing_degenerate(self):
        prosumer = create_empty_prosumer_container()
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        mv = prosumer.controller.iloc[mv_idx].object
        # No demand mass flow
        assert mv.calculate_mixing(95., 80., 70., 0.) == pytest.approx((0., 0., 0., 95.))
        # Demand feed == return (no heat wanted)
        assert mv.calculate_mixing(95., 70., 70., 2.) == pytest.approx((0., 0., 0., 95.))
        # Supply at the return temperature: cannot heat at all
        assert mv.calculate_mixing(70., 80., 70., 2.) == pytest.approx((0., 0., 0., 70.))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/models/test_mixing_valve.py -v`
Expected: Task 1 tests pass; new tests FAIL with `ImportError: cannot import name 'create_controlled_mixing_valve'`

- [ ] **Step 3: Implement**

Create `src/pandaprosumer/controller/data_model/mixing_valve.py`:

```python
from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class MixingValveControllerData:
    """
    Data class for the 3-way mixing valve controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    element_name : str
        Name of the element.
    period_index : int, optional
        Index of the period, default is None.
    input_columns : List[str]
        List of input column names (none: the received temperature and mass
        flow come from the upstream FluidMixMapping).
    result_columns : List[str]
        List of result column names.

        **q_delivered_kw** - Thermal power delivered to the responders [kW]

        **mdot_in_kg_per_s** - Hot-leg mass flow drawn from the producer [kg/s]

        **t_in_c** - Received supply temperature [°C]

        **mdot_recirc_kg_per_s** - Recirculated return mass flow [kg/s]

        **mdot_out_kg_per_s** - Mixed mass flow delivered downstream [kg/s]

        **t_out_c** - Mixed feed temperature delivered downstream [°C]

        **t_return_c** - Return temperature (identical toward producer and from responders) [°C]
    """
    element_index: List[int]
    element_name: str = 'mixing_valve'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: [])
    result_columns: List[str] = field(
        default_factory=lambda: ["q_delivered_kw",
                                 "mdot_in_kg_per_s", "t_in_c",
                                 "mdot_recirc_kg_per_s",
                                 "mdot_out_kg_per_s", "t_out_c", "t_return_c"])
```

Create `src/pandaprosumer/controller/models/mixing_valve.py` (Task 3 adds `control_step` and the receive methods; this task creates the class with the mixing algebra):

```python
"""
Module containing the MixingValveController class.
"""

import logging
import numpy as np

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.mapping import FluidMixMapping

logger = logging.getLogger(__name__)


class MixingValveController(BasicProsumerController):
    """
    Controller for a 3-way mixing valve.

    The valve draws hot fluid at t_in_c from an upstream producer (FluidMix
    initiator) and mixes it with return fluid recirculated at the responders'
    return temperature, so the responders receive their wished feed
    temperature. Mass and energy are conserved exactly under the constant-cp
    mixing rule (cp evaluated at the mean temperature; no heat loss, no
    pressure modeling).

    :param prosumer: The prosumer object
    :param mixing_valve_object: The mixing valve controller data object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "mixing_valve_controller"

    def __init__(self, prosumer, mixing_valve_object, order, level,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, mixing_valve_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.t_previous_in_c = np.nan
        self.t_previous_return_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

    @property
    def _t_received_c(self):
        """Supply temperature received from the upstream FluidMix, or NaN."""
        return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]

    @property
    def _mdot_received_kg_per_s(self):
        """Mass flow fixed by the upstream FluidMix initiator, or NaN if free."""
        return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]

    def calculate_mixing(self, t_in_c, t_out_req_c, t_return_req_c, mdot_out_req_kg_per_s):
        """
        Mixing algebra of the 3-way valve for a free (non-fixed) hot-leg flow.

        :param t_in_c: The hot supply temperature [°C]
        :param t_out_req_c: The feed temperature wished by the responders [°C]
        :param t_return_req_c: The responders' return temperature [°C]
        :param mdot_out_req_kg_per_s: The total mass flow required by the responders [kg/s]
        :return: A tuple (hot-leg mass flow [kg/s], recirculated mass flow [kg/s],
            delivered mass flow [kg/s], delivered feed temperature [°C])
        """
        if mdot_out_req_kg_per_s < 1e-6 or (t_out_req_c - t_return_req_c) < 1e-3:
            # Degenerate demand: nothing to deliver
            return 0., 0., 0., t_in_c
        if (t_in_c - t_return_req_c) < 1e-3:
            # Dead supply: cannot heat the return at all
            return 0., 0., 0., t_in_c
        if t_in_c <= t_out_req_c:
            # Cold supply: fully open, pass the flow through unchanged
            return mdot_out_req_kg_per_s, 0., mdot_out_req_kg_per_s, t_in_c
        mdot_in_kg_per_s = (mdot_out_req_kg_per_s
                            * (t_out_req_c - t_return_req_c) / (t_in_c - t_return_req_c))
        mdot_recirc_kg_per_s = mdot_out_req_kg_per_s - mdot_in_kg_per_s
        return mdot_in_kg_per_s, mdot_recirc_kg_per_s, mdot_out_req_kg_per_s, t_out_req_c
```

Append to `src/pandaprosumer/controller/data_model/__init__.py`:

```python
from .mixing_valve import *
```

Append to `src/pandaprosumer/controller/models/__init__.py`:

```python
from .mixing_valve import *
```

In `src/pandaprosumer/create_controlled.py`: add `create_mixing_valve` to the `from pandaprosumer.create import (...)` list (after `create_ice_chp`); add `MixingValveController, MixingValveControllerData,` to the `from pandaprosumer.controller import (...)` list (after `IceChpControllerData` block, alphabetical). Then add after `create_controlled_heat_exchanger` (line ~527):

```python
def create_controlled_mixing_valve(prosumer,
                                   t_in_nom_c=95.,
                                   overflow_strategy='dump_proportional',
                                   name=None,
                                   index=None,
                                   in_service=True,
                                   level=0,
                                   order=0,
                                   period=0,
                                   **kwargs):
    """
            Creates a mixing valve element in prosumer["mixing_valve"] and a mixing valve controller

        INPUT:
            **prosumer** - The prosumer within this mixing valve should be created

        OPTIONAL:
            **t_in_nom_c** (float, default 95) - Nominal hot-inlet temperature requested from the \
            upstream producer [C]

            **overflow_strategy** (string, default 'dump_proportional') - How a forced mass-flow surplus \
            is dispatched across responders: 'dump_proportional', 'dump_on_last' or 'cap'

            **name** (string, default None) - The name for this mixing valve

            **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
                higher than the highest already existing index is selected.

            **in_service** (boolean, default True) - True for in_service or False for out of service

            **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0

        OUTPUT:
            **index** (int) - The unique ID of the created mixing valve controller

        EXAMPLE:
            create_controlled_mixing_valve(prosumer, t_in_nom_c=95)
        """

    mixing_valve_index = create_mixing_valve(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", "level", "kwargs"}},
        **kwargs
    )
    mixing_valve_controller_data = MixingValveControllerData(
        element_name='mixing_valve',
        element_index=[mixing_valve_index],
        period_index=period
    )
    mixing_valve_controller = MixingValveController(prosumer,
                                                    mixing_valve_controller_data,
                                                    order=order,
                                                    level=level,
                                                    name=name)
    return mixing_valve_controller.index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/models/test_mixing_valve.py -v`
Expected: all pass (3 element + 5 controller)

- [ ] **Step 5: Commit**

```bash
git add src/pandaprosumer/controller/data_model/mixing_valve.py src/pandaprosumer/controller/data_model/__init__.py src/pandaprosumer/controller/models/mixing_valve.py src/pandaprosumer/controller/models/__init__.py src/pandaprosumer/create_controlled.py tests/models/test_mixing_valve.py
git commit -m "feat(mixing_valve): data model, controller mixing algebra, create_controlled

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `control_step`, upstream request methods, FluidMix wiring

**Files:**
- Modify: `src/pandaprosumer/controller/models/mixing_valve.py` (add methods to the class)
- Test: `tests/models/test_mixing_valve.py` (extend)

**Interfaces:**
- Consumes: `calculate_mixing`, base-class API: `t_m_to_deliver(prosumer) -> (t_feed_c, t_return_c, mdot_tab)`, `_merit_order_mass_flow(container, mdot_available, mdot_required_tab, overflow_strategy)`, `_check_fluid_mix_balance(container, q_kw, mdot, t_out_c, t_in_c, result_mdot_tab, cp)`, `finalize(container, result, result_fluid_mix)`, `self.t_keep_return_c`, `self._are_initiators_converged/_unapply_initiators`, `self._get_element_param`.
- Produces: `_t_m_to_receive_init(prosumer)` and `t_m_to_receive_for_t(prosumer, t_feed_c)` so upstream producers can ask the valve what to deliver; `control_step(prosumer)` writing the 7 result columns and `result_mass_flow_with_temp`.

- [ ] **Step 1: Write the failing tests**

Append inside `TestMixingValveController` in `tests/models/test_mixing_valve.py` (add to imports at top: `from pandaprosumer.mapping.fluid_mix import FluidMixMapping`):

```python
    @staticmethod
    def _make_controller(prosumer, **kwargs):
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer), **kwargs)
        return prosumer.controller.iloc[mv_idx].object

    def test_t_m_to_receive_requests_nominal_temperature(self):
        """The valve asks upstream for t_in_nom_c and the reduced hot-leg mdot."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        assert mv.t_m_to_receive(prosumer) == pytest.approx((95., 70., 0.8))

    def test_control_step_nominal(self):
        """No fixed upstream flow: assume the requested hot leg was delivered at t_in_nom_c."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.control_step(prosumer)

        q_kw = 2. * 4.19 * (80. - 70.)
        expected = [q_kw, 0.8, 95., 1.2, 2., 80., 70.]
        assert mv.step_results == pytest.approx(np.array([expected]), rel=.01)
        assert mv.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                  FluidMixMapping.MASS_FLOW_KEY: pytest.approx(2.)}]

    def test_control_step_received_flow_and_temperature(self):
        """Producer fixed exactly the requested hot leg at 95: nominal mix."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 95.,
                                        FluidMixMapping.MASS_FLOW_KEY: 0.8}
        mv.control_step(prosumer)
        q_kw = 2. * 4.19 * (80. - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 0.8, 95., 1.2, 2., 80., 70.]]), rel=.01)

    def test_control_step_cold_supply_passthrough(self):
        """Received 78 < wished 80: pass-through at 78, no recirculation."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 78.,
                                        FluidMixMapping.MASS_FLOW_KEY: 2.}
        mv.control_step(prosumer)
        q_kw = 2. * 4.19 * (78. - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 2., 78., 0., 2., 78., 70.]]), rel=.01)

    def test_control_step_short_supply_holds_temperature(self):
        """Producer fixed only 0.4 kg/s (< 0.8 needed): t_out held at 80, flow scaled to 1.0."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 95.,
                                        FluidMixMapping.MASS_FLOW_KEY: 0.4}
        mv.control_step(prosumer)
        q_kw = 1. * 4.19 * (80. - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 0.4, 95., 0.6, 1., 80., 70.]]), rel=.01)

    def test_control_step_excess_supply_runs_hotter(self):
        """Producer fixed 1.0 kg/s (> 0.8 needed, < 2.0 demand): recirc shrinks, mix runs hotter."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 95.,
                                        FluidMixMapping.MASS_FLOW_KEY: 1.}
        mv.control_step(prosumer)
        t_out_c = (1. * 95. + 1. * 70.) / 2.  # 82.5
        q_kw = 2. * 4.19 * (t_out_c - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 1., 95., 1., 2., t_out_c, 70.]]), rel=.01)
        # Energy conservation: hot leg in == mix out
        assert 1. * (95. - 70.) == pytest.approx(2. * (t_out_c - 70.))

    def test_control_step_flood_supply_passthrough_surplus(self):
        """Producer fixed 2.5 kg/s (>= 2.0 demand): full pass-through at 95, surplus dumped."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 95.,
                                        FluidMixMapping.MASS_FLOW_KEY: 2.5}
        mv.control_step(prosumer)
        q_kw = 2.5 * 4.19 * (95. - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 2.5, 95., 0., 2.5, 95., 70.]]), rel=.01)
        # dump_proportional: single responder receives everything
        assert mv.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 95.,
                                                  FluidMixMapping.MASS_FLOW_KEY: pytest.approx(2.5)}]

    def test_control_step_no_demand(self):
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (0., 0., [0.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.control_step(prosumer)
        assert mv.step_results == pytest.approx(np.array([[0., 0., 95., 0., 0., 95., 0.]]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/models/test_mixing_valve.py -v`
Expected: earlier tests pass; the 8 new tests FAIL (base `control_step` writes no results / `t_m_to_receive` uses the default superclass behaviour)

- [ ] **Step 3: Implement**

Add to `MixingValveController` in `src/pandaprosumer/controller/models/mixing_valve.py`:

```python
    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        if not np.isnan(self.t_previous_return_c):
            return self.t_previous_in_c, self.t_previous_return_c, self.mdot_previous_in_kg_per_s
        t_in_nom_c = self._get_element_param(prosumer, 't_in_nom_c')
        return self.t_m_to_receive_for_t(prosumer, t_in_nom_c)

    def t_m_to_receive_for_t(self, prosumer, t_feed_c):
        """
        For a given feed temperature in °C, calculate the required feed mass flow
        and the expected return temperature if this feed temperature is provided.

        :param prosumer: The prosumer object
        :param t_feed_c: The feed temperature
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_out_req_c, t_return_req_c, mdot_tab_req_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_out_req_kg_per_s = sum(mdot_tab_req_kg_per_s)
        mdot_in_kg_per_s, _, _, _ = self.calculate_mixing(t_feed_c, t_out_req_c,
                                                          t_return_req_c, mdot_out_req_kg_per_s)
        return t_feed_c, t_return_req_c, mdot_in_kg_per_s

    def _save_state(self):
        """Backup states before Run"""
        self._backup_state = {
            "t_previous_in_c": self.t_previous_in_c,
            "t_previous_return_c": self.t_previous_return_c,
            "mdot_previous_in_kg_per_s": self.mdot_previous_in_kg_per_s,
        }

    def _restore_state(self):
        """Restore states before Rerun"""
        if hasattr(self, "_backup_state"):
            self.t_previous_in_c = self._backup_state["t_previous_in_c"]
            self.t_previous_return_c = self._backup_state["t_previous_return_c"]
            self.mdot_previous_in_kg_per_s = self._backup_state["mdot_previous_in_kg_per_s"]

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if not prosumer.rerun:
            self._save_state()
        else:
            self._restore_state()

        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[
                self.obj.element_index[0]].in_service):
            self.applied = True
            return

        super().control_step(prosumer)

        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        t_out_req_c, t_return_req_c, mdot_tab_req_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_out_req_kg_per_s = sum(mdot_tab_req_kg_per_s)

        t_in_c = self._t_received_c
        if np.isnan(t_in_c):
            t_in_c = self._get_element_param(prosumer, 't_in_nom_c')

        assert not np.isnan(t_out_req_c), \
            f"Mixing Valve {self.name} t_out_req_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_return_req_c), \
            f"Mixing Valve {self.name} t_return_req_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_out_req_kg_per_s), \
            f"Mixing Valve {self.name} mdot_out_req_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"

        (mdot_in_kg_per_s, mdot_recirc_kg_per_s,
         mdot_out_kg_per_s, t_out_c) = self.calculate_mixing(t_in_c, t_out_req_c,
                                                             t_return_req_c, mdot_out_req_kg_per_s)

        mdot_received_kg_per_s = self._mdot_received_kg_per_s
        if not np.isnan(mdot_received_kg_per_s) and mdot_out_kg_per_s > 1e-9:
            assert mdot_received_kg_per_s >= 0, \
                (f"Mixing Valve {self.name} received mass flow is negative for timestep {self.time} "
                 f"in prosumer {prosumer.name}")
            if t_in_c <= t_out_req_c:
                # Cold supply: pass through whatever arrives, never recirculate to top up
                mdot_in_kg_per_s = mdot_received_kg_per_s
                mdot_recirc_kg_per_s = 0.
                mdot_out_kg_per_s = mdot_received_kg_per_s
                t_out_c = t_in_c
            elif mdot_received_kg_per_s >= mdot_out_req_kg_per_s:
                # Flooded: no recirculation, everything passes through at t_in_c;
                # the mass surplus is dispatched per overflow_strategy below
                mdot_in_kg_per_s = mdot_received_kg_per_s
                mdot_recirc_kg_per_s = 0.
                mdot_out_kg_per_s = mdot_received_kg_per_s
                t_out_c = t_in_c
            elif mdot_received_kg_per_s > mdot_in_kg_per_s:
                # Excess hot flow: recirculation shrinks, the mix runs hotter than target
                mdot_in_kg_per_s = mdot_received_kg_per_s
                mdot_recirc_kg_per_s = mdot_out_req_kg_per_s - mdot_received_kg_per_s
                mdot_out_kg_per_s = mdot_out_req_kg_per_s
                t_out_c = ((mdot_in_kg_per_s * t_in_c + mdot_recirc_kg_per_s * t_return_req_c)
                           / mdot_out_kg_per_s)
            elif mdot_received_kg_per_s < mdot_in_kg_per_s:
                # Short supply: hold the wished feed temperature, scale the delivered flow down
                mdot_in_kg_per_s = mdot_received_kg_per_s
                mdot_out_kg_per_s = (mdot_received_kg_per_s
                                     * (t_in_c - t_return_req_c) / (t_out_req_c - t_return_req_c))
                mdot_recirc_kg_per_s = mdot_out_kg_per_s - mdot_in_kg_per_s
                t_out_c = t_out_req_c

        overflow_strategy = self._get_element_param(prosumer, 'overflow_strategy')
        if overflow_strategy is None or (isinstance(overflow_strategy, float) and np.isnan(overflow_strategy)):
            overflow_strategy = "cap"
        result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer, mdot_out_kg_per_s,
                                                               mdot_tab_req_kg_per_s,
                                                               overflow_strategy)

        if len(self._get_mapped_responders(prosumer)) > 1 and mdot_out_kg_per_s < mdot_out_req_kg_per_s:
            # If the valve cannot deliver the required mass flow, recalculate the return
            # temperature, considering that all the downstream elements will still return
            # the same temperature even with a lower delivered mass flow
            t_return_tab_c = self.get_treturn_tab_c(prosumer)
            if abs(mdot_out_kg_per_s) > 1e-8:
                t_return_new_c = np.sum(np.array(result_mdot_tab_kg_per_s) * t_return_tab_c) / mdot_out_kg_per_s
                if abs(t_return_new_c - t_return_req_c) > 1:
                    t_return_req_c = t_return_new_c

        cp_kj_per_kgk = prosumer.fluid.get_heat_capacity(
            CELSIUS_TO_K + (t_out_c + t_return_req_c) / 2) / 1000
        q_delivered_kw = mdot_out_kg_per_s * cp_kj_per_kgk * (t_out_c - t_return_req_c)

        assert mdot_in_kg_per_s >= 0, \
            f"Mixing Valve {self.name} mdot_in_kg_per_s is negative ({mdot_in_kg_per_s}) for timestep {self.time}"
        assert mdot_recirc_kg_per_s >= -1e-9, \
            f"Mixing Valve {self.name} mdot_recirc_kg_per_s is negative ({mdot_recirc_kg_per_s}) for timestep {self.time}"
        assert abs(mdot_in_kg_per_s + mdot_recirc_kg_per_s - mdot_out_kg_per_s) < 1e-6, \
            (f"Mixing Valve {self.name} mass balance violated "
             f"({mdot_in_kg_per_s} + {mdot_recirc_kg_per_s} != {mdot_out_kg_per_s}) for timestep {self.time}")

        result = np.array([[q_delivered_kw, mdot_in_kg_per_s, t_in_c,
                            mdot_recirc_kg_per_s, mdot_out_kg_per_s, t_out_c, t_return_req_c]])

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        if (np.isnan(self.t_keep_return_c) or mdot_in_kg_per_s == 0
                or abs(t_return_req_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C):
            self._check_fluid_mix_balance(prosumer, q_delivered_kw, mdot_out_kg_per_s,
                                          t_out_c, t_return_req_c, result_mdot_tab_kg_per_s,
                                          cp_kj_per_kgk)
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_in_c = np.nan
            self.t_previous_return_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
        else:
            # Reapply the upstream controllers with the new return temperature
            # so no energy appears or disappears
            self._unapply_initiators(prosumer)
            self.t_previous_in_c = t_in_c
            self.t_previous_return_c = t_return_req_c
            self.mdot_previous_in_kg_per_s = mdot_in_kg_per_s
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/models/test_mixing_valve.py -v`
Expected: all pass (16 tests)

- [ ] **Step 5: Run the full model-test suite for regressions**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/models/ -x -q`
Expected: all pass (no regressions — this task only added files/exports)

- [ ] **Step 6: Commit**

```bash
git add src/pandaprosumer/controller/models/mixing_valve.py tests/models/test_mixing_valve.py
git commit -m "feat(mixing_valve): control_step with FluidMix coupling and overflow dispatch

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Integration test — gas boiler → mixing valve → heat demand

**Files:**
- Test: `tests/integrations/test_mixing_valve_integration.py` (new)

**Interfaces:**
- Consumes: `create_controlled_mixing_valve` (Task 2), controller behaviour (Task 3), `_assert_interface_consistent` from `tests/integrations/test_overflow_strategy_consistency.py`.

- [ ] **Step 1: Write the test**

Create `tests/integrations/test_mixing_valve_integration.py`:

```python
"""
Integration test for the mixing valve (3-way valve) between a producer and a demand.

Chain: ConstProfile --(q_demand)--> HeatDemand
       GasBoiler --FluidMix--> MixingValve --FluidMix--> HeatDemand

The boiler produces at the valve's t_in_nom_c (95 C); the demand wishes 80 C
feed / 70 C return. The valve recirculates return fluid so that:

  mdot_boiler / mdot_demand == (80 - 70) / (95 - 70) == 0.4

and energy is conserved across the valve (q_boiler == q_demand_received).
"""
import numpy as np
import pandas as pd
import pytest

from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer import (create_empty_prosumer_container, create_period,
                           create_controlled_const_profile,
                           create_controlled_gas_boiler,
                           create_controlled_mixing_valve,
                           create_controlled_heat_demand)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries

from tests.integrations.test_overflow_strategy_consistency import _assert_interface_consistent


class TestMixingValveGasBoilerHeatDemand:

    def _build(self):
        prosumer = create_empty_prosumer_container()
        data = pd.DataFrame({"demand_1": [50., 200., 0., 100.]})
        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data) * pd.Timedelta(f"{resol}s") - pd.Timedelta("1s")
        period = create_period(prosumer, resol, start, end, 'utc', 'default')
        data.index = pd.date_range(start, end, freq=f'{resol}s', tz='utc')

        cp = create_controlled_const_profile(prosumer, ["demand_1"], ["qdemand_kw"],
                                             DFData(data), period, 0, 0)
        gb = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0,
                                          max_q_kw=500, efficiency_percent=100,
                                          heating_value_kj_per_kg=20e3)
        mv = create_controlled_mixing_valve(prosumer, period=period, level=1, order=1,
                                            t_in_nom_c=95.)
        hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=2,
                                           t_feed_demand_c=80., t_return_demand_c=70.)

        GenericMapping(container=prosumer, initiator_id=cp, initiator_column="qdemand_kw",
                       responder_id=hd, responder_column="q_demand_kw", order=0)
        FluidMixMapping(container=prosumer, initiator_id=gb, responder_id=mv, order=0)
        FluidMixMapping(container=prosumer, initiator_id=mv, responder_id=hd, order=0)

        run_timeseries(prosumer, period, True)

        gb_df = prosumer.time_series.loc[0].data_source.df
        mv_df = prosumer.time_series.loc[1].data_source.df
        hd_df = prosumer.time_series.loc[2].data_source.df
        return data, gb_df, mv_df, hd_df

    def test_valve_demand_interface_invariants(self):
        """Valve <-> demand: the four FluidMix interface invariants hold."""
        data, gb_df, mv_df, hd_df = self._build()
        _assert_interface_consistent(mv_df, hd_df,
                                     producer_t_out_col='t_out_c',
                                     producer_t_in_col='t_return_c',
                                     producer_mdot_col='mdot_out_kg_per_s',
                                     producer_q_col='q_delivered_kw')

    def test_boiler_valve_interface_invariants(self):
        """Boiler <-> valve: feed at 95, return at 70, hot-leg mdot, same q."""
        data, gb_df, mv_df, hd_df = self._build()
        running = data["demand_1"].values > 0
        np.testing.assert_allclose(gb_df.t_out_c.values[running], 95., atol=1e-2)
        np.testing.assert_allclose(gb_df.t_out_c.values, mv_df.t_in_c.values, rtol=1e-3)
        np.testing.assert_allclose(gb_df.t_in_c.values[running],
                                   mv_df.t_return_c.values[running], rtol=1e-3)
        np.testing.assert_allclose(gb_df.mdot_kg_per_s.values,
                                   mv_df.mdot_in_kg_per_s.values, rtol=1e-3, atol=1e-6)
        np.testing.assert_allclose(gb_df.q_kw.values, mv_df.q_delivered_kw.values,
                                   rtol=5e-3, atol=1e-3)

    def test_energy_conserved_across_valve(self):
        """q_boiler == q_demand_received: the valve neither creates nor destroys energy."""
        data, gb_df, mv_df, hd_df = self._build()
        np.testing.assert_allclose(gb_df.q_kw.values, hd_df.q_received_kw.values,
                                   rtol=5e-3, atol=1e-3)
        # And the demand is fully covered
        np.testing.assert_allclose(hd_df.q_received_kw.values, data["demand_1"].values,
                                   rtol=5e-3, atol=1e-3)

    def test_recirculation_ratio(self):
        """mdot_boiler / mdot_demand == (80-70)/(95-70) == 0.4 on running steps."""
        data, gb_df, mv_df, hd_df = self._build()
        running = data["demand_1"].values > 0
        ratio = gb_df.mdot_kg_per_s.values[running] / hd_df.mdot_kg_per_s.values[running]
        np.testing.assert_allclose(ratio, 0.4, rtol=1e-3)
        # Mass balance inside the valve
        np.testing.assert_allclose(mv_df.mdot_in_kg_per_s.values + mv_df.mdot_recirc_kg_per_s.values,
                                   mv_df.mdot_out_kg_per_s.values, rtol=1e-6, atol=1e-9)

    def test_no_energy_leak_warning(self):
        """The whole run must not emit EnergyLeakWarning."""
        import warnings
        from pandaprosumer.controller.mapped import EnergyLeakWarning
        with warnings.catch_warnings():
            warnings.simplefilter("error", EnergyLeakWarning)
            self._build()

    def test_no_nan_in_results(self):
        data, gb_df, mv_df, hd_df = self._build()
        assert not np.isnan(mv_df.values).any()
        assert not np.isnan(hd_df.values).any()
```

- [ ] **Step 2: Run the integration tests**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/integrations/test_mixing_valve_integration.py -v`
Expected: 6 passed. If a test fails, debug the controller (Task 3) — typical causes: the boiler delivering at a different temperature than requested (check `_t_m_to_receive_init`), or dispatch/temperature mismatches in the reconciliation branches. Do NOT loosen tolerances beyond the values above to make tests pass.

- [ ] **Step 3: Run the full test suite for regressions**

Run: `/home/mena138/Projects/senergynet/platform/pandaprosumer_os/.venv/bin/python -m pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add tests/integrations/test_mixing_valve_integration.py
git commit -m "test(mixing_valve): integration boiler->valve->demand with interface invariants

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Documentation

**Files:**
- Create: `doc/source/elements/mixing_valve.rst`
- Modify: `doc/source/element.rst` (add `elements/mixing_valve` to the toctree, after the `elements/heat_exchanger` line ~22)

**Interfaces:**
- Consumes: final parameter/IO names from Tasks 1–3.

- [ ] **Step 1: Write the documentation**

Create `doc/source/elements/mixing_valve.rst`:

```rst
============
Mixing Valve
============

A 3-way mixing valve between a hot producer and a demand wishing a lower feed
temperature. Part of the hot supply is mixed with recirculated cold return
fluid so the downstream responders receive their wished feed temperature,
while the producer keeps its own (hotter) supply temperature. Mass and energy
are conserved exactly.

Physics
=======

Each timestep the downstream responders request a feed temperature
:math:`T_{out}`, a return temperature :math:`T_{ret}` and a mass flow
:math:`\dot m_{out}`. The valve receives hot fluid at :math:`T_{in}` from the
upstream producer (FluidMix mapping) and draws only the hot-leg flow

.. math::
   \dot m_{in} = \dot m_{out} \cdot \frac{T_{out} - T_{ret}}{T_{in} - T_{ret}}

recirculating the rest of the return flow
:math:`\dot m_{rec} = \dot m_{out} - \dot m_{in}`.

Mass conservation holds by construction. Under the constant-:math:`c_p`
mixing rule (:math:`c_p` evaluated at the mean temperature), energy is
conserved exactly:

.. math::
   \dot m_{in} c_p (T_{in} - T_{ret}) = \dot m_{out} c_p (T_{out} - T_{ret})

The producer sees the return temperature :math:`T_{ret}` and the mass flow
:math:`\dot m_{in}` only, so the delivered thermal power is identical on both
sides of the valve. The model assumes a single fluid (the prosumer's fluid),
no heat loss and no pressure modeling.

Special cases
=============

- **Cold supply** (:math:`T_{in} \le T_{out}`): the valve opens fully and
  passes the flow through unchanged (no recirculation); the responders
  receive fluid colder than wished.
- **Excess supply** (the producer forces more mass flow than the hot leg
  needs): the recirculation shrinks and the mixed temperature rises above the
  wished feed temperature; once the received flow exceeds the total demand,
  everything passes through at :math:`T_{in}` and the mass surplus is
  dispatched per ``overflow_strategy``.
- **Short supply** (the producer delivers less than the hot leg needs): the
  wished feed temperature is held and the delivered mass flow is scaled down.
- **Dead supply** (:math:`T_{in} \le T_{ret}`): nothing is delivered.

Element parameters
==================

.. csv-table::
   :header: "Parameter", "Description", "Unit", "Default"

   "name", "Name of the element", "", "None"
   "t_in_nom_c", "Nominal hot-inlet temperature requested from the upstream producer. Only used for the initial upstream request; the mixing uses the temperature actually received", "°C", "95"
   "overflow_strategy", "Dispatch of a forced mass-flow surplus: 'dump_proportional', 'dump_on_last' or 'cap'", "", "'dump_proportional'"
   "in_service", "In-service status", "", "True"

Input and result time series
============================

The controller has no required input time series: the received temperature
and mass flow come from the upstream ``FluidMixMapping``.

.. csv-table::
   :header: "Result column", "Description", "Unit"

   "q_delivered_kw", "Thermal power delivered to the responders", "kW"
   "mdot_in_kg_per_s", "Hot-leg mass flow drawn from the producer", "kg/s"
   "t_in_c", "Received supply temperature", "°C"
   "mdot_recirc_kg_per_s", "Recirculated return mass flow", "kg/s"
   "mdot_out_kg_per_s", "Mixed mass flow delivered downstream", "kg/s"
   "t_out_c", "Mixed feed temperature delivered downstream", "°C"
   "t_return_c", "Return temperature (identical toward producer and from responders)", "°C"

Creation
========

.. autofunction:: pandaprosumer.create_mixing_valve

.. autofunction:: pandaprosumer.create_controlled_mixing_valve
```

In `doc/source/element.rst`, add below the `elements/heat_exchanger` toctree line:

```rst
    elements/mixing_valve
```

- [ ] **Step 2: Build the docs and check for new warnings**

Run: `cd doc && make clean html 2>&1 | grep -iE "warning|error" ; cd ..`
Expected: no NEW warnings/errors mentioning `mixing_valve` (pre-existing unrelated warnings may appear — compare against a build without the change if unsure)

- [ ] **Step 3: Commit**

```bash
git add doc/source/elements/mixing_valve.rst doc/source/element.rst
git commit -m "docs(mixing_valve): element documentation

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
