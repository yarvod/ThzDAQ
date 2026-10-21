from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class ChannelReading:
    """Measured output of a source or bias channel, SI units."""

    voltage: float  # V
    current: float  # A

    @property
    def power(self) -> float:
        """W"""
        return self.voltage * self.current


@dataclass(frozen=True)
class Trace:
    """Scalar trace, e.g. spectrum analyzer power (dBm) versus frequency (Hz)."""

    frequency: Tuple[float, ...]
    values: Tuple[float, ...]

    def __post_init__(self):
        if len(self.frequency) != len(self.values):
            raise ValueError("frequency and values must have the same length")


@dataclass(frozen=True)
class ComplexTrace:
    """Complex trace, e.g. a VNA S-parameter versus frequency (Hz)."""

    frequency: Tuple[float, ...]
    values: Tuple[complex, ...]
    parameter: str = ""

    def __post_init__(self):
        if len(self.frequency) != len(self.values):
            raise ValueError("frequency and values must have the same length")


def linspace(start: float, stop: float, points: int) -> List[float]:
    """Evenly spaced frequency axis without numpy."""
    if points <= 0:
        return []
    if points == 1:
        return [start]
    step = (stop - start) / (points - 1)
    return [start + i * step for i in range(points)]
