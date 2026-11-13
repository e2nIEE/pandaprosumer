"""
Return temperature of a producer that cannot deliver all the mass flow its responders ask for.

A producer short of mass flow (at its maximum power, or fed with less primary flow than it needs)
serves its responders in merit order: the first ones fully, the last one partly. The water it gets
back is the mix of the responders' returns weighted by the flows it actually delivers, and that mix
depends on the return the producer assumed: a warmer return lets a power-capped producer push more
flow, so more of it goes to the last responder. The return is therefore the fixed point of
``t = g(t)``.

Plain substitution ``t <- g(t)`` contracts by ``(T_last - t) / (T_feed - t)``, where ``T_last`` is the
return of the responder served partly: it slows down as that return approaches the feed. A 100 kW
gas boiler sending 95 kW to a 40 °C return and the rest to a 72 °C one, both at 80 °C, contracts by
about 0.76 per pass and needed some 30 passes, more than ``MAX_RERUN``.
:class:`ReturnTemperatureSolver` takes secant steps instead and converges in a few passes.
"""

import numpy as np

from pandaprosumer.constants import TEMPERATURE_CONVERGENCE_THRESHOLD_C


class ReturnTemperatureSolver:
    """
    Solve ``h(t) = g(t) - t = 0`` for the return temperature ``t`` a producer gets back.

    The caller computes, for the return it tried, the mix its responders really give back
    (``g(t)``) and asks :meth:`next_guess` for the return to try next. A mix lies between the
    coldest and the warmest of the responders' returns, so ``h >= 0`` at the coldest and ``h <= 0`` at
    the warmest: the root is bracketed from the first pass on. Each pass narrows the
    bracket (``h > 0`` below the root, ``h < 0`` above it) and takes a secant step on ``h`` through
    the last two passes; a step that leaves the bracket, or a bracket that did not halve over the last
    two passes, is replaced by a bisection.

    ``g`` can jump: a storage's discharge gates (minimum useful temperature, 0.5 K above the return)
    open or close with the return it assumes, and ``h`` may then change sign without a root, where
    substitution cycled forever between the two sides. The solver stops once the bracket is
    narrower than the threshold: the return is then known to within the threshold, even if the mix
    for it differs. (The jump first seen came from the storage's loop itself, feeding a pass the
    outlet temperature of the previous one; fixed, but the gates can still flip.)

    :param threshold_c: Converged once ``|g(t) - t|``, or the bracket around the root, is at most this (°C)
    """

    def __init__(self, threshold_c=TEMPERATURE_CONVERGENCE_THRESHOLD_C):
        self.threshold_c = threshold_c
        self.started = False
        self._previous = None
        self._below_c = -np.inf
        self._above_c = np.inf
        self._below_tried = self._above_tried = False
        self._widths_c = []

    def next_guess(self, t_tried_c, t_mixed_c, t_returns_c=()):
        """
        Next return temperature to try, or ``None`` once converged.

        :param t_tried_c: Return temperature the producer was calculated with (°C)
        :param t_mixed_c: Mix of the returns its responders give back for the flows it delivered (°C)
        :param t_returns_c: The responders' returns (°C): the mix lies between the lowest and the highest
        """
        h_c = t_mixed_c - t_tried_c
        if abs(h_c) <= self.threshold_c:
            return None
        self.started = True
        if len(t_returns_c) > 0:
            # a mix can equal the coldest or the warmest return (all the flow to one responder):
            # those bounds are admissible guesses, unlike a bound already tried
            if np.min(t_returns_c) > self._below_c:
                self._below_c, self._below_tried = float(np.min(t_returns_c)), False
            if np.max(t_returns_c) < self._above_c:
                self._above_c, self._above_tried = float(np.max(t_returns_c)), False
        if h_c > 0 and t_tried_c >= self._below_c:
            self._below_c, self._below_tried = t_tried_c, True
        elif h_c < 0 and t_tried_c <= self._above_c:
            self._above_c, self._above_tried = t_tried_c, True
        bracketed = np.isfinite(self._below_c) and np.isfinite(self._above_c)
        if bracketed:
            width_c = self._above_c - self._below_c
            if width_c <= self.threshold_c and self._below_c - self.threshold_c <= t_tried_c <= self._above_c + self.threshold_c:
                return None
            self._widths_c.append(width_c)

        guess_c = t_mixed_c
        if self._previous is not None:
            t_previous_c, h_previous_c = self._previous
            if t_tried_c != t_previous_c and h_c != h_previous_c:
                guess_c = t_tried_c - h_c * (t_tried_c - t_previous_c) / (h_c - h_previous_c)
        stalled = len(self._widths_c) >= 3 and self._widths_c[-1] > self._widths_c[-3] / 2
        above_low = guess_c > self._below_c if self._below_tried else guess_c >= self._below_c
        below_high = guess_c < self._above_c if self._above_tried else guess_c <= self._above_c
        if stalled or not (above_low and below_high):
            if bracketed:
                guess_c = (self._below_c + self._above_c) / 2
            else:
                guess_c = t_mixed_c
        self._previous = (t_tried_c, h_c)
        return guess_c
