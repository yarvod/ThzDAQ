"""Port adapters: what a configured device exposes on top of an instrument part.

Adapters delegate every attribute they don't override to the wrapped part, so
an LO behind ScaledFrequencySource still offers set_output() and set_power().
Device kinds using them are declared in thzdaq_core.station.kinds.
"""

from typing import Any, Dict, Protocol, runtime_checkable

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


class AttributePort(PortAdapter):
    """A configured device over a shared part, with its own attributes.

    Two SIS configs on one DEV (different mixers, offsets) share the channel
    object; the attributes are applied before every call through this device.
    """

    def __init__(self, target: Any, attributes: Dict[str, Any]):
        super().__init__(target)
        for name in attributes:
            if not hasattr(target, name):
                raise StationError(f"{target!r} has no attribute {name!r}")
        self.attributes = dict(attributes)
        self.apply()

    def apply(self) -> None:
        for name, value in self.attributes.items():
            setattr(self.target, name, value)

    def __getattr__(self, name: str) -> Any:
        if name in ("target", "attributes"):
            raise AttributeError(name)
        if name in self.__dict__.get("attributes", {}):
            return self.attributes[name]
        value = getattr(self.target, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            self.apply()
            return value(*args, **kwargs)

        return call

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__dict__.get("attributes", {}):
            self.attributes[name] = value
            setattr(self.target, name, value)
        else:
            super().__setattr__(name, value)


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


# Device level abstractions defined here, on top of the instrument capabilities
DEVICE_PROTOCOLS = (SidebandSwitch,)
