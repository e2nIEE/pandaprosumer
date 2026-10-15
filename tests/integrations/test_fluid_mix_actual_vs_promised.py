"""Energy across a FluidMix boundary must be booked with the temperatures really exchanged.

Design rule: a model computes its physics and its energy with the temperature and mass flow it really
receives, never with the one it requested (responder side) or the return its responders promised
(initiator side). Each test drives one model into a branch where it used to book against a requested or
promised value, and asserts that both sides of the boundary book the same energy:

* heat demand fed colder than its return: it returned the water at the contract return (negative heat, and
  the source's rerun never fired); it now lets it through at its own temperature;
* boilers short of power with several responders: the return they booked was re-weighted by the delivered
  flows only beyond 1 K; now down to TEMPERATURE_CONVERGENCE_THRESHOLD_C (same in the heat pump and the
  heat exchanger);
* electric boiler held at min_p_kw with no usable lift, or with allow_stop=False and no flow: it booked heat
  the water did not carry; it now raises its outlet temperature / runs at its previous lift.

See also test_shs_hp_ecs_energy_balance.py (heat pump that cannot run).
"""

import numpy as np
import pandas as pd
import pytest

from pandaprosumer import (
    create_empty_prosumer_container,
    create_period,
    create_controlled_const_profile,
    create_controlled_electric_boiler,
    create_controlled_gas_boiler,
    create_controlled_heat_demand,
    create_controlled_heat_exchanger,
    DFData,
)
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.run_time_series import run_timeseries

TOL_KW = 0.1


def _prosumer(columns, n_steps=1, resol_s=1):
    prosumer = create_empty_prosumer_container()
    start = "2020-01-01 00:00:00"
    end = pd.Timestamp(start) + n_steps * pd.Timedelta(seconds=resol_s) - pd.Timedelta(seconds=1)
    period = create_period(prosumer, resol_s, start, end, "utc", "default")
    data = pd.DataFrame(columns, index=pd.date_range(start, periods=n_steps, freq=f"{resol_s}s", tz="utc"))
    cp = create_controlled_const_profile(prosumer, list(data.columns), list(data.columns), DFData(data), period, 0, 0)
    return prosumer, period, cp


def _results(prosumer):
    return [prosumer.time_series.loc[i].data_source.df for i in prosumer.time_series.index]


@pytest.mark.parametrize("t_primary_c", [30.0, 38.0])
def test_heat_exchanger_with_a_too_cold_primary_books_what_the_demand_receives(t_primary_c):
    """Primary at 30 or 38 degC, demand asking 40 degC feed / 35 degC return: with a 5 K pinch the secondary
    cannot leave above 33 degC, below the demand return. The exchanger first guesses a lower secondary inlet;
    the demand, fed colder than its return, must let the water through at its own temperature (it used to
    return it at the 35 degC contract and book -400 kW), so the rerun settles on no exchange on both sides."""
    prosumer, period, cp = _prosumer({"t_feed_in_c": [t_primary_c], "q_demand_kw": [200.0]})
    hx = create_controlled_heat_exchanger(prosumer, period=period, level=1, order=0, name="hx",
                                          t_1_in_nom_c=80, t_1_out_nom_c=40, t_2_in_nom_c=17, t_2_out_nom_c=57,
                                          mdot_2_nom_kg_per_s=70.0, delta_t_hot_default_c=5, max_q_kw=4000)
    hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1, name="hd",
                                       t_feed_demand_c=40.0, t_return_demand_c=35.0)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="t_feed_in_c",
                   responder_id=hx, responder_column="t_feed_in_c", order=0)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q_demand_kw",
                   responder_id=hd, responder_column="q_demand_kw", order=1)
    FluidMixMapping(container=prosumer, initiator_id=hx, responder_id=hd, order=0)
    run_timeseries(prosumer, period, False)
    hx_df, hd_df = _results(prosumer)
    q_hx, q_hd = hx_df.q_exchanged_kw.iloc[0], hd_df.q_received_kw.iloc[0]
    assert abs(q_hx - q_hd) <= TOL_KW, (
        f"exchanger books {q_hx:.1f} kW, demand receives {q_hd:.1f} kW "
        f"(secondary {hx_df.t_2_in_c.iloc[0]:.2f} -> {hx_df.t_2_out_c.iloc[0]:.2f} degC at "
        f"{hx_df.mdot_2_kg_per_s.iloc[0]:.2f} kg/s; the demand returns at {hd_df.t_out_c.iloc[0]:.2f} degC)")
    assert abs(hx_df.t_2_in_c.iloc[0] - hd_df.t_out_c.iloc[0]) <= 0.01


@pytest.mark.parametrize("kind", ["electric", "gas"])
@pytest.mark.parametrize("q2_kw, max_kw", [(5.0, 102.5), (30.0, 110.0)])
def test_boiler_short_of_power_books_the_heat_its_two_demands_receive(kind, q2_kw, max_kw):
    """One boiler short of power for two demands (100 kW at 70/30 degC, q2 at 70/50 degC): it must book its heat
    on the return of the flows it really delivers. It used to keep the return mix of the REQUESTED flows unless
    re-weighting moved it by more than 1 K (+1.2 kW created in the first case, +1.4 kW in the second)."""
    prosumer, period, cp = _prosumer({"q1": [100.0], "q2": [q2_kw]})
    if kind == "electric":
        b = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0, max_p_kw=max_kw,
                                              efficiency_percent=100, overflow_strategy="cap")
    else:
        b = create_controlled_gas_boiler(prosumer, period=period, level=1, order=0, max_q_kw=max_kw,
                                         overflow_strategy="cap")
    h1 = create_controlled_heat_demand(prosumer, period=period, level=1, order=1, t_feed_demand_c=70,
                                       t_return_demand_c=30)
    h2 = create_controlled_heat_demand(prosumer, period=period, level=1, order=2, t_feed_demand_c=70,
                                       t_return_demand_c=50)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q1", responder_id=h1,
                   responder_column="q_demand_kw", order=0)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q2", responder_id=h2,
                   responder_column="q_demand_kw", order=1)
    FluidMixMapping(container=prosumer, initiator_id=b, responder_id=h1, order=0)
    FluidMixMapping(container=prosumer, initiator_id=b, responder_id=h2, order=1)
    run_timeseries(prosumer, period, False)
    b_df, d1, d2 = _results(prosumer)
    q_booked = b_df.q_kw.iloc[0]
    q_received = d1.q_received_kw.iloc[0] + d2.q_received_kw.iloc[0]
    assert abs(q_booked - q_received) <= TOL_KW, (
        f"{kind} boiler books {q_booked:.3f} kW (t_in {b_df.t_in_c.iloc[0]:.3f} degC), "
        f"the demands receive {q_received:.3f} kW")


def test_electric_boiler_at_min_power_hands_over_the_heat_it_books():
    """Demand of 0.2 kW over a 0.5 mK lift, boiler min power 20 kW: the boiler used to book 20 kW (and 20 kW of
    electricity) while the stream it delivered at the requested temperatures carried 0.2 kW. It now raises its
    outlet temperature so the water carries the 20 kW (the demand is over-served, as with the gas boiler)."""
    prosumer, period, cp = _prosumer({"q": [0.2, 0.2]}, n_steps=2)
    b = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0, max_p_kw=100, min_p_kw=20,
                                          efficiency_percent=100, overflow_strategy="cap")
    hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1, t_feed_demand_c=30.0005,
                                       t_return_demand_c=30.0)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q", responder_id=hd,
                   responder_column="q_demand_kw", order=0)
    FluidMixMapping(container=prosumer, initiator_id=b, responder_id=hd, order=0)
    run_timeseries(prosumer, period, False)
    b_df, hd_df = _results(prosumer)
    gap = (b_df.q_kw - hd_df.q_received_kw).abs()
    assert (gap <= TOL_KW).all(), f"boiler books {b_df.q_kw.values} kW, demand receives {hd_df.q_received_kw.values} kW"


def test_electric_boiler_that_cannot_stop_books_no_heat_it_does_not_deliver():
    """Demand 50 kW then 0: with allow_stop=False the boiler used to keep booking 20 kW of heat at zero flow. It now
    runs at its previous lift (as the gas boiler does), so the 20 kW reach the demand."""
    prosumer, period, cp = _prosumer({"q": [50.0, 0.0, 0.0]}, n_steps=3)
    b = create_controlled_electric_boiler(prosumer, period=period, level=1, order=0, max_p_kw=100, min_p_kw=20,
                                          efficiency_percent=100, overflow_strategy="cap", allow_stop=False)
    hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=1, t_feed_demand_c=70,
                                       t_return_demand_c=30)
    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="q", responder_id=hd,
                   responder_column="q_demand_kw", order=0)
    FluidMixMapping(container=prosumer, initiator_id=b, responder_id=hd, order=0)
    run_timeseries(prosumer, period, False)
    b_df, hd_df = _results(prosumer)
    gap = (b_df.q_kw - hd_df.q_received_kw).abs()
    assert (gap <= TOL_KW).all(), (f"boiler books {b_df.q_kw.values} kW at {b_df.mdot_kg_per_s.values} kg/s, "
                                   f"demand receives {hd_df.q_received_kw.values} kW")
