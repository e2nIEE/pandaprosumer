"""
The substation reads the network's supply temperature and nothing else: its mass flow comes from its own
demand chain (pandaprosumer.energy_system.control.controller.coupling.substation_supply_coupling).
"""
import numpy as np
import pandapipes
import pytest

from pandaprosumer.create_controlled import create_controlled_substation_supply_coupling
from pandaprosumer.energy_system.control.controller.coupling.substation_supply_coupling import (
    SubstationSupplyCouplingControl)
from pandaprosumer.mapping import FluidMixMapping


def _line_net():
    """One pump and one heat consumer joined by a feed and a return pipe, solved at 10 kg/s."""
    net = pandapipes.create_empty_network(fluid="water")
    j0, j1, r1, r0 = (pandapipes.create_junction(net, pn_bar=6, tfluid_k=358.15) for _ in range(4))
    pandapipes.create_circ_pump_const_pressure(net, flow_junction=j0, return_junction=r0, p_flow_bar=6,
                                               plift_bar=1, t_flow_k=358.15, type="pt")
    for a, b in ((j0, j1), (r1, r0)):
        pandapipes.create_pipe_from_parameters(net, a, b, length_km=0.5, diameter_m=0.2, k_mm=0.01,
                                               u_w_per_m2k=0.4, text_k=283.15)
    consumer = pandapipes.create_heat_consumer(net, j1, r1, qext_w=300e3, controlled_mdot_kg_per_s=10)
    pandapipes.set_user_pf_options(net, mode="bidirectional", ambient_temperature=283.15)
    pandapipes.pipeflow(net)
    return net, consumer


def test_the_coupling_hands_over_the_supply_temperature_without_a_mass_flow():
    net, consumer = _line_net()
    index = create_controlled_substation_supply_coupling(net, consumer, level=1, order=-1, name="nc_read_dmd_index")
    controller = net.controller.at[index, "object"]
    assert isinstance(controller, SubstationSupplyCouplingControl)
    assert (net.controller.at[index, "level"], net.controller.at[index, "order"]) == (1, -1)

    controller.control_step(net)

    [output] = controller.result_mass_flow_with_temp
    assert output[FluidMixMapping.TEMPERATURE_KEY] == pytest.approx(net.res_heat_consumer.t_from_k.iat[0] - 273.15)
    assert np.isnan(output[FluidMixMapping.MASS_FLOW_KEY])
    assert controller.applied


def test_one_output_per_fed_element_all_without_a_mass_flow():
    net, consumer = _line_net()
    index = create_controlled_substation_supply_coupling(net, consumer, n_outputs=2, level=1, order=-1)
    controller = net.controller.at[index, "object"]
    controller.control_step(net)
    outputs = controller.result_mass_flow_with_temp
    assert len(outputs) == 2
    assert outputs[0][FluidMixMapping.TEMPERATURE_KEY] == outputs[1][FluidMixMapping.TEMPERATURE_KEY]
    assert all(np.isnan(o[FluidMixMapping.MASS_FLOW_KEY]) for o in outputs)


def test_the_plain_coupling_still_hands_over_the_flow():
    """The refactored base class keeps its behaviour: temperature AND the solved mass flow."""
    from pandaprosumer.create_controlled import create_controlled_network_coupling

    net, consumer = _line_net()
    index = create_controlled_network_coupling(net, consumer, element_name="heat_consumer",
                                               result_columns=["t_from_k", "t_to_k", "mdot_from_kg_per_s"],
                                               temp_fluid_map_output_idx=0, mdot_fluid_map_output_idx=2)
    controller = net.controller.at[index, "object"]
    controller.control_step(net)
    [output] = controller.result_mass_flow_with_temp
    assert output[FluidMixMapping.MASS_FLOW_KEY] == pytest.approx(10.0)
