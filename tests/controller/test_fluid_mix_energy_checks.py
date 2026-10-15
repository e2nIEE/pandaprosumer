"""The two generic FluidMix energy checks of MappedController (both emit EnergyLeakWarning).

* ``_check_fluid_mix_balance`` (producer side): besides the dispatched mass flow, the heat a producer books must
  be the heat its labelled outlet stream carries, ``mdot * cp * (t_out - t_in)``, including with no flow.
* ``_check_return_contract`` (responder side): a responder that finalizes on a return temperature other than the
  one it promised its initiators (``t_keep_return_c``) leaves the difference booked on one side only.
"""
import warnings

import numpy as np
import pandas as pd
import pytest

from pandaprosumer import create_empty_prosumer_container, create_period, create_controlled_gas_boiler
from pandaprosumer.controller.mapped import EnergyLeakWarning

CP = 4.18


@pytest.fixture
def controller():
    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, 1, "2020-01-01 00:00:00", "2020-01-01 00:00:09", "utc", "default")
    index = create_controlled_gas_boiler(prosumer, period=period, max_q_kw=500)
    ctrl = prosumer.controller.iloc[index].object
    ctrl.time = pd.Timestamp("2020-01-01 00:00:00", tz="utc")
    return prosumer, ctrl


def _leaks(call):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        call()
    return [w for w in caught if issubclass(w.category, EnergyLeakWarning)]


@pytest.mark.parametrize("q_kw, mdot, t_in, t_out, leaks", [
    (CP * 2 * 40, 2.0, 30.0, 70.0, False),      # the stream carries what is booked
    (20.0, 95.7, 30.0, 30.0005, True),          # min power booked on a stream at the requested ~0 lift
    (20.0, 0.0, 30.0, 30.0, True),              # heat booked with no flow at all
    (0.0, 13.0, 62.0, 62.0, False),             # no heat, no lift: nothing to report on the producer side
])
def test_producer_books_the_heat_its_stream_carries(controller, q_kw, mdot, t_in, t_out, leaks):
    prosumer, ctrl = controller
    found = _leaks(lambda: ctrl._check_fluid_mix_balance(prosumer, q_kw, mdot, t_out, t_in, np.array([mdot]),
                                                         cp_fluid_kj_per_kgk=CP))
    assert bool(found) is leaks, [str(w.message) for w in found]


def test_producer_label_check_needs_the_fluid_cp(controller):
    """Without the fluid's cp the label is not checked (a default water cp would flag glycol loops)."""
    prosumer, ctrl = controller
    assert not _leaks(lambda: ctrl._check_fluid_mix_balance(prosumer, 20.0, 0.0, 30.0, 30.0, np.array([0.0])))


@pytest.mark.parametrize("t_keep_return_c, t_return_c, mdot, leaks", [
    (51.0, 51.0, 13.0, False),     # returned what was promised
    (62.0, 51.0, 13.0, True),      # promised 62 degC to the source, returned 51: ~600 kW booked on one side
    (62.0, 51.0, 0.0, False),      # no flow received: nothing booked
    (np.nan, 51.0, 13.0, False),   # nothing was promised (initiator on another level / generic mapping)
    (51.0, 51.01, 13.0, False),    # within the 1 kW tolerance
])
def test_responder_returns_what_it_promised(controller, t_keep_return_c, t_return_c, mdot, leaks):
    prosumer, ctrl = controller
    ctrl.t_keep_return_c = t_keep_return_c
    found = _leaks(lambda: ctrl._check_return_contract(prosumer, t_return_c, mdot, CP))
    assert bool(found) is leaks, [str(w.message) for w in found]
    if leaks:
        assert f"{mdot * CP * (t_keep_return_c - t_return_c):.3f} kW" in str(found[0].message)
