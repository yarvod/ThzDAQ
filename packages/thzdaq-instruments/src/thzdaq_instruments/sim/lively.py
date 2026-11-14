"""Drift and noise for simulators, so a simulated bench looks alive.

Simulators read exact values by default (tests and procedures depend on it).
liven() on a simulator adds a slow drift and a little noise to its readings;
the station does it when the application or the CLI runs with --simulate.
"""

import math
import random
import time
from typing import Optional


class Wobble:
    """drift * sin(2πt / period + phase) + gauss(noise), in the units of the reading."""

    def __init__(
        self,
        drift: float,
        noise: float,
        period: float = 60.0,
        seed: Optional[int] = None,
    ):
        self.drift = drift
        self.noise = noise
        self.period = period
        self._random = random.Random(seed)
        self._phase = self._random.uniform(0, 2 * math.pi)
        self._start = time.monotonic()

    def __call__(self) -> float:
        t = time.monotonic() - self._start
        slow = self.drift * math.sin(2 * math.pi * t / self.period + self._phase)
        return slow + self._random.gauss(0.0, self.noise)


def still() -> float:
    return 0.0
