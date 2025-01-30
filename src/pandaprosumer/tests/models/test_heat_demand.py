import pytest

from pandaprosumer2.create import create_empty_prosumer_container, create_period, create_heat_demand
from pandaprosumer2.controller import HeatDemandController, HeatDemandControllerData
from ..create_elements_controllers import *


def _create_heat_demand_controller(prosumer, **kwargs):
    period = create_period(prosumer, 1,
                           name="foo",
                           start="2020-01-01 00:00:00",
                           end="2020-01-01 11:59:59",
                           timezone="utc")
    heat_demand_index = init_hd_element(prosumer, **kwargs)
    init_hd_controller(prosumer, period, [heat_demand_index])
    hd_controller = prosumer.controller.iloc[0].object
    return hd_controller


class TestHeatDemand:
    """
    Tests the functionalities of a Heat Pump element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a heat demand element in a prosumer container with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_heat_demand(prosumer)
        assert hasattr(prosumer, "heat_demand")
        assert len(prosumer.heat_demand) == 1

        expected_columns = ["name", "scaling", "t_in_set_c", "t_out_set_c", "in_service"]
        expected_values = [None, 1., np.nan, np.nan, True]

        assert sorted(prosumer.heat_demand.columns) == sorted(expected_columns)
        assert prosumer.heat_demand.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        """
        Test the creation of a heat demand element in a prosumer container with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        hd_params = {"scaling": 3.2,
                     "t_in_set_c": 63,
                     "t_out_set_c": 35}

        hd_idx = init_hd_element(prosumer, name='foo', in_service=False, index=4, custom='test', **hd_params)
        assert hasattr(prosumer, "heat_demand")
        assert len(prosumer.heat_demand) == 1
        assert hd_idx == 4
        assert prosumer.heat_demand.index[0] == hd_idx

        expected_columns = ["name", "scaling", "t_in_set_c", "t_out_set_c", "in_service", "custom"]
        expected_values = ['foo', 3.2, 63, 35, False, 'test']

        assert sorted(prosumer.heat_demand.columns) == sorted(expected_columns)
        assert prosumer.heat_demand.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """
        Test the creation of a heat demand controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        _create_heat_demand_controller(prosumer)

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        """
        Check that the input and result columns of the heat demand controller are the one expected
        """
        prosumer = create_empty_prosumer_container()
        hd_controller = _create_heat_demand_controller(prosumer)

        input_columns_expected = ["q_demand_kw", "mdot_demand_kg_per_s", "t_feed_demand_c", "t_return_demand_c"]
        result_columns_expected = ["q_received_kw", "q_uncovered_kw", "mdot_kg_per_s", "t_in_c", "t_out_c"]

        assert hd_controller.input_columns == input_columns_expected
        assert hd_controller.result_columns == result_columns_expected

    def test_required_temp_and_mdot(self):
        """
        Test the _demand_q_tf_tr_m method of the heat demand controller
        Check that for different inputs of required demand power, mass flow and temperature,
          the method returns the expected values
        """
        params = {"scaling": 1,
                  "t_in_set_c": 76.85,
                  "t_out_set_c": 30}
        prosumer = create_empty_prosumer_container()
        hd_controller = _create_heat_demand_controller(prosumer, **params)

        with pytest.raises(ValueError):
            assert hd_controller.t_m_to_receive(prosumer)

        hd_controller.inputs = np.array([[100, np.nan, np.nan, np.nan]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((76.85, 30., 0.5102989))

        hd_controller.inputs = np.array([[np.nan, 0.8, np.nan, np.nan]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((76.85, 30., 0.8))

        with pytest.raises(ValueError):
            hd_controller.inputs = np.array([[np.nan, np.nan, 80, np.nan]])
            hd_controller.t_m_to_receive(prosumer)

        with pytest.raises(ValueError):
            hd_controller.inputs = np.array([[np.nan, np.nan, np.nan, 35]])
            hd_controller.t_m_to_receive(prosumer)

        hd_controller.inputs = np.array([[np.nan, 0.8, 80, 35]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((80, 35., 0.8))

        hd_controller.inputs = np.array([[100, np.nan, 80, 35]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((80, 35., 0.53109161))

        hd_controller.inputs = np.array([[100, 0.8, np.nan, 35]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((64.905433, 35., 0.8))

        hd_controller.inputs = np.array([[100, 0.8, 80, np.nan]])
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((80, 50.217, .8))

        with pytest.raises(ValueError):
            hd_controller.inputs = np.array([[100, 0.8, 80, 35]])
            hd_controller.t_m_to_receive(prosumer)

    def test_controller_run_control(self):
        """
        Test the control step of the heat demand controller with different inputs
        """
        params = {'t_in_set_c': 76.85,
                  't_out_set_c': 30}
        prosumer = create_empty_prosumer_container()
        hd_controller = _create_heat_demand_controller(prosumer, **params)

        # Provide the exact amount of energy required
        # For the default value of t_out_set_c (30°C),
        # For a heat demand of 104.58385 kW at 80°C and 0.5 kg/s
        # Q = m * cp * dT = 0.5 * 4.186 * (80-30) = 104.6 kW
        # FixMe: Not exactly the good value, because of the cp value dependant on the temperature
        hd_controller.inputs = np.array([[104.58385, .5, 80, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = .5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [104.243, .34, .5,  80., 30.1628]  # no uncovered demand
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01, 1)

        # Required more energy than supplied
        hd_controller.inputs = np.array([[200, np.nan, 80, np.nan]])  # Requiring 200 kW
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = .5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [104.58385, 95.4, .5, 80., 30.]  # uncovered demand
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01)

        # Provide more that the amount of energy required (uncovered demand < 0)
        hd_controller.inputs = np.array([[0, np.nan, 80, np.nan]])  # Requiring 0 kW
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = .5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [104.58385, -104.58385, .5, 80., 30.]  # Extra supplied energy
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01)

        # Provide too low feed temperature
        hd_controller.inputs = np.array([[104.6, np.nan, 80, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 40
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = .5
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [20.8992125, 83.7, .5, 40., 30.]  # Power supplied: .5*4.186*(40-30) = 20.9, thus 83.7 uncovered
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01)

    def test_controller_t_m_to_receive(self):
        """
        For a fixed heat demand, test the t_m_to_receive method
        The demand power, mass flow and temperatures are fixed
        Put different values for the fluid input mass flow and temperature (as is actually provided by first
        merit order upstream controllers) and check that the method returns the expected values for the 
        feed temperature, return temperature and mass flow that are still to be provided (as to be provided 
        by remaining later merit order initiators)
        """
        prosumer = create_empty_prosumer_container()
        hd_controller = _create_heat_demand_controller(prosumer)

        q_demand_kw = 104.58385
        mdot_demand_kg_per_s = .5
        t_feed_demand_c = 80
        cp_kj_per_kgk = prosumer.fluid.get_heat_capacity(273.15+t_feed_demand_c) / 1000
        t_return_demand_c = t_feed_demand_c - q_demand_kw / (mdot_demand_kg_per_s * cp_kj_per_kgk)

        hd_controller.inputs = np.array([[q_demand_kw, mdot_demand_kg_per_s, t_feed_demand_c, np.nan]])

        assert hd_controller._demand_q_tf_tr_m(prosumer) == pytest.approx((q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s), .001)
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s), .001)

        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c, t_return_demand_c, 0.), .001)

        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s / 3
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s * 2/3), .001)

        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c / 2
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s / 2
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c * 1.5, t_return_demand_c, mdot_demand_kg_per_s / 2), .001)

        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c / 2
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s + 1
        assert hd_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c, t_return_demand_c, 0.), .001)

    def test_controller_run_control_air(self):
        """
        Test the control step of the heat demand controller with different inputs
        """
        params = {'t_in_set_c': 76.85,
                  't_out_set_c': 30}
        prosumer = create_empty_prosumer_container()
        hd_controller = _create_heat_demand_controller(prosumer, **params)

        # Provide the exact amount of energy required
        # For the default value of t_out_set_c (30°C),
        # For a heat demand of 104.58385 kW at 80°C and 0.5 kg/s
        # Q = m * cp * dT = 0.5 * 4.186 * (80-30) = 104.6 kW
        hd_controller.inputs = np.array([[104.58385, .5, 80, np.nan]])
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        hd_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = np.nan
        hd_controller.time_step(prosumer, "2020-01-01 00:00:00")
        hd_controller.control_step(prosumer)
        expected = [104.58385, 0., .50163058, 80., 30.16287]  # no uncovered demand
        assert hd_controller.step_results == pytest.approx(np.array([expected]), 0.01, 1)
