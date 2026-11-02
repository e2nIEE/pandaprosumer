"""
A coupling that writes prosumer outputs into the network is not converged while those outputs changed after it wrote
them: a substation exchanger reruns within the level once its demand answers, and the network must get the final
answer, not the first (game sandbox: 220 kW extracted from a 42 degC network the exchanger finally drew nothing
from, cooling the water below 0 degC and losing the heat).
"""
import numpy as np
import pandapipes
import pandas as pd
import pytest

from pandaprosumer.create_controlled import create_controlled_network_coupling


@pytest.fixture
def coupling():
    net = pandapipes.create_empty_network(fluid="water")
    j0, j1 = (pandapipes.create_junction(net, pn_bar=10, tfluid_k=350) for _ in range(2))
    hc = pandapipes.create_heat_consumer(net, from_junction=j0, to_junction=j1, qext_w=100e3,
                                         controlled_mdot_kg_per_s=3)
    net["res_heat_consumer"] = pd.DataFrame({"t_from_k": [350.], "t_to_k": [330.], "mdot_from_kg_per_s": [3.]},
                                            index=[hc])
    index = create_controlled_network_coupling(net, hc, input_columns=['qext_w', 'controlled_mdot_kg_per_s'])
    controller = net.controller.object.at[index]
    controller.time = "2020-01-01 00:00:00"
    return net, hc, controller


def test_a_coupling_written_with_its_current_inputs_is_converged(coupling):
    net, hc, controller = coupling
    controller.inputs = np.array([[220e3, 1.8]])
    controller.control_step(net)
    assert controller.is_converged(net)
    assert net.heat_consumer.at[hc, "qext_w"] == pytest.approx(220e3)


def test_inputs_changed_after_the_write_unconverge_it_until_rewritten(coupling):
    net, hc, controller = coupling
    controller.inputs = np.array([[220e3, 1.8]])
    controller.control_step(net)
    controller.inputs = np.array([[0., 0.]])  # the exchanger reran: it finally draws nothing
    assert not controller.is_converged(net)
    controller.control_step(net)
    assert controller.is_converged(net)
    assert net.heat_consumer.at[hc, "qext_w"] == 0
    assert net.heat_consumer.at[hc, "controlled_mdot_kg_per_s"] == 0
