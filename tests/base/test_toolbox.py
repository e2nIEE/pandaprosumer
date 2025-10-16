import pytest

from pandaprosumer import create_controlled_heat_pump
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.prosumer_toolbox import get_controller_index


def _default_argument():
    return {'max_p_comp_kw': 500,
            'min_p_comp_kw': .01,
            'max_t_cond_out_c': 100,
            'max_cop': 10,
            'pinch_c': 0
            }


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestToolbox:
    """
    Tests the toolbox functions
    """

    def test_get_controller_index_by_name(self):
        prosumer = create_empty_prosumer_container()
        period_idx = _default_period(prosumer)

        create_controlled_heat_pump(prosumer, name="HP1", order=0, period=period_idx, **_default_argument())
        create_controlled_heat_pump(prosumer, name="HP2", order=0, period=period_idx, **_default_argument())

        ctrl_index1 = get_controller_index(prosumer, "HP1")
        ctrl_index2 = get_controller_index(prosumer, "HP2")

        assert ctrl_index1 == 0
        assert ctrl_index2 == 1

        with pytest.raises(NameError):
            # "HP3" is not a valid controller name"
            get_controller_index(prosumer, "HP3")

    def test_multiple_controllers_same_name(self):
        prosumer = create_empty_prosumer_container()
        period_idx = _default_period(prosumer)

        create_controlled_heat_pump(prosumer, name="HP1", order=0, period=period_idx, **_default_argument())
        create_controlled_heat_pump(prosumer, name="HP1", order=0, period=period_idx, **_default_argument())

        with pytest.raises(NameError):
            # "HP1" is not a unique controller name
            get_controller_index(prosumer, "HP1")
