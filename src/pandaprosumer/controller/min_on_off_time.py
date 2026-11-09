"""
Module containing the MinOnOffTimeMixin class: minimum running and stop times of a producer controller.
"""

import numpy as np
import pandas as pd


class MinOnOffTimeMixin:
    """
    Track the on/off state of a producer and since when it is in it, to enforce the element parameters
    ``min_on_time_s`` (once started, the unit cannot stop before it has run for this duration) and
    ``min_off_time_s`` (once stopped, the unit cannot restart before it has been stopped for this duration).

    The state of a converged time step is recorded in ``finalize_step``, so reapplies within a time step do not
    count as switches. The state at the first time step of a run is assumed to have lasted long enough: only a start
    or a stop during the run locks the unit. The history is reset at the start of each run.

    To be listed before the controller base class, e.g. ``class Foo(MinOnOffTimeMixin, BasicProsumerController)``.
    The controller sets ``_on_off_result_key`` to the key of ``last_result`` telling whether the unit runs (> 0).
    """

    _on_off_result_key = 'q_kw'

    def _get_duration_s(self, prosumer, attr_name):
        """
        Read a duration parameter of the element, 0 if it is not set

        :param attr_name: Name of the duration parameter (min_on_time_s or min_off_time_s)
        """
        # None if the element has no such column (e.g. created before the parameter existed)
        duration_s = self._get_element_param(prosumer, attr_name)
        if duration_s is None or np.isnan(duration_s):
            return 0.
        return float(duration_s)

    def _check_min_on_time(self, prosumer, min_power_param, element_label):
        """
        min_on_time_s needs a positive minimum power: it is the power that holds the unit on

        :param min_power_param: Name of the minimum power parameter of the element (e.g. min_q_kw)
        :param element_label: Name of the element type, for the error message
        """
        min_power = self._get_element_param(prosumer, min_power_param)
        if self._get_duration_s(prosumer, 'min_on_time_s') > 0 and not (min_power is not None and min_power > 0):
            raise ValueError(f"{element_label} {self.name} in prosumer {prosumer.name} has min_on_time_s but no "
                             f"positive {min_power_param} ({min_power})")

    def _reset_on_off_state(self):
        """
        Forget the on/off history at the start of a run
        """
        self.is_on = None
        # Time step at which the unit started or stopped, None if it has not switched since the start of the run
        self.state_start_time = None

    def _time_in_state_s(self):
        """
        Duration since the unit entered its current state (running or stopped), at the start of the current time step [s]
        """
        if self.state_start_time is None:
            # The state of the first time step of the run is assumed to have lasted long enough
            return np.inf
        return (pd.Timestamp(self.time) - pd.Timestamp(self.state_start_time)).total_seconds()

    def _is_stop_locked(self, prosumer):
        """
        True if the unit is running but has not run for min_on_time_s yet, so it cannot stop
        """
        min_on_time_s = self._get_duration_s(prosumer, 'min_on_time_s')
        return bool(self.is_on) and self._time_in_state_s() < min_on_time_s - 1e-6

    def _is_start_locked(self, prosumer):
        """
        True if the unit is stopped but has not been stopped for min_off_time_s yet, so it cannot restart
        """
        min_off_time_s = self._get_duration_s(prosumer, 'min_off_time_s')
        return self.is_on is False and self._time_in_state_s() < min_off_time_s - 1e-6

    def time_series_initialization(self, container):
        self._reset_on_off_state()
        return super().time_series_initialization(container)

    def finalize_step(self, container, time):
        """
        Record the state (running or stopped) of the converged time step, and since when the unit is in it
        """
        super().finalize_step(container, time)
        if self._on_off_result_key not in self.last_result:
            return
        is_on = bool(self.last_result[self._on_off_result_key] > 1e-3)
        if self.is_on is not None and is_on != self.is_on:
            self.state_start_time = time
        self.is_on = is_on
