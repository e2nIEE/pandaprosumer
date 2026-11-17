"""
The plant -> circulation pump coupling conserves the plant's heat
(pandaprosumer.energy_system.control.controller.coupling.plant_pump_coupling).
"""
import numpy as np
import pandapipes
import pytest

from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.create_controlled import create_controlled_plant_pump_coupling
from pandaprosumer.energy_system.control.controller.coupling.plant_pump_coupling import (
    MAX_PLANT_WAIT_PASSES, PlantPumpCouplingControl, plant_heat_w, supply_temperature_k)
from pandaprosumer.mapping import FluidMixMapping

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


def _plant_net():
    """A circulation pump at an 85 degC setpoint feeding one 300 kW consumer, solved once."""
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
    return net, pump


def test_the_coupling_asks_the_plant_for_the_setpoint_on_the_network_return_flow():
    net, pump = _plant_net()
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


def _coupling_at_step_start():
    net, pump = _plant_net()
    controller = net.controller.at[create_controlled_plant_pump_coupling(net, pump, level=2, order=1), "object"]
    controller.time_step(net, 0)
    controller.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                            FluidMixMapping.MASS_FLOW_KEY: np.nan}
    return net, controller


def test_the_coupling_waits_for_a_plant_that_runs_again_before_it_delivers():
    """
    Field case (a heat pump charging a tank that feeds the network): when the tank's schedule
    changed, its return missed the one it promised its sources, so it ran them again on the next pass and
    delivered nothing on the first one. The coupling fixed the plant's heat on that first pass, at 0: the network
    ran cold for the hour while the tank booked the heat it discharged.
    """
    net, controller = _coupling_at_step_start()
    t_flow_k = net.circ_pump_pressure.t_flow_k.iat[0]

    controller.control_step(net)  # the tank re-runs its sources: nothing delivered yet
    assert controller.heat_w is None
    assert not controller.is_converged(net)
    assert net.circ_pump_pressure.t_flow_k.iat[0] == t_flow_k, "the solved network is left as it was"

    mdot_kg_per_s, t_return_k = controller._pump_result(net)
    controller.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 85.0,
                                            FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s}
    controller.control_step(net)  # the plant delivered on the second pass
    cp = float(net.fluid.get_heat_capacity((85.0 + CELSIUS_TO_K + t_return_k) / 2))
    assert controller.heat_w == pytest.approx(mdot_kg_per_s * cp * (85.0 + CELSIUS_TO_K - t_return_k))
    assert controller.heat_w > 0


def test_a_plant_that_never_delivers_gives_no_heat():
    net, controller = _coupling_at_step_start()
    for _ in range(MAX_PLANT_WAIT_PASSES):
        controller.control_step(net)
        assert controller.heat_w is None
    controller.control_step(net)
    assert controller.heat_w == 0.0
