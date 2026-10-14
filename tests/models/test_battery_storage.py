import numpy as np
import pandas as pd
import pytest

from pandaprosumer.controller import BatteryStorageController
from pandaprosumer.controller.data_model import BatteryStorageControllerData
from pandaprosumer.create import create_battery_storage, create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import create_controlled_battery_storage, create_controlled_const_profile
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import DFData, run_timeseries


def _prosumer(hours=4):
    prosumer = create_empty_prosumer_container()
    period = create_period(prosumer, 3600, start="2020-01-01 00:00:00", end=f"2020-01-01 {hours - 1:02d}:59:59",
                           timezone="utc", name="foo")
    return prosumer, period


def _battery(prosumer, period, **kwargs):
    params = dict(e_capacity_kwh=100.0, p_charge_max_kw=50.0, p_discharge_max_kw=50.0, eta_charge=1.0,
                  eta_discharge=1.0, soc_min=0.1, soc_max=0.9, init_soc=0.5)
    params.update(kwargs)
    return create_controlled_battery_storage(prosumer, period=period, **params)


def _step(prosumer, index, request_kw, time="2020-01-01 00:00:00"):
    controller = prosumer.controller.object.at[index]
    controller.time_step(prosumer, pd.Timestamp(time, tz="utc"))
    controller.inputs = np.array([[request_kw]])
    controller.control_step(prosumer)
    return dict(zip(controller.result_columns, controller.step_results[0], strict=True))


class TestBatteryStorage:
    def test_define_element(self):
        prosumer, _ = _prosumer()
        index = create_battery_storage(prosumer, e_capacity_kwh=200.0, p_charge_max_kw=100.0, p_discharge_max_kw=80.0)
        assert index == 0
        row = prosumer.battery_storage.iloc[0]
        assert row.e_capacity_kwh == 200.0 and row.p_discharge_max_kw == 80.0
        assert row.soc_min == pytest.approx(0.1) and row.soc_max == pytest.approx(0.9)

    def test_controller_columns(self):
        data = BatteryStorageControllerData(element_index=[0])
        assert data.input_columns == ["p_requested_kw"]
        assert "soc" in data.result_columns and "p_storage_kw" in data.result_columns

    def test_each_result_lands_in_its_own_column(self):
        """Regression: e_stored_kwh and p_request_unmet_kw used to be written swapped."""
        prosumer, period = _prosumer()
        index = _battery(prosumer, period)
        result = _step(prosumer, index, 80.0)  # 80 kW asked, 40 kWh above soc_min → 40 kW delivered
        assert result["p_storage_kw"] == pytest.approx(40.0)
        assert result["p_request_unmet_kw"] == pytest.approx(40.0)
        assert result["e_stored_kwh"] == pytest.approx(10.0)
        assert result["soc"] == pytest.approx(0.1)

    def test_charge_is_negative_and_limited_by_power(self):
        prosumer, period = _prosumer()
        index = _battery(prosumer, period, p_charge_max_kw=30.0)
        result = _step(prosumer, index, -100.0)
        assert result["p_storage_kw"] == pytest.approx(-30.0)
        assert result["p_charge_kw"] == pytest.approx(30.0)
        assert result["soc"] == pytest.approx(0.8)

    def test_efficiency_losses(self):
        prosumer, period = _prosumer()
        index = _battery(prosumer, period, eta_charge=0.9, eta_discharge=0.9)
        result = _step(prosumer, index, -10.0)
        assert result["e_stored_kwh"] == pytest.approx(50.0 + 9.0)

    def test_repeated_control_step_in_one_timestep_does_not_drift(self):
        """A prosumer coupled to a network may run a controller twice in one step: the SOC must not move twice."""
        prosumer, period = _prosumer()
        index = _battery(prosumer, period)
        controller = prosumer.controller.object.at[index]
        controller.time_step(prosumer, pd.Timestamp("2020-01-01 00:00:00", tz="utc"))
        controller.inputs = np.array([[10.0]])
        controller.control_step(prosumer)
        controller.applied = False
        controller.control_step(prosumer)
        result = dict(zip(controller.result_columns, controller.step_results[0], strict=True))
        assert result["e_stored_kwh"] == pytest.approx(40.0)

    def test_time_series_run_with_mapped_requests(self):
        prosumer, period = _prosumer(hours=4)
        requests = [-20.0, -20.0, 30.0, 30.0]
        frame = pd.DataFrame({"p_req": requests}, index=pd.date_range("2020-01-01", periods=4, freq="h", tz="utc"))
        profile = create_controlled_const_profile(prosumer, ["p_req"], ["p_req"], DFData(frame), period)
        index = _battery(prosumer, period, init_soc=0.5, order=1)
        GenericMapping(prosumer, initiator_id=profile, initiator_column="p_req", responder_id=index,
                       responder_column="p_requested_kw")
        run_timeseries(prosumer, period, verbose=False)
        controller = prosumer.controller.object.at[index]
        results = pd.DataFrame(controller.res[0], columns=controller.result_columns)
        assert list(results["p_storage_kw"]) == pytest.approx([-20.0, -20.0, 30.0, 30.0])
        assert list(results["e_stored_kwh"]) == pytest.approx([70.0, 90.0, 60.0, 30.0])
