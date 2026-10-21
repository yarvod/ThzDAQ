"""Instrument abilities as small interfaces.

An instrument or a channel implements several of them, consumers depend only on the ones they
use. Capabilities contain methods only, so ``issubclass(SomeDriver, Switchable)`` works and the
registry derives a driver's capabilities from its class.

Examples:
    power supply channel  -> Switchable, VoltageSource, CurrentSource, VoltageCurrentMeter
    SIS bias channel      -> VoltageSource, VoltageCurrentMeter
    signal generator      -> FrequencySource, PowerLevel, Switchable
"""

from typing import List, Protocol, Tuple, runtime_checkable

from thzdaq_instruments.readings import ChannelReading, ComplexTrace, Trace


@runtime_checkable
class Identifiable(Protocol):
    def identify(self) -> str:
        """Instrument identification, e.g. the *IDN? answer."""


@runtime_checkable
class Switchable(Protocol):
    def set_output(self, value: bool) -> None:
        ...

    def get_output(self) -> bool:
        ...


@runtime_checkable
class VoltageSource(Protocol):
    def set_voltage(self, voltage: float) -> None:
        """V"""

    def get_voltage(self) -> float:
        """Programmed voltage, V. Use VoltageCurrentMeter.measure() for the actual one."""


@runtime_checkable
class CurrentSource(Protocol):
    def set_current(self, current: float) -> None:
        """A, setpoint or limit"""

    def get_current(self) -> float:
        """Programmed current, A"""


@runtime_checkable
class VoltageCurrentMeter(Protocol):
    def measure(self) -> ChannelReading:
        ...


@runtime_checkable
class FrequencySource(Protocol):
    def set_frequency(self, frequency: float) -> None:
        """Hz"""

    def get_frequency(self) -> float:
        """Hz"""


@runtime_checkable
class PowerLevel(Protocol):
    def set_power(self, power: float) -> None:
        """dBm"""

    def get_power(self) -> float:
        """dBm"""


@runtime_checkable
class PowerDetector(Protocol):
    def read_power(self) -> float:
        """dBm, raises InstrumentError instead of returning None"""


@runtime_checkable
class TunableFilter(Protocol):
    def tune(self, frequency: float) -> float:
        """Tune to a frequency, Hz. Returns the frequency actually set."""


@runtime_checkable
class LoadSwitch(Protocol):
    """Hot/cold calibration load switch, e.g. a chopper."""

    def to_hot(self) -> None:
        ...

    def to_cold(self) -> None:
        ...


@runtime_checkable
class Thermometer(Protocol):
    def read_temperature(self) -> float:
        """K"""


@runtime_checkable
class SpectrumAnalyzer(Protocol):
    def set_center_frequency(self, frequency: float) -> None:
        """Hz"""

    def set_span(self, span: float) -> None:
        """Hz"""

    def set_resolution_bandwidth(self, bandwidth: float) -> None:
        """Hz, the nearest supported value is used"""

    def set_video_bandwidth(self, bandwidth: float) -> None:
        """Hz, the nearest supported value is used"""

    def read_peak(self) -> Tuple[float, float]:
        """(frequency Hz, power dBm) of the highest peak"""

    def read_trace(self) -> Trace:
        ...


@runtime_checkable
class NetworkAnalyzer(Protocol):
    def set_frequency_range(self, start: float, stop: float) -> None:
        """Hz"""

    def set_points(self, points: int) -> None:
        ...

    def select_parameter(self, parameter: str) -> None:
        """Measure this S-parameter ("S11", "S21", ...) as complex data."""

    def set_averaging(self, count: int) -> None:
        """Sweep averaging, count <= 1 switches it off."""

    def read_trace(self) -> ComplexTrace:
        ...


@runtime_checkable
class VacuumGauge(Protocol):
    def read_pressure(self) -> float:
        """Pa"""


@runtime_checkable
class Rotator(Protocol):
    """Angles in degrees (the one non-SI unit, as on every lab drawing)."""

    def rotate_to(self, angle: float) -> float:
        """Rotate to an absolute angle, returns the angle reached."""

    def get_angle(self) -> float:
        ...


@runtime_checkable
class Compressor(Protocol):
    def turn_on(self) -> None:
        ...

    def turn_off(self) -> None:
        ...

    def read_temperatures(self) -> List[float]:
        """K"""

    def read_pressures(self) -> List[float]:
        """Pa, gauge pressure"""


ALL_CAPABILITIES: tuple[type, ...] = (
    Identifiable,
    Switchable,
    VoltageSource,
    CurrentSource,
    VoltageCurrentMeter,
    FrequencySource,
    PowerLevel,
    PowerDetector,
    TunableFilter,
    LoadSwitch,
    Thermometer,
    SpectrumAnalyzer,
    NetworkAnalyzer,
    VacuumGauge,
    Rotator,
    Compressor,
)


def capabilities_of(cls: type | None) -> tuple[type, ...]:
    if cls is None:
        return ()
    return tuple(
        capability for capability in ALL_CAPABILITIES if issubclass(cls, capability)
    )
