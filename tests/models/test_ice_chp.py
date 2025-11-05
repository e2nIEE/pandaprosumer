# from pandaprosumer.pv_module.source.pv_production import PvProduction
import pytest
import pandas as pd
import numpy as np
import joblib
from pandapower.timeseries.data_sources.frame_data import DFData



"""Enter the environment. Comment init. Run
python -m pytest --cov=pandaprosumer2/controller tests/models/test_combined_heat_and_power.py 
"""


def _default_argument():
    """Default test values based on actual data ranges"""
    return {
        'Size': 10,  # Range: 10-200
        'Heat_demand': 4,  # Range: 4-375
        'Return_water_temperature': 40,  # Range: 40-55
        'Supply_water_temperature': 78,  # Range: 78-99
        'p_th_mw': 8,  # Range: 8-810
        'p_el_mw': 2.0  # Range: 2.0-200
    }


def _max_argument():
    """Maximum values from actual data ranges"""
    return {
        'Size': 200,
        'Heat_demand': 375,
        'Return_water_temperature': 55,
        'Supply_water_temperature': 99,
        'p_th_mw': 810,
        'p_el_mw': 200.0
    }


def test_chp_validation():
    """Test CHP input validation with actual data ranges"""
    inputs = _default_argument()

    # Test minimum values
    with pytest.raises(ValueError):
        inputs["Size"] = 9  # Below minimum 10
        chp_ulj(**inputs)

    # Test maximum values
    inputs = _max_argument()
    with pytest.raises(ValueError):
        inputs["Size"] = 201  # Above maximum 200
        chp_ulj(**inputs)


def test_chp_input_validation():
    """Test CHP input parameter validation with actual ranges"""
    inputs = {
        "Size": 10,
        "Return_water_temperature": 40,
        "Supply_water_temperature": 78,
        "Heat_demand": 4,
        "period_start": "2020-01-01 00:00:00",
        "period_end": "2020-01-01 01:00:00",
        "cycle": "topping",
        "location_lat": 37.8882,
        "location_long": 4.7794
    }

    with pytest.raises(ValueError):
        del inputs["Size"]
        chp_ulj(**inputs)


def test_prepare_data():
    """Test data preparation with actual data ranges"""
    test_data = pd.DataFrame({
        "Size": [10, 100, 200],
        "Return_water_temperature": [40, 45, 55],
        "Supply_water_temperature": [78, 85, 99],
        "Heat_demand": [4, 200, 375]
    })

    test_file = "test_chp_data.xlsx"
    test_data.to_excel(test_file, index=False)

    processed_data = prepare_data(
        test_file,
        "2020-01-01 00:00:00",
        "2020-01-01 02:00:00",
        3600,
        10
    )

    assert isinstance(processed_data, pd.DataFrame)
    assert len(processed_data) == 3
    assert all(40 <= temp <= 55 for temp in processed_data["Return_water_temperature"])
    assert all(78 <= temp <= 99 for temp in processed_data["Supply_water_temperature"])
    assert all(4 <= demand <= 375 for demand in processed_data["Heat_demand"])


def test_model_prediction():
    """Test model prediction with actual data ranges"""
    input_data = np.array([
        [10, 40, 78, 4],  # Minimum values
        [200, 55, 99, 375]  # Maximum values
    ])

    try:
        model = load_model("model_weights.pkl")
        scalers = joblib.load("scalers.pkl")

        predictions = predict_with_model(
            model,
            input_data,
            scalers['input_scaler'],
            scalers['target_scaler']
        )

        # Verify predictions are within expected ranges
        assert all(8 <= heat <= 810 for heat in predictions[:, 0])  # Total heat of steam
        assert all(2.0 <= power <= 200.0 for power in predictions[:, 1])  # Electricity generation

    except FileNotFoundError:
        pytest.skip("Model files not found, skipping test")


def test_chp_simulation():
    """Test CHP simulation with actual data ranges"""
    test_data = pd.DataFrame({
        "Size": [10, 200],
        "Return water temperature": [40, 55],
        "Supply water temperature": [78, 99],
        "Heat demand": [4, 375]
    })

    data_source = DFData(test_data)

    try:
        prosumer = chp_ulj(
            data_source=data_source,
            cycle="topping",
            size=10,
            profile_name_demand=[
                "Size",
                "Return water temperature",
                "Supply water temperature",
                "Heat demand"
            ],
            period_start="2020-01-01 00:00:00",
            period_end="2020-01-01 01:00:00"
        )

        assert prosumer is not None

    except Exception as e:
        pytest.fail(f"Simulation process failed: {str(e)}")


def _default_period(prosumer):
    return create_period(prosumer, 1,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestCombinedHeatAndPower:
    """Tests the functionalities of a CHP element and controller"""

    def test_define_element(self):
        """Test the creation of a CHP element with default parameters values"""
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        create_chp(prosumer, **_default_argument())
        assert hasattr(prosumer, "chp")
        assert len(prosumer.chp) == 1

        expected_columns = ["Size", "Heat_demand", "Return_water_temperature",
                            "Supply_water_temperature", "Tp_th_mw",
                            "p_el_mw", "in_service"]
        expected_values = [10, 4, 40, 78, 8, 2.0, True]

        assert sorted(prosumer.chp.columns) == sorted(expected_columns)
        assert prosumer.chp.iloc[0].values == pytest.approx(expected_values)

    def test_define_element_with_parameters(self):
        """Test the creation of a CHP element with custom parameters values"""
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)

        params = {
            'Size': 200,
            'Heat_demand': 375,
            'Return_water_temperature': 55,
            'Supply_water_temperature': 99,
            'p_th_mw': 810,
            'p_el_mw': 2.0
        }

        chp_idx = create_chp(prosumer, name='foo', in_service=False, custom='test', index=4, **params)
        assert hasattr(prosumer, "chp")
        assert len(prosumer.chp) == 1
        assert chp_idx == 4
        assert prosumer.chp.index[0] == chp_idx

        expected_columns = ["name", "Size", "Heat_demand", "Return_water_temperature",
                            "Supply_water_temperature", "p_th_mw",
                            "p_el_mw", "in_service", "custom"]
        expected_values = ['foo', 200, 375, 55, 99, 810, 2.0, False, 'test']

        assert sorted(prosumer.chp.columns) == sorted(expected_columns)
        assert prosumer.chp.iloc[0].values == pytest.approx(expected_values)

    def test_define_controller(self):
        """Test the creation of a CHP controller in a prosumer container"""
        prosumer = create_empty_prosumer_container()
        create_controlled_chp(prosumer, period=_default_period(prosumer), **_default_argument())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_controller_columns_default(self):
        """Test the input and result columns of the CHP controller"""
        prosumer = create_empty_prosumer_container()
        chp_controller_index = create_controlled_chp(prosumer, period=_default_period(prosumer), **_default_argument())
        chp_controller = prosumer.controller.iloc[chp_controller_index].object

        input_columns_expected = ['Size', 'Heat_demand', 'Return_water_temperature', 'Supply_water_temperature']
        result_columns_expected = ['p_th_mw', 'p_el_mw']

        assert chp_controller.input_columns == input_columns_expected
        assert chp_controller.result_columns == result_columns_expected

    def test_controller_run_control_no_demand(self):
        """Test the CHP run control method with no demand"""
        prosumer = create_empty_prosumer_container()
        chp_controller_index = create_controlled_chp(prosumer, period=_default_period(prosumer), **_default_argument())
        chp_controller = prosumer.controller.iloc[chp_controller_index].object

        chp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        chp_controller.control_step(prosumer)

        expected = [0, 0]  # No heat and electricity generation when no demand
        assert chp_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_demand(self):
        """Test the CHP run control method with a typical demand"""
        prosumer = create_empty_prosumer_container()
        chp_controller_index = create_controlled_chp(prosumer, period=_default_period(prosumer), **_default_argument())
        chp_controller = prosumer.controller.iloc[chp_controller_index].object

        chp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        chp_controller.control_step(prosumer)

        expected = [8, 2.0]  # Expected heat and electricity generation
        assert chp_controller.step_results == pytest.approx(np.array([expected]))

    def test_controller_run_control_max_demand(self):
        """Test the CHP run control method with maximum demand"""
        params = _default_argument()
        params['Size'] = 200
        params['Heat_demand'] = 375
        params['Return_water_temperature'] = 55
        params['Supply_water_temperature'] = 99

        prosumer = create_empty_prosumer_container()
        chp_controller_index = create_controlled_chp(prosumer, period=_default_period(prosumer), **params)
        chp_controller = prosumer.controller.iloc[chp_controller_index].object

        chp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        chp_controller.control_step(prosumer)

        expected = [810, 200.0]  # Maximum heat and electricity generation
        assert chp_controller.step_results == pytest.approx(np.array([expected]))



