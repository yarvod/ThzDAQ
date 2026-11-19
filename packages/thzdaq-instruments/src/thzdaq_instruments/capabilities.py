"""Instrument abilities as small interfaces.

An instrument or a channel declares the ones it has by inheriting them
(``class RigolChannel(SupplyChannel, OutputProtection)``), consumers depend only on
the ones they use. A capability is what its class says, never what a method's name
happens to match: a power sensor with a ``set_frequency`` of its own is no
frequency source. A method left out fails as the class is instantiated.

A capability gives every part that has it its quantities and actions
(``capability_quantities``, ``capability_actions``): the voltage setpoint of a
VoltageSource, the hot and cold loads of a LoadSwitch. One that refines another
(PreciseVoltageSource of VoltageSource) gives its quantity in place of the other's
of the same key. A driver adds its own with ``quantities`` and ``actions``
(thzdaq_instruments.parts).

Examples:
    power supply channel  -> Switchable, VoltageSource, CurrentSource, VoltageCurrentMeter
    SIS bias channel      -> VoltageSource, VoltageCurrentMeter
    signal generator      -> FrequencySource, PowerLevel, Switchable
"""

from abc import ABC, abstractmethod
from typing import ClassVar, List, Optional, Tuple

from thzdaq_instruments.actions import (
    CONFIGURE_NETWORK,
    CONFIGURE_SPECTRUM,
    READ_TRACE,
    TO_COLD,
    TO_HOT,
    TURN_OFF,
    TURN_ON,
    Action,
)
from thzdaq_instruments.quantities import (
    ANGLE,
    CURRENT_SET,
    FREQUENCY,
    OUTPUT,
    POWER_LEVEL,
    PRECISE_VOLTAGE_SET,
    VOLTAGE_SET,
    Quantity,
)
from thzdaq_instruments.readings import ChannelReading, ComplexTrace, Trace


class Capability(ABC):
    """An ability of a device part: its methods, and the quantities and actions
    it gives every part that has it."""

    capability_quantities: ClassVar[Tuple[Quantity, ...]] = ()
    capability_actions: ClassVar[Tuple[Action, ...]] = ()


def _measure(target):
    return target.measure()


def _temperatures(target):
    return target.read_temperatures()


def _pressures(target):
    return target.read_pressures()


class Identifiable(Capability):
    @abstractmethod
    def identify(self) -> str:
        """Instrument identification, e.g. the *IDN? answer."""


class Switchable(Capability):
    capability_quantities = (OUTPUT,)

    @abstractmethod
    def set_output(self, value: bool) -> None:
        ...

    @abstractmethod
    def get_output(self) -> bool:
        ...


class VoltageSource(Capability):
    capability_quantities = (VOLTAGE_SET,)

    @abstractmethod
    def set_voltage(self, voltage: float) -> None:
        """V"""

    @abstractmethod
    def get_voltage(self) -> float:
        """Programmed voltage, V. Use VoltageCurrentMeter.measure() for the actual one."""


class PreciseVoltageSource(VoltageSource):
    """A voltage source that also corrects its setpoint by readback until the
    measured voltage is the one asked (a SIS bias)."""

    capability_quantities = (PRECISE_VOLTAGE_SET,)

    @abstractmethod
    def set_voltage_precise(self, voltage: float, max_iterations: int = 30) -> float:
        """V; returns the voltage measured, raises InstrumentError when it is
        not reached in max_iterations corrections."""


class CurrentSource(Capability):
    capability_quantities = (CURRENT_SET,)

    @abstractmethod
    def set_current(self, current: float) -> None:
        """A, setpoint or limit"""

    @abstractmethod
    def get_current(self) -> float:
        """Programmed current, A"""


class OutputProtection(Capability):
    """A supply output that switches itself off above a voltage or a current
    (OVP, OCP), whatever the program does."""

    @abstractmethod
    def set_protection(
        self, voltage: Optional[float], current: Optional[float]
    ) -> None:
        """V, A; None leaves that protection as it is."""


class VoltageCurrentMeter(Capability):
    capability_quantities = (
        Quantity("voltage", "Voltage", "V", source=_measure, field="voltage"),
        Quantity("current", "Current", "A", source=_measure, field="current"),
    )

    @abstractmethod
    def measure(self) -> ChannelReading:
        ...


class FrequencySource(Capability):
    capability_quantities = (FREQUENCY,)

    @abstractmethod
    def set_frequency(self, frequency: float) -> None:
        """Hz"""

    @abstractmethod
    def get_frequency(self) -> float:
        """Hz"""


class PowerLevel(Capability):
    capability_quantities = (POWER_LEVEL,)

    @abstractmethod
    def set_power(self, power: float) -> None:
        """dBm"""

    @abstractmethod
    def get_power(self) -> float:
        """dBm"""


class PowerDetector(Capability):
    capability_quantities = (
        Quantity("power", "Power", "dBm", get=lambda t: t.read_power()),
    )

    @abstractmethod
    def read_power(self) -> float:
        """dBm, raises InstrumentError instead of returning None"""


class TunableFilter(Capability):
    capability_quantities = (
        Quantity(
            "frequency", "Frequency", "Hz",
            get=lambda t: t.get_frequency(), setters=("tune",),
        ),
    )  # fmt: skip

    @abstractmethod
    def tune(self, frequency: float) -> float:
        """Tune to a frequency, Hz. Returns the frequency actually set."""

    @abstractmethod
    def get_frequency(self) -> Optional[float]:
        """Hz, the one tuned last (no readback); None before the first tune."""


HOT, COLD = "hot", "cold"  # the loads of a LoadSwitch


class LoadSwitch(Capability):
    """Hot/cold calibration load switch, e.g. a chopper."""

    capability_actions = (TO_HOT, TO_COLD)

    @abstractmethod
    def to_hot(self) -> None:
        ...

    @abstractmethod
    def to_cold(self) -> None:
        ...

    def to(self, load: str) -> None:
        """Turn to the load named: HOT or COLD."""
        turns = {HOT: self.to_hot, COLD: self.to_cold}
        if load not in turns:
            raise ValueError(f"no load {load!r}: {HOT} or {COLD}")
        turns[load]()


class Thermometer(Capability):
    capability_quantities = (
        Quantity("temperature", "Temperature", "K", get=lambda t: t.read_temperature()),
    )

    @abstractmethod
    def read_temperature(self) -> float:
        """K"""


class SpectrumAnalyzer(Capability):
    capability_actions = (CONFIGURE_SPECTRUM, READ_TRACE)

    @abstractmethod
    def set_center_frequency(self, frequency: float) -> None:
        """Hz"""

    @abstractmethod
    def set_span(self, span: float) -> None:
        """Hz"""

    @abstractmethod
    def set_resolution_bandwidth(self, bandwidth: float) -> None:
        """Hz, the nearest supported value is used"""

    @abstractmethod
    def set_video_bandwidth(self, bandwidth: float) -> None:
        """Hz, the nearest supported value is used"""

    @abstractmethod
    def set_continuous_sweep(self, continuous: bool) -> None:
        """Sweep over and over, or once per trigger()."""

    @abstractmethod
    def trigger(self) -> None:
        """Start one sweep (single sweep mode); nothing while sweeping continuously."""

    @abstractmethod
    def read_peak(self) -> Tuple[float, float]:
        """(frequency Hz, power dBm) of the highest peak"""

    @abstractmethod
    def read_trace(self) -> Trace:
        ...


class NetworkAnalyzer(Capability):
    capability_actions = (CONFIGURE_NETWORK, READ_TRACE)

    @abstractmethod
    def set_frequency_range(self, start: float, stop: float) -> None:
        """Hz"""

    @abstractmethod
    def set_points(self, points: int) -> None:
        ...

    @abstractmethod
    def select_parameter(self, parameter: str) -> None:
        """Measure this S-parameter ("S11", "S21", ...) as complex data."""

    @abstractmethod
    def set_averaging(self, count: int) -> None:
        """Sweep averaging, count <= 1 switches it off."""

    @abstractmethod
    def read_trace(self) -> ComplexTrace:
        ...


class VacuumGauge(Capability):
    capability_quantities = (
        Quantity("pressure", "Pressure", "Pa", get=lambda t: t.read_pressure()),
    )

    @abstractmethod
    def read_pressure(self) -> float:
        """Pa"""


class Rotator(Capability):
    """Angles in degrees (the one non-SI unit, as on every lab drawing)."""

    capability_quantities = (ANGLE,)

    @abstractmethod
    def rotate_to(self, angle: float) -> float:
        """Rotate to an absolute angle, returns the angle reached."""

    @abstractmethod
    def get_angle(self) -> float:
        ...


class Compressor(Capability):
    # F-70: discharge, water out, water in (the fourth sensor is spare); return pressure
    capability_quantities = (
        Quantity("temperature_1", "Discharge temperature", "K", source=_temperatures, field=0),
        Quantity("temperature_2", "Water out temperature", "K", source=_temperatures, field=1),
        Quantity("temperature_3", "Water in temperature", "K", source=_temperatures, field=2),
        Quantity("pressure_1", "Return pressure", "Pa", source=_pressures, field=0),
    )  # fmt: skip
    capability_actions = (TURN_ON, TURN_OFF)

    @abstractmethod
    def turn_on(self) -> None:
        ...

    @abstractmethod
    def turn_off(self) -> None:
        ...

    @abstractmethod
    def read_temperatures(self) -> List[float]:
        """K"""

    @abstractmethod
    def read_pressures(self) -> List[float]:
        """Pa, gauge pressure"""


class RawCommands(Capability):
    """An instrument that takes commands as text: what its driver does not wrap
    yet is sent as typed, over its link, with nothing checked."""

    @abstractmethod
    def send_raw(self, command: str, answer: bool) -> Optional[str]:
        """Send the command; with answer, read and return the answer."""


ALL_CAPABILITIES: tuple[type, ...] = (
    Identifiable,
    RawCommands,
    Switchable,
    VoltageSource,
    PreciseVoltageSource,
    CurrentSource,
    OutputProtection,
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


# How an instrument is reached rather than what it does
ACCESS: tuple[type, ...] = (Identifiable, RawCommands)


def capabilities_of(cls: type | None) -> tuple[type, ...]:
    """The capabilities a class declares (inherits), in ALL_CAPABILITIES order."""
    if cls is None:
        return ()
    return tuple(
        capability for capability in ALL_CAPABILITIES if issubclass(cls, capability)
    )
