"""
A tank charged and discharged at once through the same connections: the common flow short-circuits it.

Field case: a heat pump capped under a forced charge setpoint put all it made into the tank while the
network was served from the discharge. Each outlet was booked as if the other stream did not exist -- the
discharge drawn from the start-of-step layers, colder than the charge entering the same top layer -- so a tank
charged with 440 kW gave 140 kW at 51 degC to the network, its stored energy flat: ~1.7 MWh lost a day. The
charge water now reaches the discharge straight, only the net flow crosses the layers, and the tank's energy
balance closes.
"""
import pytest

from tests.integrations import test_shs_forced_setpoints as forced
from tests.integrations.test_shs_forced_setpoints import (
    MIN_USEFUL,
    N_LAYERS,
    N_STEPS,
    T_RETURN_DEMAND,
    _assert_shs_balances,
    _assert_source_interface,
    _run,
)

#: 15 min steps: long enough for the charge to cross a good part of the tank within a step, as hourly steps do
RESOL_S = 900


@pytest.fixture
def capped_forced_charge_into_a_cold_tank(monkeypatch):
    """A heat pump capped far under a forced charge setpoint, a cold tank, the demand served by the discharge."""
    monkeypatch.setattr(forced, "RESOL_S", RESOL_S)
    return _run(charge_setpoints=[50.0] * N_STEPS, hp_max_p_comp_kw=30.0,
                init_layer_temps_c=[T_RETURN_DEMAND] * N_LAYERS)


def test_the_tank_energy_balance_closes(capped_forced_charge_into_a_cold_tank):
    shs = capped_forced_charge_into_a_cold_tank["shs"]
    net_in_kwh = float(((shs["q_received_kw"] - shs["q_delivered_kw"]) * RESOL_S / 3600).sum())
    stored_kwh = float(shs["e_stored_kwh"].iloc[-1])
    assert stored_kwh > 0
    assert abs(net_in_kwh - stored_kwh) < 0.05 * net_in_kwh + 0.5, (net_in_kwh, stored_kwh)


def test_the_discharge_gets_the_charge_water_once_the_tank_is_usable(capped_forced_charge_into_a_cold_tank):
    dfs = capped_forced_charge_into_a_cold_tank
    shs = dfs["shs"]
    discharging = shs["mdot_discharge_kg_per_s"] > 1e-6
    assert discharging.any()
    assert (shs.loc[discharging, "t_discharge_out_c"] >= MIN_USEFUL - 0.5).all(), shs["t_discharge_out_c"]
    _assert_shs_balances(shs)
    _assert_source_interface(dfs)
