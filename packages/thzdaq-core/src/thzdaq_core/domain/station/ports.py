"""Adapters over an instrument part: the attributes of a configured device,
the guard every device is handed out in.

An adapter delegates every attribute it doesn't override to the wrapped part.
"""

from typing import Any, Callable, Dict, Iterable, Optional, Set, Tuple

from thzdaq_instruments.quantities import Quantity

from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.station.safety import Guard

Pause = Callable[[float], None]  # waits so many seconds
Told = Callable[[str, float], None]  # hears a quantity key and the value set
# Hears, at a run's first change of a quantity, how to set it back
Changed = Callable[[Callable[[], None]], None]
# A port's own attributes: never looked up on the device it wraps
PORT_ATTRIBUTES = (
    "target", "guard", "setters", "pause", "setpoints", "told", "changed",
    "changed_keys",
)  # fmt: skip


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


class GuardedPort(PortAdapter):
    """A device as the station hands it out. Every call that sets a quantity
    (its Quantity.setters) is checked by the guard first, so nothing outside
    the limits reaches the instrument whoever calls; a change larger than the
    bench step goes in steps, pausing between them for the bench rate.

    The value before a change is the setpoint last written through the device
    (read once when there is none yet), so a sweep costs no extra query. The
    ports of one device share it; each waits with its own pause (a run's stops
    on cancel), and a run's port tells the values it sets.

    A run's port also tells, at the first change of each quantity, how to set
    it back to what it was before (changed): the run does so as it ends, so a
    measurement leaves the bench as it found it. A quantity whose value is not
    known before (one that cannot be read, never set yet) stays as the run
    leaves it.
    """

    def __init__(
        self,
        target: Any,
        guard: Guard,
        quantities: Iterable[Quantity],
        pause: Pause,
        setpoints: Optional[Dict[str, float]] = None,
        told: Optional[Told] = None,
        changed: Optional[Changed] = None,
    ):
        super().__init__(target)
        self.guard = guard
        self.setters = {name: q for q in quantities for name in q.setters}
        self.pause = pause
        self.setpoints: Dict[str, float] = {} if setpoints is None else setpoints
        self.told = told
        self.changed = changed
        self.changed_keys: Set[str] = set()  # those changed hears of already

    def for_run(
        self,
        pause: Pause,
        told: Optional[Told] = None,
        changed: Optional[Changed] = None,
    ) -> "GuardedPort":
        """The same device for a run: its ramps wait with the run's pause,
        told hears the values it sets and changed how to set each back."""
        quantities = set(self.setters.values())
        return GuardedPort(
            self.target, self.guard, quantities, pause, self.setpoints, told, changed
        )

    def forget(self) -> None:
        """The setpoints are not known any more (a raw write): each change reads
        its own first."""
        self.setpoints.clear()

    def __getattr__(self, name: str) -> Any:
        if name in PORT_ATTRIBUTES:
            raise AttributeError(name)
        value = getattr(self.target, name)
        quantity = self.setters.get(name)
        if quantity is None:
            return value

        def guarded(new: float, *args, **kwargs):
            return self._set(quantity, value, new, args, kwargs)

        return guarded

    def _set(
        self,
        quantity: Quantity,
        method: Callable[..., Any],
        value: float,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> Any:
        key = quantity.key
        self.guard.check(quantity, value)
        if self.changed is not None and key not in self.changed_keys:
            self.changed_keys.add(key)
            self._note_before(quantity)
        before = self._before(quantity) if self.guard.ramps(key) else None
        plain = getattr(self.target, quantity.setters[0])
        last = before
        for step in self.guard.ladder(key, before, value)[:-1]:
            plain(step)
            self.setpoints[key] = step
            self.pause(self.guard.delay(key, step - last))
            last = step
        result = method(value, *args, **kwargs)
        self.setpoints[key] = value
        if self.told is not None:
            self.told(key, value)
        return result

    def _note_before(self, quantity: Quantity) -> None:
        """Tell changed how to set quantity back to its value now, through
        this port: checked and ramped as any change."""
        before = self._before(quantity)
        if before is None:
            return
        setter = getattr(self, quantity.setters[0])
        self.changed(lambda: setter(before))

    def _before(self, quantity: Quantity) -> Optional[float]:
        """The setpoint now: the last one written, else read once."""
        if quantity.key not in self.setpoints and quantity.readable:
            self.setpoints[quantity.key] = quantity.read(self.target)
        return self.setpoints.get(quantity.key)
