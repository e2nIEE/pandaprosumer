# Mixing Valve (3-way valve) — Design

Date: 2026-07-21
Status: approved (design discussion in session; spec pending user review)

## Purpose

A district-heating producer often supplies hotter fluid (e.g. 95 °C) than the
demand wishes to receive (e.g. 80 °C). A 3-way mixing valve placed between them
recirculates part of the cold return (e.g. 70 °C) and mixes it into the supply,
so the demand receives its wished feed temperature while the producer keeps its
own supply temperature. The new `mixing_valve` component models this with exact
mass and energy conservation.

```text
producer ──(mdot_in @ t_in=95°C)──▶ ┌─────────────┐ ──(mdot_out @ t_out=80°C)──▶ demand
                                    │ mixing_valve │
producer ◀─(mdot_in @ t_return)──── └─────▲───────┘ ◀─(mdot_out @ t_return=70°C)─ demand
                                          │
                                          └── mdot_recirc @ t_return (internal recirculation)
```

## Approach

New full library component (element + data model + controller + create
functions + docs + tests), following the `add-component` skill checklist. The
controller copies the *intermediate component* shape of
`HeatExchangerController` (`src/pandaprosumer/controller/models/heat_exchanger.py`):
upstream `FluidMixMapping` initiator → controller → downstream `FluidMixMapping`
responders, with the HX-style reapply/convergence state
(`t_previous_*` + `t_keep_return_c` check).

Rejected alternatives:

- Extending `FluidMixMapping` with a target temperature — buries physics in the
  mapping layer and breaks the four-invariant contract semantics.
- Emulating with a `heat_exchanger` configuration — an HX has separate circuits
  and temperature-approach constraints; it cannot represent direct
  recirculation mixing of the same fluid.

## Physics (per timestep)

Downstream responders request `(t_out_req_c, t_return_req_c, mdot_tab_req)`;
let `mdot_out = sum(mdot_tab_req)`. The valve receives hot fluid at the actual
temperature `t_in_c` from the upstream producer.

Nominal mixing case (`t_in_c > t_out_req_c`):

- Hot-leg flow:
  `mdot_in = mdot_out * (t_out_req_c - t_return_req_c) / (t_in_c - t_return_req_c)`
- Recirculation: `mdot_recirc = mdot_out - mdot_in` (≥ 0 by construction)
- Delivered feed temperature: `t_out_c = t_out_req_c`

Mass conservation holds by construction (`mdot_in + mdot_recirc = mdot_out`).
Energy conservation is exact under the constant-cp mixing rule:
`mdot_in * cp * (t_in_c - t_return_req_c) = mdot_out * cp * (t_out_c - t_return_req_c)`,
with `cp` evaluated once at the mean temperature `(t_in_c + t_return_req_c)/2`
and used consistently on both sides. This is the documented model assumption
(same fluid, cp treated constant across the valve; no heat loss, no pressure
modeling).

The producer therefore sees return temperature `t_return_req_c` and mass flow
`mdot_in` only, so `q_producer == q_demand` across the valve — the valve
transforms temperature/mass-flow but neither creates nor destroys energy.

### Edge cases

1. **Cold supply** (`t_in_c <= t_out_req_c`): full pass-through. No
   recirculation (`mdot_recirc = 0`), forward `mdot_out` at `t_in_c`. The
   demand receives colder-than-wished fluid and accounts for the shortfall
   itself (this is what a real fully-open 3-way valve does).
2. **Upstream delivers more than `mdot_in`** (`input_mass_flow_with_temp`
   fixed by the producer, received flow `R > mdot_in`): recirculation shrinks
   to `mdot_recirc = max(0, mdot_out - R)` and the mixed temperature rises
   above target per the mixing rule
   `t_out_c = (R * t_in_c + mdot_recirc * t_return_req_c) / (R + mdot_recirc)`
   — energy stays exactly balanced (like boilers raising `t_out_c`, the
   surplus heat is carried downstream, not dropped). Once `R >= mdot_out`,
   `mdot_recirc = 0`, everything passes through at `t_in_c` and the mass-flow
   surplus `R - mdot_out` is dispatched per `overflow_strategy`
   (`dump_proportional` default) via `_merit_order_mass_flow`. No energy leak.
3. **Upstream delivers less than `mdot_in`**: hold `t_out_c` at target and
   scale down delivered flow:
   `mdot_out_actual = mdot_received * (t_in_c - t_return_req_c) / (t_out_req_c - t_return_req_c)`;
   `_merit_order_mass_flow` dispatches the reduced flow across responders.
4. **Zero/degenerate demand** (`mdot_out < 1e-6` or
   `t_out_req_c - t_return_req_c < 1e-3`): no exchange — `mdot_in = 0`,
   `mdot_recirc = 0`, pass-through of any provided flow at `t_in_c` (same
   handling as the HX zero-exchange branch).
5. **Degenerate mixing denominator** (`t_in_c - t_return_req_c < 1e-3` while
   demand is non-degenerate): treat as cold supply (case 1) — the supply
   cannot heat the return at all.

### Upstream request

`_t_m_to_receive_init` requests feed at the element parameter `t_in_nom_c`
(e.g. 95 °C), return at `t_return_req_c`, and mass flow `mdot_in` computed at
`t_in_nom_c`. When a previous non-converged step stored state
(`t_previous_*`), that state is returned instead (HX pattern).
`t_m_to_receive_for_t(prosumer, t_feed_c)` computes `mdot_in` for an arbitrary
proposed feed temperature so upstream producers can iterate.

### Convergence / reapply

Same mechanism as the HX `control_step` tail: if the return temperature
promised upstream (`t_keep_return_c`) differs from the computed one by more
than `TEMPERATURE_CONVERGENCE_THRESHOLD_C`, `_unapply_initiators` and store
`t_previous_*` for the rerun. Note the valve's return to the producer is the
responders' return temperature unchanged, so convergence is expected to be
immediate in single-responder setups. The multi-responder return-temperature
recalculation loop (HX lines ~454–467) is copied for the reduced-flow case.

`self._check_fluid_mix_balance(...)` is called right before
`self.finalize(...)` (mandatory safety net, per `add-component`).

## Files

| File | Content |
| --- | --- |
| `src/pandaprosumer/element/mixing_valve.py` | `MixingValveElementData`: `name`, `t_in_nom_c` ('f8'), `overflow_strategy` (str, default `'dump_proportional'`), `in_service` (bool) |
| `src/pandaprosumer/controller/data_model/mixing_valve.py` | `MixingValveControllerData`: no required time-series inputs; result columns below |
| `src/pandaprosumer/controller/models/mixing_valve.py` | `MixingValveController(BasicProsumerController)` — physics above |
| `src/pandaprosumer/create.py` | `create_mixing_valve` with full parameter docstring |
| `src/pandaprosumer/create_controlled.py` | `create_controlled_mixing_valve` |
| `doc/source/elements/mixing_valve.rst` | Physics, equations, assumptions, parameter/IO tables; added to elements toctree (h2 `===` underlines per repo quirk) |
| `tests/models/test_mixing_valve.py` | Unit tests (see below) |
| `tests/integrations/test_mixing_valve_integration.py` | Producer → valve → demand integration tests |

Element/`create` registration follows the heat-exchanger sibling. New element
columns append at the end before `in_service` per the `models-parameters`
ordering rules; `test_define_element*` column-order tests updated positionally.

### Result columns

`["q_delivered_kw", "mdot_in_kg_per_s", "t_in_c", "mdot_recirc_kg_per_s", "mdot_out_kg_per_s", "t_out_c", "t_return_c"]`

- `q_delivered_kw` — thermal power delivered to responders [kW]
- `mdot_in_kg_per_s` — hot-leg mass flow drawn from the producer [kg/s]
- `t_in_c` — received supply temperature [°C]
- `mdot_recirc_kg_per_s` — recirculated return mass flow [kg/s]
- `mdot_out_kg_per_s` — mixed flow delivered downstream [kg/s]
- `t_out_c` — mixed feed temperature delivered downstream [°C]
- `t_return_c` — return temperature (identical toward producer and from responders) [°C]

Names follow `doc/source/about/units.rst` (unit last, adjectives between).

## Testing

Unit tests (`t_m_to_deliver` stub + direct `control_step`, per AGENTS.md):

- Nominal case 95/80/70: `mdot_in/mdot_out == (80-70)/(95-70) == 0.4`, mass and
  energy balances exact, `t_out_c == 80`.
- Cold supply (78 °C received, 80 wished): pass-through, `mdot_recirc == 0`.
- Provided mdot greater than needed: recirculation reduction, then hot
  pass-through with surplus dispatch.
- Provided mdot smaller than needed: `t_out_c` held, flow scaled down.
- Zero demand; degenerate temperatures; invalid inputs (negative mdot, NaN).

Integration tests (gas boiler → mixing_valve → heat demand, `run_timeseries`):

- The four FluidMix interface invariants asserted at **both** interfaces with
  `_assert_interface_consistent`
  (`tests/integrations/test_overflow_strategy_consistency.py` helper).
- Energy conservation across the valve: `q_producer == q_demand`.
- Mass relation: `mdot_producer == mdot_demand - mdot_recirc`.
- No unexpected `EnergyLeakWarning`.
- `create_period` called with positional args (pandapower 2.14.11 pin).

## Done criteria

Per `add-component`: component imports; minimal `create_mixing_valve` works in
`pandaprosumer_os/.venv`; all files mutually consistent; honors
`overflow_strategy` and calls `_check_fluid_mix_balance`; unit + integration
tests pass; docs build clean (`cd doc && make clean html`).
