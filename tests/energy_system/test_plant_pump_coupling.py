"""
The plant -> circulation pump coupling conserves the plant's heat
(pandaprosumer.energy_system.control.controller.coupling.plant_pump_coupling).
"""
import numpy as np
import pandapipes
import pytest

from pandaprosumer.create_controlled import create_controlled_plant_pump_coupling
from pandaprosumer.energy_system.control.controller.coupling.plant_pump_coupling import (
    PlantPumpCouplingControl, plant_heat_w, supply_temperature_k)

CP = 4190.0


def test_the_pump_injects_the_plant_heat_capped_at_the_plant_temperature():
    heat = plant_heat_w(mdot_plant_kg_per_s=5.0, t_plant_k=358.15, t_inlet_k=338.15, cp_j_per_kgk=CP)
    assert heat == pytest.approx(5.0 * CP * 20.0)
    # 10 kg/s in the network, half of it bypasses the plant: mixed supply halfway
    assert supply_temperature_k(heat, 10.0, 338.15, CP, 358.15) == pytest.approx(348.15)
    # more heat than the network flow can take: never hotter than the plant's water
    assert supply_temperature_k(4 * heat, 10.0, 338.15, CP, 358.15) == pytest.approx(358.15)
    assert plant_heat_w(np.nan, np.nan, 338.15, CP) == 0.0
    assert supply_temperature_k(0.0, 10.0, 338.15, CP, np.nan) == pytest.approx(338.15)


def test_the_coupling_asks_the_plant_for_the_setpoint_on_the_network_return_flow():
    net = pandapipes.create_empty_network(fluid="water")
    j0, j1, r1, r0 = (pandapipes.create_junction(net, pn_bar=6, tfluid_k=358.15) for _ in range(4))
    pump = pandapipes.create_circ_pump_const_pressure(net, flow_junction=j0, return_junction=r0, p_flow_bar=6,
                                                      plift_bar=1, t_flow_k=358.15, type="pt")
    for a, b in ((j0, j1), (r1, r0)):
        pandapipes.create_pipe_from_parameters(net, a, b, length_km=0.5, diameter_m=0.2, k_mm=0.01,
                                               u_w_per_m2k=0.4, text_k=283.15)
    pandapipes.create_heat_consumer(net, j1, r1, qext_w=300e3, controlled_mdot_kg_per_s=10)
    pandapipes.set_user_pf_options(net, mode="bidirectional", ambient_temperature=283.15)
    pandapipes.pipeflow(net)

    index = create_controlled_plant_pump_coupling(net, pump, level=2, order=1, name="plant_pump")
    controller = net.controller.at[index, "object"]
    assert isinstance(controller, PlantPumpCouplingControl)
    assert controller.setpoint_k == pytest.approx(358.15)
    assert (net.controller.at[index, "level"], net.controller.at[index, "order"]) == (2, 1)

    # a short step left the supply below the setpoint: the plant is still asked for the setpoint
    net.circ_pump_pressure.t_flow_k = 348.15
    pandapipes.pipeflow(net)
    t_feed_c, t_return_c, mdot = controller._t_m_to_receive_init(net)
    assert t_feed_c == pytest.approx([85.0])
    assert t_return_c[0] == pytest.approx(net.res_circ_pump_pressure.t_from_k.iat[0] - 273.15)
    assert mdot == pytest.approx([10.0])
