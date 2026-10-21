"""Port adapters: what a role exposes on top of an instrument part.

Adapters delegate every attribute they don't override to the wrapped part, so
an LO behind ScaledFrequencySource still offers set_output() and set_power().
New adapters are added with register_adapter() without touching the station.
"""

from typing import Any, Callable, Dict, Optional, Protocol, runtime_checkable

from thzdaq_instruments.capabilities import FrequencySource, Switchable

from thzdaq_core.errors import StationError

SIDE_BANDS = ("upper", "lower")


@runtime_checkable
class SidebandSwitch(Protocol):
    """Routes the upper or lower IF channel of a 2SB mixer to the detector."""

    def select(self, side_band: str) -> None:
        ...

    def selected(self) -> str:
        ...


class PortAdapter:
    def __init__(self, target: Any):
        self.target = target

    def __getattr__(self, name: str) -> Any:
        # Only called for attributes missing on the adapter itself
        if name == "target":
            raise AttributeError(name)
        return getattr(self.target, name)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.target!r})"


class SwitchPort(PortAdapter):
    """Switchable with optional inversion: True means 'active' for the role."""

    def __init__(self, target: Switchable, inverted: bool = False):
        super().__init__(target)
        self.inverted = bool(inverted)

    def set_output(self, value: bool) -> None:
        self.target.set_output(bool(value) != self.inverted)

    def get_output(self) -> bool:
        return self.target.get_output() != self.inverted


class ScaledFrequencySource(PortAdapter):
    """Frequency at the mixer for a source behind a multiplier chain (e.g. LO x18)."""

    def __init__(self, target: FrequencySource, multiplier: float = 1.0):
        super().__init__(target)
        if multiplier <= 0:
            raise StationError("Frequency multiplier must be positive")
        self.multiplier = float(multiplier)

    def set_frequency(self, frequency: float) -> None:
        self.target.set_frequency(frequency / self.multiplier)

    def get_frequency(self) -> float:
        return self.target.get_frequency() * self.multiplier


class SidebandSelector(PortAdapter):
    """Routes the upper or lower IF channel of a 2SB mixer with one switch."""

    def __init__(self, target: Switchable, upper_when_on: bool = True):
        super().__init__(target)
        self.upper_when_on = bool(upper_when_on)

    def select(self, side_band: str) -> None:
        if side_band not in SIDE_BANDS:
            raise StationError(f"Unknown sideband {side_band!r}")
        self.target.set_output((side_band == "upper") == self.upper_when_on)

    def selected(self) -> str:
        on = self.target.get_output()
        return "upper" if on == self.upper_when_on else "lower"


AdapterFactory = Callable[..., Any]
ADAPTERS: Dict[str, AdapterFactory] = {
    "switch": SwitchPort,
    "scaled_frequency": ScaledFrequencySource,
    "sideband_selector": SidebandSelector,
}


def register_adapter(name: str, factory: AdapterFactory, replace: bool = False) -> None:
    if name in ADAPTERS and not replace:
        raise StationError(f"Port adapter {name!r} is already registered")
    ADAPTERS[name] = factory


def build_adapter(name: Optional[str], part: Any, options: Dict[str, Any]) -> Any:
    if name is None:
        if options:
            raise StationError("Adapter options given without an adapter")
        return part
    try:
        factory = ADAPTERS[name]
    except KeyError:
        raise StationError(
            f"Unknown port adapter {name!r}, available: {sorted(ADAPTERS)}"
        ) from None
    try:
        return factory(part, **options)
    except TypeError as e:
        raise StationError(f"Adapter {name!r}: {e}") from e
