import pytest

from ..create_elements_controllers import *


def _create_stratified_heat_storage_controller(prosumer, resol=1, **kwargs):
    period = create_period(prosumer, resol,
                           name="foo",
                           start="2020-01-01 00:00:00",
                           end="2020-01-01 00:00:09",
                           timezone="utc")

    shs_index = init_shs_element(prosumer, **kwargs)
    init_shs_controller(prosumer, period, [shs_index])
    shs_controller = prosumer.controller.iloc[0].object
    return shs_controller


class TestStratifiedHeatStorage:
    """
    Tests the functionalities of a SHS element and controller
    """

    def test_define_element(self):
        """
        Test the creation of a stratified heat storage element in a prosumer container with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        shs_params = {"tank_height_m": 12.,
                      "tank_internal_radius_m": 4.}

        init_shs_element(prosumer, **shs_params)
        assert hasattr(prosumer, "stratified_heat_storage")
        assert len(prosumer.stratified_heat_storage) == 1

        expected_columns = ['name', 'tank_height_m', 'tank_internal_radius_m', 'tank_external_radius_m',
                            'insulation_thickness_m', 'n_layers', 'min_useful_temp_c', 'k_fluid_w_per_mk',
                            'k_insu_w_per_mk', 'k_wall_w_per_mk', 'h_ext_w_per_m2k', 't_ext_c', 'height_charge_in_m',
                            'height_charge_out_m', 'height_discharge_out_m', 'height_discharge_in_m', 'in_service']
        expected_values = [None, 12., 4., 4.1, .15, 100, 65., .598, .028, 45., 12.5, 22.5, np.nan, 0, np.nan, 0, True]

        assert sorted(prosumer.stratified_heat_storage.columns) == sorted(expected_columns)
        assert prosumer.stratified_heat_storage.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        """
        Test the creation of a stratified heat storage element in a prosumer container with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        shs_params = {"tank_height_m": 12.,
                      "tank_internal_radius_m": 4.,
                      "tank_external_radius_m": 5.,
                      "insulation_thickness_m": .15,
                      "n_layers": 100,
                      "min_useful_temp_c": 22.5,
                      "k_fluid_w_per_mk": 0.598,
                      "k_insu_w_per_mk": .028,
                      "k_wall_w_per_mk": 45,
                      "h_ext_w_per_m2k": 12.5,
                      "t_ext_c": 22.5,
                      "height_charge_in_m": 10,
                      "height_charge_out_m": 2,
                      "height_discharge_out_m": 11,
                      "height_discharge_in_m": 1}

        shs_idx = init_shs_element(prosumer, name='foo', in_service=False, custom='test', index=4, **shs_params)
        assert hasattr(prosumer, "stratified_heat_storage")
        assert len(prosumer.stratified_heat_storage) == 1
        assert shs_idx == 4
        assert prosumer.stratified_heat_storage.index[0] == shs_idx

        expected_columns = ['name', 'h_ext_w_per_m2k', 'insulation_thickness_m',
                            'k_fluid_w_per_mk', 'k_insu_w_per_mk', 'k_wall_w_per_mk', 'min_useful_temp_c',
                            'n_layers', 'tank_height_m', 'tank_internal_radius_m', 'tank_external_radius_m', 't_ext_c',
                            'height_charge_in_m', 'height_charge_out_m', 'height_discharge_out_m',
                            'height_discharge_in_m', 'in_service', 'custom']
        expected_values = ['foo', 12., 4., 5., .15, 100, 22.5, .598, .028, 45., 12.5, 22.5, 10, 2, 11, 1, False, 'test']

        assert sorted(prosumer.stratified_heat_storage.columns) == sorted(expected_columns)
        assert prosumer.stratified_heat_storage.iloc[0].values == pytest.approx(expected_values)

    def test_define_element_param_fail(self):
        """
        Test the creation of an element in a prosumer container with invalid parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        shs_params = {"tank_height_m": 12.,
                      "tank_internal_radius_m": 4.,
                      "tank_external_radius_m": 3.,
                      "insulation_thickness_m": .15,
                      "n_layers": 100,
                      "min_useful_temp_c": 22.5,
                      "k_fluid_w_per_mk": 0.598,
                      "k_insu_w_per_mk": .028,
                      "k_wall_w_per_mk": 45,
                      "h_ext_w_per_m2k": 12.5,
                      "t_ext_c": 22.5}

        with pytest.raises(ValueError):
            # tank_external_radius_m < tank_internal_radius_m
            init_shs_element(prosumer, name='foo', **shs_params)

        shs_params = {"tank_height_m": 12.,
                      "tank_internal_radius_m": 4.,
                      "insulation_thickness_m": .15,
                      "n_layers": 100,
                      "min_useful_temp_c": 22.5,
                      "k_fluid_w_per_mk": 0.598,
                      "k_insu_w_per_mk": .028,
                      "k_wall_w_per_mk": 45,
                      "h_ext_w_per_m2k": 12.5,
                      "t_ext_c": 22.5,
                      "height_charge_in_m": 5,
                      "height_charge_out_m": 6,
                      "height_discharge_out_m": 11,
                      "height_discharge_in_m": 1}

        with pytest.raises(ValueError):
            # height_charge_in_m < height_charge_out_m
            init_shs_element(prosumer, name='foo', **shs_params)

        shs_params = {"tank_height_m": 12.,
                      "tank_internal_radius_m": 4.,
                      "insulation_thickness_m": .15,
                      "n_layers": 100,
                      "min_useful_temp_c": 22.5,
                      "k_fluid_w_per_mk": 0.598,
                      "k_insu_w_per_mk": .028,
                      "k_wall_w_per_mk": 45,
                      "h_ext_w_per_m2k": 12.5,
                      "t_ext_c": 22.5,
                      "height_charge_in_m": 10,
                      "height_charge_out_m": 2,
                      "height_discharge_out_m": 4,
                      "height_discharge_in_m": 11}

        with pytest.raises(ValueError):
            # height_discharge_out_m < height_discharge_in_m
            init_shs_element(prosumer, name='foo', **shs_params)

        shs_params = {"tank_height_m": 12.,
                      "tank_internal_radius_m": 4.,
                      "insulation_thickness_m": .15,
                      "n_layers": 100,
                      "min_useful_temp_c": 22.5,
                      "k_fluid_w_per_mk": 0.598,
                      "k_insu_w_per_mk": .028,
                      "k_wall_w_per_mk": 45,
                      "h_ext_w_per_m2k": 12.5,
                      "t_ext_c": 22.5,
                      "height_charge_in_m": 15,
                      "height_charge_out_m": 2,
                      "height_discharge_out_m": 13,
                      "height_discharge_in_m": 1}

        with pytest.raises(ValueError):
            # height_charge_in_m > tank_height_m and height_discharge_out_m > tank_height_m
            init_shs_element(prosumer, name='foo', **shs_params)

    def test_define_controller(self):
        """
        Test the creation of a stratified heat storage controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        _create_stratified_heat_storage_controller(prosumer)

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        """
        Check that the input and result columns of the stratified heat storage controller are the one expected
        """
        prosumer = create_empty_prosumer_container()
        shs_controller = _create_stratified_heat_storage_controller(prosumer)

        input_columns_expected = []
        result_columns_expected = ['q_received_kw', 'q_delivered_kw', 'q_charge_kw', 'q_discharge_kw', 'e_stored_kwh',
                                   'mdot_received_kg_per_s', 't_received_in_c', 't_received_out_c',
                                   'mdot_delivered_kg_per_s', 't_demand_in_c', 't_delivered_out_c',
                                   'mdot_charge_kg_per_s', 't_charge_out_c',
                                   'mdot_discharge_kg_per_s', 't_discharge_out_c']

        assert shs_controller.input_columns == input_columns_expected
        assert shs_controller.result_columns == result_columns_expected

    def test_controller_run_control(self):
        """
        Test the control step of the controller with no demand
        """
        prosumer = create_empty_prosumer_container()
        shs_controller = _create_stratified_heat_storage_controller(prosumer)

        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 150
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 1.5
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        expected = [803.685285, 0., 803.685285, 0., 0., 1.5, 150., 22.5, 0., 0., 22.5, 1.5, 22.5, 0., 22.5]
        assert shs_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_out(self):
        """
        Test the control step of the controller with a demand
        """
        prosumer = create_empty_prosumer_container()
        resol = 3600
        # Create a SHS with no heat losses to the environment
        shs_controller = _create_stratified_heat_storage_controller(prosumer,
                                                                    resol=resol,
                                                                    h_ext_w_per_m2k=0,
                                                                    min_useful_temp_c=22.5)

        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 80
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 1.5
        shs_controller.t_m_to_deliver = lambda x: (0, 0, [0])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        # Check that the energy stored in the storage is equal to the input energy
        e_in_kwh = (80-22.5)*1.5*4.186*resol/3600
        expected = [360.697845, 0., 360.697845, 0., e_in_kwh, 1.5, 80., 22.5, 0., 0., 22.5, 1.5, 22.5, 0., 22.5]
        assert shs_controller.step_results == pytest.approx(np.array([expected]), .03)
        assert shs_controller._get_stored_energy_kwh(22.5) == pytest.approx(e_in_kwh, .03)

    def test_controller_run_control_2_layers(self):
        """
        Test of a minimalist SHS with only two layers, each of volume 1m^3
        no heat losses to the environment, and no heat diffusion
        """
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 1,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 00:00:09",
                               timezone="utc")

        shs_params = {"tank_height_m": 2.,
                      "tank_internal_radius_m": .564,
                      "tank_external_radius_m": .664,
                      "insulation_thickness_m": .1,
                      "n_layers": 2,
                      "min_useful_temp_c": 20,
                      "k_fluid_w_per_mk": 0,
                      "k_insu_w_per_mk": 0,
                      "k_wall_w_per_mk": 0,
                      "h_ext_w_per_m2k": 0,
                      "t_ext_c": 20}

        t_layers_init_c = [20., 30.]

        shs_index = init_shs_element(prosumer, **shs_params)
        init_shs_controller(prosumer, period, [shs_index], init_layer_temps_c=t_layers_init_c)
        shs_controller = prosumer.controller.iloc[0].object

        assert shs_controller._layer_temps_c == pytest.approx(np.array(t_layers_init_c))

        layer_volume_m3 = shs_controller.A_m2 * shs_controller.dz_m
        layer_mass_kg = prosumer.fluid.get_density(273.15+25) * layer_volume_m3  # Each layer is about 1m^3

        # Test with no charge nor discharge
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 0
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0
        shs_controller.t_m_to_deliver = lambda x: (0, 0, [0])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        res_expected = [0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 30., 0., 20., 0., 30.]
        layers_expected = t_layers_init_c
        assert shs_controller.step_results == pytest.approx(np.array([res_expected]))
        assert shs_controller._layer_temps_c == pytest.approx(np.array(layers_expected))

        # Test with filling 1m^3 (the volume of one layer) at 30°C in one time step
        shs_controller._layer_temps_c = t_layers_init_c
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 30
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = layer_mass_kg
        shs_controller.t_m_to_deliver = lambda x: (0, 0, [0])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        res_expected = [41662.4243, 0., 41662.4243, 0., (30-20)*layer_mass_kg*4.186*1/3600, layer_mass_kg, 30., 20., 0., 0., 30., layer_mass_kg, 20., 0., 30.]
        layers_expected = [30., 30.]
        assert shs_controller.step_results == pytest.approx(np.array([res_expected]), .01)
        assert shs_controller._layer_temps_c == pytest.approx(np.array(layers_expected), .01)

        # Test with filling 1m^3 (the volume of one layer) at 30°C in 1000 time steps
        # NB: A shorter time step here give worse results !
        shs_controller._layer_temps_c = t_layers_init_c
        for counter in range(1000):
            shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 30
            shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = layer_mass_kg / 1000
            shs_controller.t_m_to_deliver = lambda x: (0, 0, [0])
            shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
            shs_controller.control_step(prosumer)

        res_expected = [15.32302511, 0., 15.32302511, 0., 7.3157, .99633807, 30., 26.32126533, 0., 0., 30., .99633807, 26.32126533, 0., 30.]
        layers_expected = [26.3244, 30.]
        assert shs_controller.step_results == pytest.approx(np.array([res_expected]), .01)
        assert shs_controller._layer_temps_c == pytest.approx(np.array(layers_expected), .01)

        # Test charging then discharging the same amount of energy
        shs_controller._layer_temps_c = t_layers_init_c
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 30
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = layer_mass_kg
        shs_controller.t_m_to_deliver = lambda x: (0, 0, [0])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 0
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0
        shs_controller.t_m_to_deliver = lambda x: (30, 20, [layer_mass_kg])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        res_expected = [0., (30-20)*layer_mass_kg*4186 / 1e3, 0., (30-20)*layer_mass_kg*4186 / 1e3, 0., 0., 0., 0., layer_mass_kg, 20., 30., 0., 30., layer_mass_kg, 30.]
        layers_expected = [20., 30.]
        assert shs_controller.step_results == pytest.approx(np.array([res_expected]), .01, 0.1)
        assert shs_controller._layer_temps_c == pytest.approx(np.array(layers_expected), .01)

        # Test charging when already full
        shs_controller._layer_temps_c = [30, 30]
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 30
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = layer_mass_kg
        shs_controller.t_m_to_deliver = lambda x: (0, 0, [0])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        res_expected = [0., 0.,  0.,  0., (30-20)*layer_mass_kg*4.186*1/3600, layer_mass_kg, 30., 30.,  0., 0., 30., layer_mass_kg, 30., 0., 30]
        layers_expected = [30., 30.]
        assert shs_controller.step_results == pytest.approx(np.array([res_expected]), .01, 0.01)
        assert shs_controller._layer_temps_c == pytest.approx(np.array(layers_expected), .01)

        # Test charging when empty
        shs_controller._layer_temps_c = [20, 20]
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 30
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = layer_mass_kg
        shs_controller.t_m_to_deliver = lambda x: (0, 0, [0])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        res_expected = [41662.4242, 0.,  41662.4242,  0., -1.15565777, layer_mass_kg, 30., 20.,  0., 0., 20., layer_mass_kg, 20., 0., 20.]
        layers_expected = [20., 29.]
        assert shs_controller.step_results == pytest.approx(np.array([res_expected]), .01, 0.01)
        assert shs_controller._layer_temps_c == pytest.approx(np.array(layers_expected), .01)

        # Test discharging when full
        shs_controller._layer_temps_c = [30, 30]
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 0
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0
        shs_controller.t_m_to_deliver = lambda x: (30, 20, [layer_mass_kg])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        res_expected = [0., (30-20)*layer_mass_kg*4186 / 1e3, 0., (30-20)*layer_mass_kg*4186 / 1e3, 0., 0., 0., 0., layer_mass_kg, 20., 30., 0., 30., layer_mass_kg, 30.]
        layers_expected = [19., 30.]
        assert shs_controller.step_results == pytest.approx(np.array([res_expected]), .01, 0.01)
        assert shs_controller._layer_temps_c == pytest.approx(np.array(layers_expected), .01)

        # Test discharging when already empty
        shs_controller._layer_temps_c = [20, 20]
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = 0
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = 0
        shs_controller.t_m_to_deliver = lambda x: (30, 20, [layer_mass_kg])
        shs_controller.time_step(prosumer, "2020-01-01 00:00:00")
        shs_controller.control_step(prosumer)

        res_expected = [0., 0., 0., 0., -(30-20)*layer_mass_kg*4.186*1/3600, 0., 0., 0., 0., 20., 20., 0., 20., 0., 20.]
        layers_expected = [20., 20.]
        assert shs_controller.step_results == pytest.approx(np.array([res_expected]), .01, 0.01)
        assert shs_controller._layer_temps_c == pytest.approx(np.array(layers_expected), .01)

    def test_controller_t_m_to_receive(self):
        prosumer = create_empty_prosumer_container()
        period = create_period(prosumer, 1,
                               name="foo",
                               start="2020-01-01 00:00:00",
                               end="2020-01-01 00:00:09",
                               timezone="utc")

        shs_params = {"tank_height_m": 2.,
                      "tank_internal_radius_m": .564,
                      "tank_external_radius_m": .664,
                      "insulation_thickness_m": .1,
                      "n_layers": 2,
                      "min_useful_temp_c": 80,
                      "k_fluid_w_per_mk": 0,
                      "k_insu_w_per_mk": 0,
                      "k_wall_w_per_mk": 0,
                      "h_ext_w_per_m2k": 0,
                      "t_ext_c": 20}

        t_layers_init_c = [40., 80.]

        shs_index = init_shs_element(prosumer, **shs_params)
        init_shs_controller(prosumer, period, [shs_index], init_layer_temps_c=t_layers_init_c)
        shs_controller = prosumer.controller.iloc[0].object

        min_useful_temp_c = shs_params['min_useful_temp_c']
        t_low_c = t_layers_init_c[0]
        t_high_c = t_layers_init_c[-1]

        # Each layer is about 1m^3
        layer_volume_m3 = shs_controller.A_m2 * shs_controller.dz_m
        layer_mass_kg = prosumer.fluid.get_density(273.15+np.mean(t_layers_init_c)) * layer_volume_m3
        t_feed_demand_c = 80
        t_return_demand_c = 40
        mdot_demand_kg_per_s = 100

        assert shs_controller.t_m_to_receive(prosumer) == pytest.approx((min_useful_temp_c, t_low_c, layer_mass_kg), .001)

        shs_controller.t_m_to_deliver = lambda x: (t_feed_demand_c, t_return_demand_c, [mdot_demand_kg_per_s])

        assert shs_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c, t_low_c, layer_mass_kg + mdot_demand_kg_per_s), .001)

        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s
        assert shs_controller.t_m_to_receive(prosumer) == pytest.approx((t_feed_demand_c, t_return_demand_c, layer_mass_kg), .001)

        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s / 3
        assert shs_controller.t_m_to_receive(prosumer) == pytest.approx(
            (t_feed_demand_c, t_return_demand_c, layer_mass_kg + mdot_demand_kg_per_s * 2 / 3), .001)

        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c / 2
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s / 2
        assert shs_controller.t_m_to_receive(prosumer) == pytest.approx(
            (81.93712, t_return_demand_c, layer_mass_kg + mdot_demand_kg_per_s / 2), .001)

        shs_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] = t_feed_demand_c / 2
        shs_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] = mdot_demand_kg_per_s + 1
        assert shs_controller.t_m_to_receive(prosumer) == pytest.approx((84.1163169, t_return_demand_c, layer_mass_kg - 1), .001)
