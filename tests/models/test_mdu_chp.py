import pytest
from pandaprosumer.create import *
from pandaprosumer.create_controlled import *


def _default_argument():
    """Default test values for MDU CHP element"""
    return {
        'size': 100,  
    }


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestMduChp:
    """Tests the functionalities of an MDU CHP element and controller"""

    def test_define_element(self):
        """Test the creation of an MDU CHP element with default parameter values"""
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_mdu_chp(prosumer, **_default_argument())
        assert hasattr(prosumer, "mdu_chp")
        assert len(prosumer.mdu_chp) == 1

        expected_columns = ["size", "in_service"]
        expected_values = [100, True]

        assert sorted(prosumer.mdu_chp.columns) == sorted(expected_columns)
        assert prosumer.mdu_chp.iloc[0].values == pytest.approx(expected_values)

    def test_define_element_with_parameters(self):
        """Test the creation of an MDU CHP element with custom parameter values"""
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {
            'size': 200,
        }

        mdu_chp_idx = create_mdu_chp(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "mdu_chp")
        assert len(prosumer.mdu_chp) == 1
        assert mdu_chp_idx == 4
        assert prosumer.mdu_chp.index[0] == mdu_chp_idx

        expected_columns = ["name", "size", "in_service", "custom"]
        expected_values = ['foo', 200, False, 'test']

        assert sorted(prosumer.mdu_chp.columns) == sorted(expected_columns)
        assert prosumer.mdu_chp.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """Test the creation of an MDU CHP controller in a prosumer container"""
        prosumer = create_empty_prosumer_container()
        create_controlled_mdu_chp(prosumer, period=_default_period(prosumer), **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """Test the input and result columns of the MDU CHP controller"""
        prosumer = create_empty_prosumer_container()
        mdu_chp_controller_index = create_controlled_mdu_chp(prosumer, period=_default_period(prosumer), **_default_argument())
        mdu_chp_controller = prosumer.controller.iloc[mdu_chp_controller_index].object

        input_columns_expected = ['Size', 'Return water temperature', 'Supply water temperature', 'Heat demand']
        result_columns_expected = ['q_fuel_mw', 'p_el_mw']

        assert mdu_chp_controller.input_columns == input_columns_expected
        assert mdu_chp_controller.result_columns == result_columns_expected

    def test_controller_element_index(self):
        """Test that the controller has the correct element index"""
        prosumer = create_empty_prosumer_container()
        mdu_chp_controller_index = create_controlled_mdu_chp(prosumer, period=_default_period(prosumer), **_default_argument())
        mdu_chp_controller = prosumer.controller.iloc[mdu_chp_controller_index].object

        # Verify element was created
        assert hasattr(prosumer, "mdu_chp")
        assert len(prosumer.mdu_chp) == 1

        # Verify controller references the correct element
        assert len(mdu_chp_controller.element_index) == 1
        assert mdu_chp_controller.element_index[0] == prosumer.mdu_chp.index[0]
