"""Coil current sequence that demagnetizes the SIS mixer magnet."""

from typing import List


def _segment(start: float, stop: float, step: float) -> List[float]:
    """Points from start (excluded) to stop (included) with at most `step` spacing."""
    count = max(1, int(round(abs(stop - start) / step + 0.5 - 1e-9)))
    return [start + (stop - start) * i / count for i in range(1, count + 1)]


def demagnetization_currents(
    minimum: float, maximum: float, step: float
) -> List[float]:
    """Sweep minimum -> maximum, then swing around the centre with the
    amplitude shrinking by `step` every half period, ending at the centre.

    The legacy sequence swept every later pass in the same direction, so the
    current jumped from the bottom of one pass to the top of the next; here the
    direction alternates and the current never jumps by more than `step`.
    """
    if step <= 0:
        raise ValueError("step must be positive")
    if maximum <= minimum:
        raise ValueError("maximum must be above minimum")
    centre = (minimum + maximum) / 2
    amplitude = (maximum - minimum) / 2
    points = [minimum] + _segment(minimum, maximum, step)
    level, sign = maximum, -1
    amplitude -= step
    while amplitude > 1e-12:
        target = centre + sign * amplitude
        points += _segment(level, target, step)
        level, sign = target, -sign
        amplitude -= step
    if abs(level - centre) > 1e-12:
        points += _segment(level, centre, step)
    return points
