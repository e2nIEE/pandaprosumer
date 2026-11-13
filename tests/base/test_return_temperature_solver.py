"""
Unit tests of :class:`ReturnTemperatureSolver`, the fixed-point solver a producer short of mass flow
uses for the return its responders give back.
"""
import numpy as np
import pytest

from pandaprosumer.constants import MAX_RERUN
from pandaprosumer.controller.return_temperature import ReturnTemperatureSolver


def _solve(g, t_start_c, threshold_c=0.01, max_passes=200):
    """Drive the solver the way a producer's rerun loop does; return (root, number of passes)."""
    solver = ReturnTemperatureSolver(threshold_c)
    t_c = t_start_c
    for n_passes in range(1, max_passes + 1):
        t_next_c = solver.next_guess(t_c, g(t_c))
        if t_next_c is None:
            return t_c, n_passes
        t_c = t_next_c
    raise AssertionError(f"no convergence after {max_passes} passes")


def _substitution_passes(g, t_start_c, threshold_c=0.01, max_passes=1000):
    t_c = t_start_c
    for n_passes in range(1, max_passes + 1):
        if abs(g(t_c) - t_c) <= threshold_c:
            return n_passes
        t_c = g(t_c)
    return max_passes


def _capped_boiler_return(t_c, q_kw=100., cp=4.19, t_feed_c=80., returns_c=(40., 72.), mdots=(95 / (4.19 * 40), 1.)):
    """Return mix of a 100 kW boiler serving two responders in merit order, for an assumed return t_c."""
    mdot_kg_per_s = q_kw / (cp * (t_feed_c - t_c))
    first = min(mdot_kg_per_s, mdots[0])
    second = min(mdot_kg_per_s - first, mdots[1])
    return (first * returns_c[0] + second * returns_c[1]) / (first + second)


class TestReturnTemperatureSolver:
    def test_already_converged_returns_none(self):
        solver = ReturnTemperatureSolver(0.01)
        assert solver.next_guess(50., 50.005) is None
        assert not solver.started

    def test_slow_contraction_converges_in_a_few_passes(self):
        """g contracts by 0.95 per pass: substitution needs ~150 passes, the secant a handful."""
        def g(t_c):
            return 10. + 0.95 * t_c  # root at 200
        assert _substitution_passes(g, 60.) > MAX_RERUN
        root_c, n_passes = _solve(g, 60.)
        assert root_c == pytest.approx(200., abs=0.01)
        assert n_passes <= 4

    def test_capped_boiler_with_a_hot_last_return(self):
        """The case that failed: the merit-order mix has a kink where the second responder is served fully."""
        t_start_c = 56.4  # the mix of the returns weighted by the flows the responders ask for
        assert _substitution_passes(_capped_boiler_return, t_start_c) > MAX_RERUN
        root_c, n_passes = _solve(_capped_boiler_return, t_start_c)
        assert abs(_capped_boiler_return(root_c) - root_c) <= 0.01
        assert n_passes <= 6

    @pytest.mark.parametrize("t_start_c", [0., 30., 60., 79.])
    def test_root_bracketed_from_both_sides(self, t_start_c):
        """A steep, kinked g: secant steps that leave the bracket fall back to bisection."""
        def g(t_c):
            return 45. + (0.99 * (t_c - 45.) if t_c > 45. else 0.2 * (t_c - 45.))
        root_c, n_passes = _solve(g, t_start_c)
        assert root_c == pytest.approx(45., abs=1.)
        assert abs(g(root_c) - root_c) <= 0.01
        assert n_passes <= MAX_RERUN

    def test_guesses_stay_inside_the_bracket(self):
        """Every guess lies strictly between the highest tried return below the root and the lowest above it."""
        def g(t_c):
            return 50. + 0.9 * (t_c - 50.) + 2. * np.sin(t_c)
        solver = ReturnTemperatureSolver(1e-6)
        below_c, above_c = -np.inf, np.inf
        t_c = 20.
        for _ in range(MAX_RERUN):
            g_c = g(t_c)
            if g_c > t_c:
                below_c = max(below_c, t_c)
            else:
                above_c = min(above_c, t_c)
            t_c = solver.next_guess(t_c, g_c)
            if t_c is None:
                break
            assert below_c < t_c < above_c
        assert t_c is None

    def test_guesses_stay_within_the_responders_returns(self):
        """A mix lies between the coldest and the warmest return: no guess leaves that range, even when
        a secant step through two passes would (a storage then diverged to negative layer temperatures)."""
        returns_c = (40., 60.)

        def g(t_c):
            return 40. if t_c > 42.9 else 47.5 + 0.5 * (42.9 - t_c)
        solver = ReturnTemperatureSolver(0.01)
        t_c = 53.6
        for _ in range(MAX_RERUN):
            t_c = solver.next_guess(t_c, g(t_c), returns_c)
            if t_c is None:
                break
            assert 40. <= t_c <= 60.
        assert t_c is None

    def test_jump_without_root_stops_on_the_jump(self):
        """g jumps across the diagonal (a storage's discharge gate): no fixed point exists, substitution
        cycles forever; the solver stops on the jump once the bracket is narrower than the threshold."""
        def g(t_c):
            return 40. if t_c > 42.9 else 47.5
        assert g(g(47.5)) == 47.5  # substitution cycles: 47.5 -> 40 -> 47.5 -> ...
        root_c, n_passes = _solve(g, 53.6)
        assert root_c == pytest.approx(42.9, abs=0.02)
        assert n_passes <= MAX_RERUN
