import numpy as np
import pandas as pd
from pandapower.timeseries.data_sources.frame_data import DFData

from pandaprosumer import create_controlled_const_profile
from pandaprosumer.controller import ConstProfileController
from pandaprosumer.controller.data_model.const_profile import ConstProfileControllerData
from pandaprosumer.create import create_empty_prosumer_container, create_period

from ..data_sources import FROM_CLAUDIA

def _define_and_get_period_and_data_source(prosumer):
    data = pd.read_excel(FROM_CLAUDIA)
    start = '2020-01-01 00:00:00'
    end = '2020-01-01 11:59:59'
    resol = 3600
    dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
    data.index = dur
    data_source = DFData(data)
    period = create_period(prosumer,
                           3600,
                        '2020-01-01 00:00:00',
                        '2020-01-01 11:59:59',
                        'utc',
                        'default')
    return period, data_source


def _get_all_columns_from_data_source():
    data = pd.read_excel(FROM_CLAUDIA)
    return data.columns.to_list()


def _get_first_row_from_data_source():
    data = pd.read_excel(FROM_CLAUDIA)
    return data.iloc[0]


def _init_const_profile_controller():
    input_columns = ["Tin_cond", "Tout_cond", "Mass-flow-cond", "Tin,evap"]
    result_columns = ["Tin_cond", "Tout_cond", "Mass-flow-cond", "Tin,evap"]
    prosumer = create_empty_prosumer_container()
    period, data_source = _define_and_get_period_and_data_source(prosumer)
    create_controlled_const_profile(prosumer,input_columns,result_columns,period,data_source)
    return prosumer


class TestConstProfile:

    def test_create(self):

        """
        """

        prosumer = _init_const_profile_controller()
        assert len(prosumer.controller) == 1
        assert prosumer.controller.iloc[0].in_service
        assert prosumer.controller.iloc[0].order == 0
        assert prosumer.controller.iloc[0].level == 0

    def test_time(self):

        """
        """

        prosumer = _init_const_profile_controller()
        const_profile_controller = prosumer.controller.iloc[0].object
        assert const_profile_controller.time is None

    def test_dfdata_columns(self):

        """
        """

        prosumer = _init_const_profile_controller()
        const_profile_controller = prosumer.controller.iloc[0].object
        expected = sorted(const_profile_controller.df_data.df.columns.to_list())
        assert expected == sorted(_get_all_columns_from_data_source())

    def test_step_results(self):

        """
        """

        prosumer = _init_const_profile_controller()
        const_profile_controller = prosumer.controller.iloc[0].object
        expected = np.full((1, 4), np.nan)
        assert np.array_equal(const_profile_controller.step_results, expected, equal_nan=True)

    def test_res(self):

        """
        """

        prosumer = _init_const_profile_controller()
        const_profile_controller = prosumer.controller.iloc[0].object
        expected = np.full((1, len(const_profile_controller.time_index), 4), 0.)
        assert np.array_equal(const_profile_controller.res, expected, equal_nan=True)

    def test_time_index(self):

        """
        """

        prosumer = _init_const_profile_controller()
        const_profile_controller = prosumer.controller.iloc[0].object
        period = prosumer.period.iloc[0]

        # First time step should be exactly the period.start
        assert const_profile_controller.df_data.df.iloc[0].name == pd.Timestamp(period.start, tz='utc')

        # Final time step should be exactly the period.end, plus the resolution minus 1 second
        assert const_profile_controller.df_data.df.iloc[-1].name + pd.Timedelta(seconds=period.resolution_s - 1) == pd.Timestamp(period.end, tz='utc')

    def test_time_step(self):

        """
        Tests that execution of the `time_step` method has the intended effect, which is to set the time instance
        variable and updates step_results.
        """

        prosumer = _init_const_profile_controller()
        const_profile_controller = prosumer.controller.iloc[0].object

        time = const_profile_controller.time_index[0]
        const_profile_controller.time_step(prosumer, time)
        assert const_profile_controller.time == time

        # time_step() method resets the internal `step_results` variable to an array of nans
        expected_step_results = np.full((1, 4), np.nan)
        assert np.array_equal(const_profile_controller.step_results, expected_step_results, equal_nan=True)

    def test_control_step(self):

        """
        Tests that execution of the `control_step` method has the intended effect, which is to read the contents of the
        appropriate row of the excel and write it into the first row of .res, and into .step_results. Then it should set
        .applied to True
        """

        prosumer = _init_const_profile_controller()
        const_profile_controller = prosumer.controller.iloc[0].object
        time = const_profile_controller.time_index[0]
        const_profile_controller.time_step(prosumer, time)
        const_profile_controller.control_step(prosumer)

        # Test that the first row of res is populated with this time step's contents in the excel
        first_row = _get_first_row_from_data_source()
        expected = np.array((first_row["Tin_cond"],
                            first_row["Tout_cond"],
                            first_row["Mass-flow-cond"],
                            first_row["Tin,evap"]),
                            dtype=np.float64)
        assert np.array_equal(const_profile_controller.res[0,0], expected)

        # Test that the step results contain what was read from the excel during this time step
        assert np.array_equal(const_profile_controller.step_results[0], expected)

        # Test that .applied is set to True
        assert const_profile_controller.applied

    def test_is_converged(self):

        """
        Tests that the .is_converged method accurately returns the convergence state
        """

        prosumer = _init_const_profile_controller()
        const_profile_controller = prosumer.controller.iloc[0].object
        time = const_profile_controller.time_index[0]
        const_profile_controller.time_step(prosumer, time)

        # Convergence is simply set to True after the control step.
        assert not const_profile_controller.is_converged(prosumer)
        const_profile_controller.control_step(prosumer)
        assert const_profile_controller.is_converged(prosumer)
