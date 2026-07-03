"""
Tests for the clearer error/warning messages raised when controllers are
ill-connected (a mapping points to a non-existent controller, a controller is
left unconnected, or a FluidMix initiator produced no output for a mapping).
"""

import warnings

import pandas as pd
import pytest
from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer import (create_controlled_const_profile, create_controlled_heat_exchanger,
                           create_controlled_heat_demand)
from pandaprosumer.mapping import FluidMixMapping, GenericMapping
from pandaprosumer.run_time_series import run_timeseries
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.check_connections import check_controller_connections, OrphanedControllerWarning


def _build_prosumer(data, add_fluidmix=True, fluidmix_responder=None):
    """Build a ConstProfile -> HeatExchanger -> HeatDemand prosumer.

    :param add_fluidmix: whether to add the HX -> HD FluidMix mapping
    :param fluidmix_responder: override the FluidMix responder id (to create a
        dangling mapping)
    """
    prosumer = create_empty_prosumer_container()

    start = '2020-01-01 00:00:00'
    resol = 3600
    end = pd.Timestamp(start) + len(data["Tin_1"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
    dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
    period = create_period(prosumer, resol, start, end, 'utc', 'default')

    data.index = dur
    data_source = DFData(data)

    hx_params = {'t_1_in_nom_c': 72, 't_1_out_nom_c': 47, 't_2_in_nom_c': 32,
                 't_2_out_nom_c': 63, 'mdot_2_nom_kg_per_s': 2}

    cp_idx = create_controlled_const_profile(prosumer, ["Tin_1", "demand_1"],
                                             ["t_1_in_c", "qdemand_kw"], data_source, period, 0, 0)
    hx_idx = create_controlled_heat_exchanger(prosumer, level=1, order=0, period=period, **hx_params)
    hd_idx = create_controlled_heat_demand(prosumer, level=1, order=1,
                                           t_feed_demand_c=76.85, t_return_demand_c=30, period=period)

    GenericMapping(container=prosumer, initiator_id=cp_idx, initiator_column="qdemand_kw",
                   responder_id=hd_idx, responder_column="q_demand_kw", order=0)
    GenericMapping(container=prosumer, initiator_id=cp_idx, initiator_column="t_1_in_c",
                   responder_id=hx_idx, responder_column="t_feed_in_c", order=0)
    if add_fluidmix:
        FluidMixMapping(container=prosumer, initiator_id=hx_idx,
                        responder_id=hd_idx if fluidmix_responder is None else fluidmix_responder,
                        order=0)
    return prosumer, period, cp_idx, hx_idx, hd_idx


def _data():
    return pd.DataFrame({"Tin_1": [80, 95], "demand_1": [50, 200]})


class TestDanglingMapping:
    def test_mapping_to_nonexistent_responder_raises_clear_error(self):
        prosumer, period, *_ = _build_prosumer(_data(), add_fluidmix=True, fluidmix_responder=99)
        with pytest.raises(ValueError) as exc:
            check_controller_connections(prosumer)
        msg = str(exc.value)
        assert "Invalid controller mapping" in msg
        assert "responder controller #99 does not exist" in msg
        assert prosumer.name in msg or "<unnamed>" in msg

    def test_dangling_mapping_caught_at_run(self):
        prosumer, period, *_ = _build_prosumer(_data(), add_fluidmix=True, fluidmix_responder=99)
        with pytest.raises(ValueError, match="responder controller #99 does not exist"):
            run_timeseries(prosumer, period, verbose=False)

    def test_valid_prosumer_passes_check(self):
        prosumer, period, *_ = _build_prosumer(_data(), add_fluidmix=True)
        # Should not raise, and should not warn about orphans
        with warnings.catch_warnings():
            warnings.simplefilter("error", OrphanedControllerWarning)
            check_controller_connections(prosumer)


class TestOrphanedController:
    def test_explicit_orphan_warns_clearly(self):
        prosumer, period, cp_idx, hx_idx, hd_idx = _build_prosumer(_data(), add_fluidmix=True)
        # Drop all mappings referencing the heat demand to orphan it.
        mask = (prosumer.mapping["initiator"] != hd_idx) & (prosumer.mapping["responder"] != hd_idx)
        prosumer.mapping = prosumer.mapping[mask]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check_controller_connections(prosumer)
        orphan_warnings = [w for w in caught if issubclass(w.category, OrphanedControllerWarning)]
        assert len(orphan_warnings) == 1
        assert "not connected to any other controller" in str(orphan_warnings[0].message)


class TestFluidMixOrderError:
    def test_fluidmix_no_output_raises_clear_error(self):
        prosumer, period, cp_idx, hx_idx, hd_idx = _build_prosumer(_data(), add_fluidmix=True)
        mapping_obj = prosumer.mapping[
            prosumer.mapping["object"].apply(lambda o: o.name == "FluidMixMapping")].iloc[0]["object"]
        initiator = prosumer.controller.loc[hx_idx, "object"]
        responder = prosumer.controller.loc[hd_idx, "object"]
        # Initiator produced no fluid output (empty list) -> clear error
        initiator.result_mass_flow_with_temp = []
        with pytest.raises(ValueError, match="did not produce a fluid output for mapping order 0"):
            mapping_obj.map(initiator, responder)
