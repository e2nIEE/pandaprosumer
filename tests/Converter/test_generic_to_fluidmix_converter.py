import numpy as np
import pytest
from pandaprosumer import *

def _default_argument():
    return {"cp_water": 4185.0}

def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")
def _default_responder():
    return (80, 60, 1.0)

class TestGenericToFluidMixController:
    """Tests for the GenericToFluidMixController"""


    def test_define_element(self):
        """
        Test the creation of a converter element in a prosumer container with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_converter(prosumer)
        assert hasattr(prosumer, "converter")
        assert len(prosumer.converter) == 1

        expected_columns = ["name", "cp_water", "in_service"]
        expected_values = [None, 4180.0, True]

        assert sorted(prosumer.converter.columns) == sorted(expected_columns)
        assert prosumer.converter.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        """
        Test the creation of a converter element in a prosumer container with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        converter_params = {"cp_water": 4200.0}

        converter_idx = create_converter(prosumer, name='foo', in_service=False, custom='test', index=4, **converter_params)
        assert hasattr(prosumer, "converter")
        assert len(prosumer.converter) == 1
        assert converter_idx == 4
        assert prosumer.converter.index[0] == converter_idx

        expected_columns = ['name', 'cp_water', 'in_service', 'custom']
        expected_values = ['foo', 4200.0, False, 'test']

        assert sorted(prosumer.converter.columns) == sorted(expected_columns)
        assert prosumer.converter.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """
        Test the creation of a converter controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_converter(prosumer,
                                       order=0,
                                       period=_default_period(prosumer),
                                       **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        """
        Check that the input and result columns of the converter controller are the one expected
        """
        prosumer = create_empty_prosumer_container()
        converter_controller_idx = create_controlled_converter(prosumer,
                                                            order=0,
                                                            period=_default_period(prosumer),
                                                            **_default_argument())
        converter_controller = prosumer.controller.iloc[converter_controller_idx].object

        input_columns_expected = ['t_supply_c', 'q_received_kw']
        result_columns_expected = []

        assert converter_controller.input_columns == input_columns_expected
        assert converter_controller.result_columns == result_columns_expected

        assert converter_controller.inputs == pytest.approx(np.full([converter_controller._nb_elements, len(converter_controller.input_columns)], np.nan), nan_ok=True)
        assert converter_controller.input_mass_flow_with_temp == {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                           FluidMixMapping.MASS_FLOW_KEY: np.nan}

    def test_controller_run_control_no_demand(self):
        """
        Test the control step of the controller with no demand
        """
        prosumer = create_empty_prosumer_container()
        converter_controller_idx = create_controlled_converter(prosumer,
                                                            order=0,
                                                            period=_default_period(prosumer),
                                                            **_default_argument())
        converter_controller = prosumer.controller.iloc[converter_controller_idx].object

        q_in_kw = 0
        t_supply_c = 5
        converter_controller.inputs = np.array([[t_supply_c, q_in_kw]])
        converter_controller.time_step(prosumer, "2020-01-01 00:00:00")
        converter_controller.control_step(prosumer)

        expected = []
        assert converter_controller.step_results == pytest.approx(np.array([expected]))
        assert converter_controller.result_mass_flow_with_temp == pytest.approx([{'mdot_kg_per_s': 0.0, 't_c': t_supply_c}])

    def test_controller_run_control_demand(self):
        """
        Test the control step of the controller with demand
        """
        prosumer = create_empty_prosumer_container()
        converter_controller_idx = create_controlled_converter(prosumer,
                                                            order=0,
                                                            period=_default_period(prosumer),
                                                            **_default_argument())
        converter_controller = prosumer.controller.iloc[converter_controller_idx].object

        q_in_kw = 1000
        t_supply_c = 80
        t_required_out_c, t_required_in_c, mdot_required_tab_kg_per_s = _default_responder()
        converter_controller.t_m_to_deliver = lambda prosumer: _default_responder()
        converter_controller.inputs = np.array([[t_supply_c, q_in_kw]])
        converter_controller.time_step(prosumer, "2020-01-01 00:00:00")
        converter_controller.control_step(prosumer)

        t_mean_K = CELSIUS_TO_K + 0.5 * (t_supply_c + t_required_in_c)
        cp = converter_controller.fluid.get_heat_capacity(t_mean_K)

        mdot_received = q_in_kw * 1e3 / (cp * (t_supply_c - t_required_in_c))
        expected = []
        assert converter_controller.step_results == pytest.approx(np.array([expected]))
        assert converter_controller.result_mass_flow_with_temp == pytest.approx([{'mdot_kg_per_s': mdot_received, 't_c': t_supply_c}])