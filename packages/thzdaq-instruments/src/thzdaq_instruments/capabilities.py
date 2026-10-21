"""Instrument abilities as small interfaces.

An instrument or a channel implements several of them, consumers depend only on the ones they
use. Capabilities contain methods only, so ``issubclass(SomeDriver, Switchable)`` works and the
registry derives a driver's capabilities from its class.

Examples:
    power supply channel  -> Switchable, VoltageSource, CurrentSource, VoltageCurrentMeter
    SIS bias channel      -> VoltageSource, VoltageCurrentMeter
    signal generator      -> FrequencySource, PowerLevel, Switchable
"""

from typing import Protocol, runtime_checkable

from thzdaq_instruments.readings import ChannelReading


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
)


def capabilities_of(cls: type | None) -> tuple[type, ...]:
    if cls is None:
        return ()
    return tuple(
        capability for capability in ALL_CAPABILITIES if issubclass(cls, capability)
    )
