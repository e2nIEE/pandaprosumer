"""GenericMapping 'add' must be idempotent across reapply re-fires.

Within one time step, the convergence (reapply) loop can make an initiator
controller finalize — and hence re-fire its GenericMappings — several times
(`_unapply_initiators` sets `applied = False`, pandapower re-runs the
controller). The responder's input must reflect the LATEST contribution of each
mapping, not the SUM over passes.

Pre-fix, `_add_mapping` did `inputs = nan_to_num(previous) + mapped`, so a
2-pass negotiation doubled the mapped power. Observed in the Paris BET coupled
run as `net.heat_consumer[0].qext_w` = exactly 2×/3× `hp_ecs.q_evap_kw` at DEMix
schedule transitions (33/564 steps of the December week) — a ~1000 kW phantom
extraction that shocks the loop temperature.

Distinct mappings (several initiators legitimately summing into one responder
input) must keep summing — that is what 'add' is for.
"""
import numpy as np

from pandaprosumer import create_empty_prosumer_container
from pandaprosumer.mapping import GenericMapping


class _StubController:
    """Minimal stand-in exposing what GenericMapping.map() touches.

    `time` mirrors the per-step stamp pandapower sets on real controllers: the
    idempotence is scoped to one time step (same `time` = reapply re-fire),
    while a new `time` restores the historical accumulate-onto-previous
    semantics whatever way the responder resets its inputs.
    """

    def __init__(self, result_columns=None, input_columns=None, name="stub",
                 level=0, order=0, time="t0"):
        self.result_columns = result_columns or []
        self.input_columns = input_columns or []
        self.name = name
        self.level = level
        self.order = order
        self.time = time
        if self.result_columns:
            self.step_results = np.full([1, len(self.result_columns)], np.nan)
        if self.input_columns:
            self.inputs = np.full([1, len(self.input_columns)], np.nan)


def _make(container, initiator_col="q_kw", responder_col="qext_w", **kw):
    initiator = _StubController(result_columns=[initiator_col], name="init", order=0)
    responder = _StubController(input_columns=[responder_col], name="resp", order=1)
    mapping = GenericMapping(container=container,
                             initiator_id=0, initiator_column=initiator_col,
                             responder_id=1, responder_column=responder_col,
                             order=0, no_chain=True, **kw)
    return initiator, responder, mapping


def test_refire_same_value_does_not_accumulate():
    container = create_empty_prosumer_container()
    initiator, responder, mapping = _make(container)
    initiator.step_results[0, 0] = 995.0

    mapping.map(initiator, responder)   # pass 1
    mapping.map(initiator, responder)   # reapply pass 2 (same step)

    assert responder.inputs[0, 0] == 995.0, (
        f"re-fired mapping accumulated: {responder.inputs[0, 0]} (expected 995.0)")


def test_refire_uses_latest_value():
    container = create_empty_prosumer_container()
    initiator, responder, mapping = _make(container)

    initiator.step_results[0, 0] = 1000.0
    mapping.map(initiator, responder)
    initiator.step_results[0, 0] = 700.0   # negotiation converged lower
    mapping.map(initiator, responder)

    assert responder.inputs[0, 0] == 700.0


def test_two_initiators_still_sum():
    container = create_empty_prosumer_container()
    init_a, responder, map_a = _make(container)
    init_b = _StubController(result_columns=["q_kw"], name="init_b", order=0)
    map_b = GenericMapping(container=container,
                           initiator_id=2, initiator_column="q_kw",
                           responder_id=1, responder_column="qext_w",
                           order=0, no_chain=True)

    init_a.step_results[0, 0] = 300.0
    init_b.step_results[0, 0] = 200.0
    map_a.map(init_a, responder)
    map_b.map(init_b, responder)
    assert responder.inputs[0, 0] == 500.0

    # initiator A re-fires with a new value: replaces ITS contribution only
    init_a.step_results[0, 0] = 350.0
    map_a.map(init_a, responder)
    assert responder.inputs[0, 0] == 550.0


def test_subtract_refire_idempotent():
    container = create_empty_prosumer_container()
    initiator, responder, mapping = _make(container,
                                          application_operation="subtract")
    initiator.step_results[0, 0] = 400.0

    mapping.map(initiator, responder)
    mapping.map(initiator, responder)

    assert responder.inputs[0, 0] == -400.0


def test_conversion_function_applied_on_each_fire():
    container = create_empty_prosumer_container()
    initiator, responder, mapping = _make(
        container, conversion_function=lambda q: q * 1000)  # kW -> W
    initiator.step_results[0, 0] = 995.0

    mapping.map(initiator, responder)
    mapping.map(initiator, responder)

    assert responder.inputs[0, 0] == 995000.0


def test_new_time_step_keeps_historic_accumulate_semantics():
    """Idempotence is scoped WITHIN a step: on a new step the mapping must add
    onto whatever the responder's inputs hold (historic behaviour), never
    subtract a stale prior-step contribution. This is the Supervisor pattern:
    it consumes and re-NaNs its own inputs inside control_step (not in
    finalize_control), so the fresh step's value must arrive un-mangled —
    pre-fix-regression this came out as 0 − 26 + 30 = 4 instead of 30 and the
    in_service rule silently stopped firing."""
    container = create_empty_prosumer_container()
    initiator, responder, mapping = _make(container)

    initiator.step_results[0, 0] = 26.0
    mapping.map(initiator, responder)
    assert responder.inputs[0, 0] == 26.0

    # responder consumes and resets its own inputs mid-lifecycle (Supervisor)
    responder.inputs[:] = np.nan

    initiator.time = "t1"   # next time step
    initiator.step_results[0, 0] = 30.0
    mapping.map(initiator, responder)
    assert responder.inputs[0, 0] == 30.0

    # and if inputs were NOT reset across steps, the values still accumulate
    initiator.time = "t2"
    initiator.step_results[0, 0] = 5.0
    mapping.map(initiator, responder)
    assert responder.inputs[0, 0] == 35.0
