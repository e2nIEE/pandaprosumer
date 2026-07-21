import pytest
import numpy as np
from pandaprosumer import (create_empty_prosumer_container, create_period, create_mixing_valve,
                           create_controlled_mixing_valve)
from pandaprosumer.mapping.fluid_mix import FluidMixMapping


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestMixingValveElement:
    """Tests the definition of a Mixing Valve element."""

    def test_define_element(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_mixing_valve(prosumer)
        assert hasattr(prosumer, "mixing_valve")
        assert len(prosumer.mixing_valve) == 1

        expected_columns = ['name', 't_in_nom_c', 'overflow_strategy', 'in_service']
        expected_values = [None, 95., 'dump_proportional', True]

        assert list(prosumer.mixing_valve.columns) == expected_columns
        assert prosumer.mixing_valve.iloc[0].values == pytest.approx(expected_values, nan_ok=True)

    def test_define_element_param(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        mv_idx = create_mixing_valve(prosumer, t_in_nom_c=90, overflow_strategy='dump_on_last',
                                     name='foo', in_service=False, index=4, custom='test')
        assert len(prosumer.mixing_valve) == 1
        assert mv_idx == 4
        assert prosumer.mixing_valve.index[0] == mv_idx

        expected_columns = ['name', 't_in_nom_c', 'overflow_strategy', 'in_service', 'custom']
        expected_values = ['foo', 90., 'dump_on_last', False, 'test']

        assert list(prosumer.mixing_valve.columns) == expected_columns
        assert prosumer.mixing_valve.iloc[0].values == pytest.approx(expected_values)

    def test_define_element_invalid_overflow_strategy(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)
        with pytest.raises(ValueError):
            create_mixing_valve(prosumer, overflow_strategy='drop_it')


class TestMixingValveController:
    """Tests the Mixing Valve controller definition and mixing algebra."""

    def test_define_controller(self):
        prosumer = create_empty_prosumer_container()
        create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns(self):
        prosumer = create_empty_prosumer_container()
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        mv = prosumer.controller.iloc[mv_idx].object
        assert mv.input_columns == []
        assert mv.result_columns == ["q_delivered_kw", "mdot_in_kg_per_s", "t_in_c",
                                     "mdot_recirc_kg_per_s", "mdot_out_kg_per_s", "t_out_c", "t_return_c"]

    def test_calculate_mixing_nominal(self):
        """95 in, 80 wished, 70 return, 2 kg/s out: hot leg is 10/25 = 40%."""
        prosumer = create_empty_prosumer_container()
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        mv = prosumer.controller.iloc[mv_idx].object
        mdot_in, mdot_recirc, mdot_out, t_out_c = mv.calculate_mixing(95., 80., 70., 2.)
        assert mdot_in == pytest.approx(0.8)
        assert mdot_recirc == pytest.approx(1.2)
        assert mdot_out == pytest.approx(2.)
        assert t_out_c == pytest.approx(80.)
        # Mass and energy conservation
        assert mdot_in + mdot_recirc == pytest.approx(mdot_out)
        assert mdot_in * (95. - 70.) == pytest.approx(mdot_out * (t_out_c - 70.))

    def test_calculate_mixing_cold_supply(self):
        """Supply at 78 < wished 80: full pass-through, no recirculation."""
        prosumer = create_empty_prosumer_container()
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        mv = prosumer.controller.iloc[mv_idx].object
        assert mv.calculate_mixing(78., 80., 70., 2.) == pytest.approx((2., 0., 2., 78.))

    def test_calculate_mixing_degenerate(self):
        prosumer = create_empty_prosumer_container()
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer))
        mv = prosumer.controller.iloc[mv_idx].object
        # No demand mass flow
        assert mv.calculate_mixing(95., 80., 70., 0.) == pytest.approx((0., 0., 0., 95.))
        # Demand feed == return (no heat wanted)
        assert mv.calculate_mixing(95., 70., 70., 2.) == pytest.approx((0., 0., 0., 95.))
        # Supply at the return temperature: cannot heat at all
        assert mv.calculate_mixing(70., 80., 70., 2.) == pytest.approx((0., 0., 0., 70.))

    @staticmethod
    def _make_controller(prosumer, **kwargs):
        mv_idx = create_controlled_mixing_valve(prosumer, order=0, period=_default_period(prosumer), **kwargs)
        return prosumer.controller.iloc[mv_idx].object

    def test_t_m_to_receive_requests_nominal_temperature(self):
        """The valve asks upstream for t_in_nom_c and the reduced hot-leg mdot."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        assert mv.t_m_to_receive(prosumer) == pytest.approx((95., 70., 0.8))

    def test_control_step_nominal(self):
        """No fixed upstream flow: assume the requested hot leg was delivered at t_in_nom_c."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.control_step(prosumer)

        q_kw = 2. * 4.19 * (80. - 70.)
        expected = [q_kw, 0.8, 95., 1.2, 2., 80., 70.]
        assert mv.step_results == pytest.approx(np.array([expected]), rel=.01)
        assert mv.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 80.,
                                                  FluidMixMapping.MASS_FLOW_KEY: pytest.approx(2.)}]

    def test_control_step_received_flow_and_temperature(self):
        """Producer fixed exactly the requested hot leg at 95: nominal mix."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 95.,
                                        FluidMixMapping.MASS_FLOW_KEY: 0.8}
        mv.control_step(prosumer)
        q_kw = 2. * 4.19 * (80. - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 0.8, 95., 1.2, 2., 80., 70.]]), rel=.01)

    def test_control_step_cold_supply_passthrough(self):
        """Received 78 < wished 80: pass-through at 78, no recirculation."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 78.,
                                        FluidMixMapping.MASS_FLOW_KEY: 2.}
        mv.control_step(prosumer)
        q_kw = 2. * 4.19 * (78. - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 2., 78., 0., 2., 78., 70.]]), rel=.01)

    def test_control_step_short_supply_holds_temperature(self):
        """Producer fixed only 0.4 kg/s (< 0.8 needed): t_out held at 80, flow scaled to 1.0."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 95.,
                                        FluidMixMapping.MASS_FLOW_KEY: 0.4}
        mv.control_step(prosumer)
        q_kw = 1. * 4.19 * (80. - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 0.4, 95., 0.6, 1., 80., 70.]]), rel=.01)

    def test_control_step_excess_supply_runs_hotter(self):
        """Producer fixed 1.0 kg/s (> 0.8 needed, < 2.0 demand): recirc shrinks, mix runs hotter."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 95.,
                                        FluidMixMapping.MASS_FLOW_KEY: 1.}
        mv.control_step(prosumer)
        t_out_c = (1. * 95. + 1. * 70.) / 2.  # 82.5
        q_kw = 2. * 4.19 * (t_out_c - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 1., 95., 1., 2., t_out_c, 70.]]), rel=.01)
        # Energy conservation: hot leg in == mix out
        assert 1. * (95. - 70.) == pytest.approx(2. * (t_out_c - 70.))

    def test_control_step_flood_supply_passthrough_surplus(self):
        """Producer fixed 2.5 kg/s (>= 2.0 demand): full pass-through at 95, surplus dumped."""
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (80., 70., [2.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: 95.,
                                        FluidMixMapping.MASS_FLOW_KEY: 2.5}
        mv.control_step(prosumer)
        q_kw = 2.5 * 4.19 * (95. - 70.)
        assert mv.step_results == pytest.approx(np.array([[q_kw, 2.5, 95., 0., 2.5, 95., 70.]]), rel=.01)
        # dump_proportional: single responder receives everything
        assert mv.result_mass_flow_with_temp == [{FluidMixMapping.TEMPERATURE_KEY: 95.,
                                                  FluidMixMapping.MASS_FLOW_KEY: pytest.approx(2.5)}]

    def test_control_step_no_demand(self):
        prosumer = create_empty_prosumer_container()
        mv = self._make_controller(prosumer, t_in_nom_c=95.)
        mv.t_m_to_deliver = lambda p: (0., 0., [0.])
        mv.time_step(prosumer, "2020-01-01 00:00:00")
        mv.control_step(prosumer)
        assert mv.step_results == pytest.approx(np.array([[0., 0., 95., 0., 0., 95., 0.]]))
