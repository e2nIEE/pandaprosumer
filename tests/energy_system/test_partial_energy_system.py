"""Energy systems that contain only prosumers (no net) or only nets (no prosumer).

A study with no district-heating / electrical network is still a valid energy system
(a set of independent prosumers), and a network without any prosumer is valid too.
The energy-system runner must handle both partial cases instead of raising
``NetCalculationNotConverged`` when there is no net to drive convergence.
"""

import numpy as np
import pandas as pd
import pandapipes
import pytest
from pandapower.control.run_control import ControllerNotConverged

from pandaprosumer import (
    DFData,
    create_empty_prosumer_container,
    create_controlled_const_profile,
    create_controlled_heat_pump,
    create_controlled_heat_demand,
)
from pandaprosumer.create import create_period
from pandaprosumer.mapping import GenericMapping, FluidMixMapping
from pandaprosumer.energy_system import (
    create_empty_energy_system,
    add_net_to_energy_system,
    add_pandaprosumer_to_energy_system,
)
from pandaprosumer.energy_system.timeseries.run_time_series_energy_system import (
    run_timeseries as run_time_series_system,
)


RESOL_S = 3600
START = "2020-01-01 00:00:00"
N_STEPS = 4


def _period_end():
    return pd.Timestamp(START) + N_STEPS * pd.Timedelta(f"00:00:{RESOL_S}") - pd.Timedelta("00:00:01")


def _self_contained_prosumer(name="prosumer_hp"):
    """A const-profile -> heat-pump -> heat-demand prosumer that runs standalone (no coupling)."""
    prosumer = create_empty_prosumer_container(name=name)
    data = pd.DataFrame(
        {
            "Tin_evap": [25, 25, 25, 25],
            "demand_1_kw": [50, 200, 337.512 + 30, 0],
            "tdmd_feed1_c": [76.85, 76.85, 76.85, 76.85],
            "tdmd_return1_c": [30, 30, 30, 30],
        }
    )
    dur = pd.date_range(START, _period_end(), freq="%ss" % RESOL_S, tz="utc")
    data.index = dur
    period = create_period(prosumer, RESOL_S, START, _period_end(), "utc", "default")
    data_source = DFData(data)

    cp_in = ["Tin_evap", "demand_1_kw", "tdmd_feed1_c", "tdmd_return1_c"]
    cp_out = ["t_evap_in_c", "qdemand_kw", "tdmd_feed_c", "tdmd_return_c"]
    hp_params = {"carnot_efficiency": 0.5, "pinch_c": 0, "delta_t_evap_c": 5, "max_p_comp_kw": 100}
    hd_params = {"t_feed_demand_c": 76.85, "t_return_demand_c": 30}

    cp = create_controlled_const_profile(prosumer, cp_in, cp_out, data_source, period, level=0, order=0)
    hp = create_controlled_heat_pump(prosumer, level=1, order=0, period=period, **hp_params)
    hd = create_controlled_heat_demand(prosumer, level=1, order=1, period=period, **hd_params)

    GenericMapping(container=prosumer, initiator_id=cp, initiator_column="t_evap_in_c",
                   responder_id=hp, responder_column="t_evap_in_c", order=0)
    GenericMapping(container=prosumer, initiator_id=cp,
                   initiator_column=["qdemand_kw", "tdmd_feed_c", "tdmd_return_c"],
                   responder_id=hd, responder_column=["q_demand_kw", "t_feed_demand_c", "t_return_demand_c"],
                   order=1)
    FluidMixMapping(container=prosumer, initiator_id=hp, responder_id=hd, order=0)
    return prosumer


def _pipes_network():
    net = pandapipes.create_empty_network(fluid="water", name="net_pipes")
    t_amb_k = 293
    pandapipes.set_user_pf_options(net, ambient_temperature=t_amb_k, mode="bidirectional")
    j0 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 1))
    j1 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(2, 1))
    j2 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(2, 0))
    j3 = pandapipes.create_junction(net, pn_bar=10, tfluid_k=350, geodata=(0, 0))
    pandapipes.create_pipes_from_parameters(net, from_junctions=[j0, j2], to_junctions=[j1, j3],
                                            length_km=0.1, diameter_m=0.05, u_w_per_m2k=10, text_k=t_amb_k)
    pandapipes.create_circ_pump_const_pressure(net, j3, j0, p_flow_bar=10, plift_bar=5, t_flow_k=350)
    pandapipes.create_heat_consumer(net, from_junction=j1, to_junction=j2, qext_w=100e3, controlled_mdot_kg_per_s=3)
    return net


def _energy_system_with_period(name):
    energy_system = create_empty_energy_system(name=name)
    create_period(energy_system, RESOL_S, START, _period_end(), timezone="utc", name="default")
    return energy_system


class TestProsumerOnlyEnergySystem:
    def test_prosumer_only_runs_and_produces_results(self):
        """An energy system with prosumers but no net runs each prosumer to completion."""
        prosumer = _self_contained_prosumer()
        energy_system = _energy_system_with_period("prosumer_only")
        add_pandaprosumer_to_energy_system(energy_system, prosumer, pandaprosumer_name=prosumer.name)

        run_time_series_system(energy_system, period_index=0, continue_on_divergence=False, verbose=False)

        hp_res = prosumer.time_series.loc[0].data_source.df
        assert not np.isnan(hp_res).to_numpy().any()
        # heat pump compressor power should have been computed for the non-zero demand steps
        assert (hp_res.p_comp_kw > 0).any()

    def test_prosumer_failure_still_raises(self):
        """A prosumer that never converges must still fail the run, not be masked as converged.

        The no-net convergence shortcut only makes the *network* flag vacuously True; prosumer
        controller convergence must still be enforced (ControllerNotConverged on max_iter).
        """
        prosumer = _self_contained_prosumer()
        energy_system = _energy_system_with_period("prosumer_fail")
        add_pandaprosumer_to_energy_system(energy_system, prosumer, pandaprosumer_name=prosumer.name)

        # Force one prosumer controller to never report convergence.
        failing_ctrl = prosumer.controller.object.iloc[-1]
        failing_ctrl.is_converged = lambda *args, **kwargs: False

        with pytest.raises(ControllerNotConverged):
            run_time_series_system(energy_system, period_index=0, continue_on_divergence=False, verbose=False)


class TestNetsOnlyEnergySystem:
    def test_nets_only_runs(self):
        """An energy system with a net but no prosumer runs the network time series to completion."""
        net = _pipes_network()
        energy_system = _energy_system_with_period("nets_only")
        add_net_to_energy_system(energy_system, net, net_name=net.name)

        run_time_series_system(energy_system, period_index=0, continue_on_divergence=False,
                               verbose=False, transient=True, dt=RESOL_S)

        # the net's result table for the last computed step should be populated
        assert len(net.res_junction) > 0
