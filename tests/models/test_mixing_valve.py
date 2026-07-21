import pytest
import numpy as np
from pandaprosumer import (create_empty_prosumer_container, create_period, create_mixing_valve,
                           create_controlled_mixing_valve)


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
