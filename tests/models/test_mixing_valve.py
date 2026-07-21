import pytest
import numpy as np
from pandaprosumer import create_empty_prosumer_container, create_period, create_mixing_valve


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
