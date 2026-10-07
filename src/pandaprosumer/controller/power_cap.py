"""
Time-varying power caps: an optional controller input that lowers an element's maximum power for one
time step (e.g. a grid operator's flexibility call mapped from a schedule profile).
"""

import numpy as np


def _setpoint(controller, input_name):
    """
    The cap carried by the input ``input_name`` for this time step, or NaN when none applies.

    NaN (input not mapped, or not declared by a custom data model) or a negative value means "no cap" —
    a time-series driver cannot emit NaN, so a negative value is how it opts out on a given step.
    """
    if input_name not in controller.input_columns:
        return np.nan
    try:
        value = float(controller._get_input(input_name))
    except (TypeError, ValueError, IndexError):  # IndexError: inputs set narrower than declared
        return np.nan
    return np.nan if np.isnan(value) or value < 0 else value


def _capped(max_value, cap):
    """The effective maximum: ``max_value`` (None when NaN/None) lowered by ``cap`` (NaN = no cap)."""
    if max_value is None or (isinstance(max_value, float) and np.isnan(max_value)):
        max_value = None
    if np.isnan(cap):
        return max_value
    return cap if max_value is None else min(max_value, cap)
