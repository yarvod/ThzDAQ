"""A device as the station hands it out: a port over an instrument part that
implements the capabilities the part declares, and nothing else.

The class of a port is built once per class of part (port_class): it inherits
the part's capabilities, so ``isinstance(port, PowerDetector)`` holds by
declaration, and implements each of their methods by calling the part. A method
that a capability's quantity names as its setter goes through the guard. What
no capability declares (a driver's own methods) is no method of the port.

A part's own quantities and actions (an NRX's averaging, a sensor's zero) are
reached by their declarations (read, write, act), a setpoint among them through
the same guard. The attributes of a configured device (a SIS bias's offsets) are
set on its part before every call (Attributes).
"""

import functools
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Set,
    Tuple,
)

from thzdaq_instruments.actions import Action
from thzdaq_instruments.capabilities import capabilities_of
from thzdaq_instruments.parts import declared_by, read_values
from thzdaq_instruments.quantities import Quantity

from thzdaq_core.domain.errors import StationError
from thzdaq_core.domain.station.safety import Guard

Pause = Callable[[float], None]  # waits so many seconds
Told = Callable[[str, float], None]  # hears a quantity key and the value set
# Hears, at a run's first change of a quantity, how to set it back
Changed = Callable[[Callable[[], None]], None]


class Attributes:
    """The attributes of a configured device (a SIS bias's offsets), set on its
    part before every call through the device: two devices configured on one
    channel share the part."""

    def __init__(self, part: Any, values: Mapping[str, Any]):
        for name in values:
            if not hasattr(part, name):
                raise StationError(f"{part!r} has no attribute {name!r}")
        self.values = dict(values)

    def apply(self, part: Any) -> None:
        for name, value in self.values.items():
            setattr(part, name, value)


NO_ATTRIBUTES = Attributes(None, {})


class GuardedPort:
    """The base of every port class (port_class). Every call that sets a
        quantity (its Quantity.setters) is checked by the guard first, so nothing
        outside the limits reaches the instrument whoever calls; a change larger
        than the bench step goes in steps, pausing between them for the bench rate.
    A sweep the instrument makes by itself (Quantity.sweepers) is checked whole:
    both ends within the limits, its steps within the bench step and rate.

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
        attributes: Attributes = NO_ATTRIBUTES,
        setpoints: Optional[Dict[str, float]] = None,
        told: Optional[Told] = None,
        changed: Optional[Changed] = None,
    ):
        """quantities: those the guard checks and ramps (numbers it sets)."""
        self.target = target  # the part
        self.guard = guard
        self.setters = {name: q for q in quantities for name in q.setters}
        self.sweepers = {name: q for q in quantities for name in q.sweepers}
        self.pause = pause
        self.attributes = attributes
        self.setpoints: Dict[str, float] = {} if setpoints is None else setpoints
        self.told = told
        self.changed = changed
        self.changed_keys: Set[str] = set()  # those changed hears of already

    def __repr__(self):
        return f"{self.__class__.__name__}({self.target!r})"

    def for_run(
        self,
        pause: Pause,
        told: Optional[Told] = None,
        changed: Optional[Changed] = None,
    ) -> "GuardedPort":
        """The same device for a run: its ramps wait with the run's pause,
        told hears the values it sets and changed how to set each back."""
        return type(self)(
            self.target,
            self.guard,
            {*self.setters.values(), *self.sweepers.values()},
            pause,
            self.attributes,
            self.setpoints,
            told,
            changed,
        )

    def forget(self) -> None:
        """The setpoints are not known any more (a raw write): each change reads
        its own first."""
        self.setpoints.clear()

    # A part's quantities and actions by their declarations
    def read(self, quantities: Iterable[Quantity]) -> Dict[str, Any]:
        """Values of these quantities of the part, a shared source read once."""
        self.attributes.apply(self.target)
        return read_values(self.target, quantities)

    def write(self, quantity: Quantity, value: Any) -> Any:
        """Set a quantity of the part: a setpoint through the guard."""
        if quantity.setters:
            return self._setter(quantity.setters[0], quantity.parse(value), (), {})
        self.attributes.apply(self.target)
        return quantity.write(self.target, value)

    def act(self, action: Action, arguments: Mapping[str, Any]) -> Any:
        """Run an action of the part with its arguments, bound already."""
        self.attributes.apply(self.target)
        return action.call(self.target, **arguments)

    # How the methods of a port class call the part
    def _call(self, name: str, *args, **kwargs) -> Any:
        self.attributes.apply(self.target)
        return getattr(self.target, name)(*args, **kwargs)

    def _setter(
        self, name: str, value: Any, args: Tuple[Any, ...], kwargs: Dict[str, Any]
    ) -> Any:
        quantity = self.setters.get(name)
        if quantity is None:  # a value the guard has no limits for (an output)
            return self._call(name, value, *args, **kwargs)
        return self._set(quantity, name, value, args, kwargs)

    def _set(
        self,
        quantity: Quantity,
        name: str,
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
        plain = quantity.setters[0]
        last = before
        for step in self.guard.ladder(key, before, value)[:-1]:
            self._call(plain, step)
            self.setpoints[key] = step
            self.pause(self.guard.delay(key, step - last))
            last = step
        result = self._call(name, value, *args, **kwargs)
        self.setpoints[key] = value
        if self.told is not None:
            self.told(key, value)
        return result

    def _sweeper(
        self, name: str, start: float, stop: float, step: float, dwell: float
    ) -> Iterator[Any]:
        """A sweep the instrument makes by itself, checked before it starts:
        both ends within the limits, its steps within the bench step and rate.
        The start is set as any change (checked, ramped, set back as the run
        ends); the setpoint is stop once the sweep ends, unknown if it stops."""
        quantity = self.sweepers.get(name)
        if quantity is None:  # a value the guard has no limits for
            return self._call(name, start, stop, step, dwell)
        self.guard.check(quantity, stop)
        self.guard.check_sweep(quantity, step, dwell)
        self._set(quantity, quantity.setters[0], start, (), {})
        return self._swept(quantity, name, start, stop, step, dwell)

    def _swept(
        self,
        quantity: Quantity,
        name: str,
        start: float,
        stop: float,
        step: float,
        dwell: float,
    ) -> Iterator[Any]:
        key = quantity.key
        del self.setpoints[key]  # where it is while it sweeps nobody knows
        yield from self._call(name, start, stop, step, dwell)
        self.setpoints[key] = stop
        if self.told is not None:
            self.told(key, stop)

    def _note_before(self, quantity: Quantity) -> None:
        """Tell changed how to set quantity back to its value now, through
        this port: checked and ramped as any change."""
        before = self._before(quantity)
        if before is None:
            return
        plain = quantity.setters[0]
        self.changed(lambda: self._set(quantity, plain, before, (), {}))

    def _before(self, quantity: Quantity) -> Optional[float]:
        """The setpoint now: the last one written, else read once."""
        if quantity.key not in self.setpoints and quantity.readable:
            self.attributes.apply(self.target)
            self.setpoints[quantity.key] = quantity.read(self.target)
        return self.setpoints.get(quantity.key)


def _calling(name: str, doc: Optional[str]) -> Callable[..., Any]:
    def method(self, *args, **kwargs):
        return self._call(name, *args, **kwargs)

    method.__name__, method.__doc__ = name, doc
    return method


def _setting(name: str, doc: Optional[str]) -> Callable[..., Any]:
    def method(self, value, *args, **kwargs):
        return self._setter(name, value, args, kwargs)

    method.__name__, method.__doc__ = name, doc
    return method


def _sweeping(name: str, doc: Optional[str]) -> Callable[..., Any]:
    def method(self, start, stop, step, dwell):
        return self._sweeper(name, start, stop, step, dwell)

    method.__name__, method.__doc__ = name, doc
    return method


@functools.lru_cache(maxsize=None)
def port_class(part_class: type) -> type:
    """The class of the ports over parts of this class: a GuardedPort with the
    part's capabilities, its methods built from their declarations, and the
    part's own quantities and actions declared as the part's class declares
    them (thzdaq_instruments.parts asks the port as it asks the part)."""
    capabilities = capabilities_of(part_class)
    quantities = [q for c in capabilities for q in c.capability_quantities]
    setters = {name for quantity in quantities for name in quantity.setters}
    sweepers = {name for quantity in quantities for name in quantity.sweepers}
    namespace: Dict[str, Any] = {
        "__module__": __name__,
        "quantities": declared_by(part_class, "quantities")[1],
        "actions": declared_by(part_class, "actions")[1],
    }
    for capability in capabilities:
        for name, member in vars(capability).items():
            public = callable(member) and not name.startswith("_")
            if public and hasattr(GuardedPort, name):
                raise TypeError(
                    f"{capability.__name__}.{name} is a name of the port itself"
                )
        for name in sorted(capability.__abstractmethods__):
            doc = getattr(capability, name).__doc__
            if name in sweepers:
                build = _sweeping
            else:
                build = _setting if name in setters else _calling
            namespace.setdefault(name, build(name, doc))
    # The most refined ones: a capability another one refines comes with it
    bases = tuple(
        capability
        for capability in capabilities
        if not any(
            c is not capability and issubclass(c, capability) for c in capabilities
        )
    )
    return type(f"{part_class.__name__}Port", (GuardedPort, *bases), namespace)


def port(
    part: Any,
    guard: Guard,
    quantities: Iterable[Quantity],
    pause: Pause,
    attributes: Attributes = NO_ATTRIBUTES,
) -> GuardedPort:
    """A port over the part, of the class its own class gets."""
    return port_class(type(part))(part, guard, quantities, pause, attributes)
