"""
Level comparisons of MappedController: a level is an int or, without check_order, a list of levels.
"""
import pytest

from pandaprosumer.controller.mapped import MappedController


@pytest.mark.parametrize("level_a, level_b, expected", [
    (0, 0, True),
    (0, 1, False),
    ([0, 2], 2, True),
    (1, [0, 2], False),
    ([0, 1], [1, 3], True),
    ([0], [2, 3], False),
])
def test_levels_overlap(level_a, level_b, expected):
    assert MappedController._levels_overlap(level_a, level_b) is expected
