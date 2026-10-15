"""Stratified heat storage between a heat pump and a heat demand — physical invariants.

Instead of golden values, a 24 h day (charge, partial load, peaks above the heat pump, idle hours, a
peak that drains the tank) is run over a grid of demand feed / return temperatures, heat-pump supply
temperatures (``t_charge_target_c``) and the two wirings (heat pump -> tank -> demand, and heat pump
feeding the demand and the tank in parallel). Every hour must:

* close the tank's energy balance: the change of its internal energy equals the booked charge minus the
  booked discharge minus a small, non-negative wall loss;
* hand over what it books: heat pump ``q_cond`` == tank ``q_received`` (series), tank ``q_delivered`` ==
  demand ``q_received``;
* never over-serve the demand;
* keep every layer between the ambient (the wall loses towards it) and the hottest water that entered;
* never leave usable heat in the tank while the demand goes uncovered;
* report as ``e_stored_kwh`` the heat its layers hold against the initial state, and a usable share
  ``e_usable_kwh`` between 0 and that.
"""
import numpy as np
import pandas as pd
import pytest
from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer import (
    create_empty_prosumer_container,
    create_period,
    create_controlled_const_profile,
    create_controlled_heat_pump,
    create_controlled_stratified_heat_storage,
    create_controlled_heat_demand,
)
from pandaprosumer.controller.models import stratified_heat_storage as shs_module
from pandaprosumer.controller.models.stratified_heat_storage import MIN_USEFUL_MARGIN_K
from pandaprosumer.mapping import FluidMixMapping, GenericMapping
from pandaprosumer.run_time_series import run_timeseries

HP_MAX_P_COMP_KW = 100.0
#: kW of demand over the day: charge (0), partial load, a peak above the heat pump, idle, a draining peak
DEMAND_KW = [0] * 4 + [150] * 3 + [500] * 3 + [0] * 3 + [200] * 2 + [800] * 4 + [100] * 5
#: The balance may miss by this much per hour plus a share of the energy exchanged: the layer solver
#: diffuses numerically and the booking takes one heat capacity per stream
BALANCE_TOL_KWH = 3.0
BALANCE_TOL_SHARE = 0.03
#: kWh per hour a 10 m3 tank may lose through its wall at ~80 °C with the default insulation
MAX_WALL_LOSS_KWH = 2.0
POWER_TOL_KW = 1.0
T_EXT_C = 20.0


def _layer_energy_kwh(layers_c, controller, t_ref_c):
    """Internal energy of the tank above ``t_ref_c`` (kWh)."""
    return sum(float(controller.fluid.get_density(273.15 + t_c)) * controller.A_m2 * controller.dz_m
               * float(controller.fluid.get_heat_capacity(273.15 + t_c)) * (t_c - t_ref_c)
               for t_c in layers_c) / 3.6e6


def _run(monkeypatch, t_feed_c, t_return_c, t_target_c, parallel):
    snapshots = []
    original = shs_module.StratifiedHeatStorageController.time_step

    def time_step(self, prosumer, time):
        snapshots.append(np.array(self._layer_temps_c, dtype=float))
        return original(self, prosumer, time)

    monkeypatch.setattr(shs_module.StratifiedHeatStorageController, "time_step", time_step)

    prosumer = create_empty_prosumer_container()
    n = len(DEMAND_KW)
    period = create_period(prosumer, 3600, "2020-01-01 00:00:00", "2020-01-01 23:59:59", "utc", "default")
    data = pd.DataFrame({"t_evap_in_c": [25.0] * n, "q_demand_kw": DEMAND_KW,
                         "t_feed_demand_c": [t_feed_c] * n, "t_return_demand_c": [t_return_c] * n},
                        index=pd.date_range("2020-01-01", periods=n, freq="3600s", tz="utc"))
    columns = list(data.columns)
    cp = create_controlled_const_profile(prosumer, columns, columns, DFData(data), period, 0, 0)
    hp = create_controlled_heat_pump(prosumer, period=period, level=1, order=0, max_p_comp_kw=HP_MAX_P_COMP_KW,
                                     delta_t_evap_c=5, pinch_c=0)
    shs = create_controlled_stratified_heat_storage(prosumer, period=period, level=1, order=1,
                                                    tank_height_m=10., tank_internal_radius_m=.564,
                                                    tank_external_radius_m=.664, insulation_thickness_m=.1,
                                                    n_layers=50, min_useful_temp_c=t_feed_c, t_ext_c=T_EXT_C,
                                                    max_dt_s=10, t_charge_target_c=t_target_c,
                                                    init_layer_temps_c=[t_return_c] * 50)
    hd = create_controlled_heat_demand(prosumer, period=period, level=1, order=2)
    GenericMapping(prosumer, initiator_id=cp, initiator_column="t_evap_in_c", responder_id=hp,
                   responder_column="t_evap_in_c", order=0)
    for column in ("q_demand_kw", "t_feed_demand_c", "t_return_demand_c"):
        GenericMapping(prosumer, initiator_id=cp, initiator_column=column, responder_id=hd,
                       responder_column=column, order=0)
    if parallel:
        FluidMixMapping(prosumer, initiator_id=hp, responder_id=hd, order=0)
        FluidMixMapping(prosumer, initiator_id=hp, responder_id=shs, order=1)
    else:
        FluidMixMapping(prosumer, initiator_id=hp, responder_id=shs, order=0)
    FluidMixMapping(prosumer, initiator_id=shs, responder_id=hd, order=0)

    run_timeseries(prosumer, period, True)
    results = [prosumer.time_series.loc[i].data_source.df.reset_index(drop=True) for i in range(3)]
    controller = prosumer.controller.iloc[shs].object
    snapshots.append(np.array(controller._layer_temps_c, dtype=float))
    return results, controller, snapshots


CASES = [
    # (feed, return, heat-pump supply target)
    (80.0, 20.0, None),
    (80.0, 40.0, None),
    (70.0, 40.0, None),
    (60.0, 30.0, None),
    (60.0, 45.0, None),
    (60.0, 30.0, 70.0),
    (70.0, 40.0, 80.0),
]


@pytest.mark.parametrize("parallel", [False, True], ids=["series", "parallel"])
@pytest.mark.parametrize("t_feed_c, t_return_c, t_target_c", CASES,
                         ids=[f"{f:g}-{r:g}-{'demand' if t is None else f'{t:g}'}" for f, r, t in CASES])
def test_shs_energy_invariants(monkeypatch, t_feed_c, t_return_c, t_target_c, parallel):
    (hp, shs, hd), controller, layers = _run(monkeypatch, t_feed_c, t_return_c,
                                             np.nan if t_target_c is None else t_target_c, parallel)
    t_supply_c = t_feed_c if t_target_c is None else max(t_feed_c, t_target_c)
    energy = [_layer_energy_kwh(t, controller, t_return_c) for t in layers]
    failures = []
    for h in range(len(DEMAND_KW)):
        d_u = energy[h + 1] - energy[h]
        loss = shs.q_charge_kw[h] - shs.q_discharge_kw[h] - d_u
        tol = BALANCE_TOL_KWH + BALANCE_TOL_SHARE * (shs.q_charge_kw[h] + shs.q_discharge_kw[h])
        if not -tol <= loss <= MAX_WALL_LOSS_KWH + tol:
            failures.append(f"h{h}: tank balance off by {loss:.1f} kWh (charge {shs.q_charge_kw[h]:.1f}, "
                            f"discharge {shs.q_discharge_kw[h]:.1f}, dU {d_u:.1f})")
        if not parallel and abs(hp.q_cond_kw[h] - shs.q_received_kw[h]) > POWER_TOL_KW:
            failures.append(f"h{h}: heat pump q_cond {hp.q_cond_kw[h]:.1f} != tank q_received "
                            f"{shs.q_received_kw[h]:.1f}")
        if hd.q_uncovered_kw[h] < -POWER_TOL_KW:
            failures.append(f"h{h}: demand over-served by {-hd.q_uncovered_kw[h]:.1f} kW")
        if not T_EXT_C - 0.1 <= layers[h + 1].min() and layers[h + 1].max() <= t_supply_c + 0.1:
            failures.append(f"h{h}: layers {layers[h + 1].min():.2f}..{layers[h + 1].max():.2f} °C "
                            f"outside {T_EXT_C:g}..{t_supply_c:g}")
        if abs(shs.e_stored_kwh[h] - energy[h + 1]) > 0.01 * abs(energy[h + 1]) + 1.0:
            failures.append(f"h{h}: e_stored {shs.e_stored_kwh[h]:.1f} kWh, layers hold {energy[h + 1]:.1f}")
        if not -1e-6 <= shs.e_usable_kwh[h] <= max(0.0, shs.e_stored_kwh[h]) + 1.0:
            failures.append(f"h{h}: e_usable {shs.e_usable_kwh[h]:.1f} outside 0..{shs.e_stored_kwh[h]:.1f} kWh")
        usable = layers[h][-1] >= t_feed_c - MIN_USEFUL_MARGIN_K and energy[h] > 5.0
        if hd.q_uncovered_kw[h] > POWER_TOL_KW and usable and shs.q_discharge_kw[h] < 1.0:
            failures.append(f"h{h}: {hd.q_uncovered_kw[h]:.1f} kW uncovered while the tank holds "
                            f"{energy[h]:.0f} kWh with its top at {layers[h][-1]:.2f} °C")
    if not parallel:
        if not np.allclose(shs.q_delivered_kw, hd.q_received_kw, atol=POWER_TOL_KW):
            failures.append("tank q_delivered != demand q_received")
    assert not failures, "\n".join(failures)
