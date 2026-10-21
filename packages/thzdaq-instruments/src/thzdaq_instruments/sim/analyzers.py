import cmath
import math
from typing import Callable, Optional, Tuple

from thzdaq_instruments.instrument import Instrument
from thzdaq_instruments.readings import ComplexTrace, Trace, linspace


class SimSpectrumAnalyzer(Instrument):
    """A single tone at `tone_frequency` above a flat noise floor."""

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        tone_frequency: float = 5e9,
        tone_power: float = -40.0,
        noise_floor: float = -90.0,
        points: int = 501,
    ):
        super().__init__(name=name)
        self.tone_frequency = tone_frequency
        self.tone_power = tone_power
        self.noise_floor = noise_floor
        self.points = points
        self.center = tone_frequency
        self.span = 1e6
        self.resolution_bandwidth = 1e3
        self.video_bandwidth = 1e3

    def identify(self) -> str:
        return "THZDAQ,SimSpectrumAnalyzer,0,1.0"

    def set_center_frequency(self, frequency: float) -> None:
        self.center = frequency

    def set_span(self, span: float) -> None:
        self.span = span

    def set_resolution_bandwidth(self, bandwidth: float) -> None:
        self.resolution_bandwidth = bandwidth

    def set_video_bandwidth(self, bandwidth: float) -> None:
        self.video_bandwidth = bandwidth

    def _level(self, frequency: float) -> float:
        offset = (frequency - self.tone_frequency) / self.resolution_bandwidth
        tone = self.tone_power - 10 * offset**2
        return max(tone, self.noise_floor)

    def read_trace(self) -> Trace:
        frequency = linspace(
            self.center - self.span / 2, self.center + self.span / 2, self.points
        )
        return Trace(tuple(frequency), tuple(self._level(f) for f in frequency))

    def read_peak(self) -> Tuple[float, float]:
        trace = self.read_trace()
        index = max(range(len(trace.values)), key=trace.values.__getitem__)
        return trace.frequency[index], trace.values[index]


class SimNetworkAnalyzer(Instrument):
    """Reflection of a resistive load at the end of a lossless line."""

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        load: float = 25.0,  # Ohm
        delay: float = 1e-9,  # s, line electrical length
        model: Optional[Callable[[float], complex]] = None,
    ):
        super().__init__(name=name)
        self.start, self.stop, self.points = 2e9, 12e9, 201
        self.power = -30.0
        self.parameter = "S11"
        self.averaging = 1
        gamma = (load - 50) / (load + 50)
        self.model = model or (
            lambda f: gamma * cmath.exp(-2j * math.pi * f * 2 * delay)
        )

    def identify(self) -> str:
        return "THZDAQ,SimNetworkAnalyzer,0,1.0"

    def set_frequency_range(self, start: float, stop: float) -> None:
        self.start, self.stop = start, stop

    def set_points(self, points: int) -> None:
        self.points = int(points)

    def select_parameter(self, parameter: str) -> None:
        self.parameter = parameter

    def set_averaging(self, count: int) -> None:
        self.averaging = count

    def set_power(self, power: float) -> None:
        self.power = power

    def get_power(self) -> float:
        return self.power

    def read_trace(self) -> ComplexTrace:
        frequency = linspace(self.start, self.stop, self.points)
        return ComplexTrace(
            tuple(frequency), tuple(self.model(f) for f in frequency), self.parameter
        )
