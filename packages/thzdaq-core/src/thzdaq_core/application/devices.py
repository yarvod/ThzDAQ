"""Reading and setting device quantities and running device actions, each in
its instrument's lane; what is read or set becomes the known value, a set or an
action is an event. The safe state of the profile is a set per value.

A set or an action that changes a device a running measurement sweeps needs
share; the measurements using the device note who changed what
(thzdaq_core.domain.leases). Leases change only when runs start and end, so the
check just before the write holds.
"""

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from thzdaq_api.devices import SafeValue
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ActionDone, QuantitySet
from thzdaq_api.leases import EXCLUSIVE
from thzdaq_api.measurement_file import CONFLICTS, INTERACTIONS
from thzdaq_instruments.actions import Action
from thzdaq_instruments.errors import InstrumentError
from thzdaq_instruments.quantities import Quantity, read_values
from thzdaq_instruments.units import format_value

from thzdaq_core.application.approvals import Ask
from thzdaq_core.application.bench import Bench
from thzdaq_core.application.clock import wall_time
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.values import KnownValues
from thzdaq_core.domain.leases import Lease, LeaseConflict, Leases

# note(run id, metadata key, entry) into a running measurement
Note = Callable[[int, str, Dict[str, Any]], None]
JUMP = 10.0  # a set that changes a value this many times is pointed out


def shown(spec: Any, value: Any) -> str:
    """A value of a quantity or an action argument as people read it."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        return format_value(value, spec.unit)
    return str(value)


def jump(before: Any, after: Any) -> str:
    """ " (×1000)" for a change by a factor of JUMP or more (a mV given as V)."""
    numbers = all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in (before, after)
    )
    if not numbers or before == 0 or after == 0:
        return ""
    factor = after / before
    return f" (×{factor:.6g})" if not 1 / JUMP < abs(factor) < JUMP else ""


class DeviceAccess:
    def __init__(
        self,
        bench: Bench,
        known: KnownValues,
        events: EventBus,
        leases: Leases,
        note: Note,
    ):
        self.bench = bench
        self.known = known
        self.events = events
        self.leases = leases
        self.note = note

    def quantities(self, ref: str) -> List[Quantity]:
        self.bench.info(ref)  # an unknown device is NOT_FOUND
        return self.bench.station.quantities(ref)

    def quantity(self, ref: str, key: str) -> Quantity:
        for quantity in self.quantities(ref):
            if quantity.key == key:
                return quantity
        keys = ", ".join(q.key for q in self.quantities(ref))
        raise LabError(ErrorCode.NOT_FOUND, f"{ref} has no {key!r}", f"it has: {keys}")

    def readable(
        self, ref: str, keys: Optional[Iterable[str]] = None
    ) -> List[Quantity]:
        """Every readable quantity, or the listed ones (all must be readable)."""
        wanted = (
            [q for q in self.quantities(ref) if q.readable]
            if keys is None
            else [self.quantity(ref, key) for key in keys]
        )
        unreadable = [q.key for q in wanted if not q.readable]
        if unreadable:
            raise LabError(ErrorCode.NOT_ALLOWED, f"{ref}: {unreadable} cannot be read")
        return wanted

    def read(self, ref: str, keys: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        wanted = self.readable(ref, keys)
        values = self.bench.run(ref, lambda device: read_values(device, wanted))
        self.known.update(ref, values)
        return values

    def read_later(
        self,
        ref: str,
        keys: Optional[Iterable[str]],
        deliver: Callable[[Optional[Dict[str, Any]], Optional[BaseException]], None],
    ) -> None:
        """A read that does not wait (a poll): deliver(values, error) in the lane."""
        wanted = self.readable(ref, keys)

        def done(values, error):
            if error is None:
                self.known.update(ref, values)
            deliver(values, error)

        self.bench.submit(ref, lambda device: read_values(device, wanted), done)

    def write(
        self, ref: str, key: str, value: Any, origin: str, share: bool = False
    ) -> Any:
        """Set a quantity; the value as given (a text may carry its unit) is
        parsed by the quantity. Returns the value set."""
        quantity = self.quantity(ref, key)
        if not quantity.settable:
            raise LabError(ErrorCode.NOT_ALLOWED, f"{ref}: {key} cannot be set")
        try:
            parsed = quantity.parse(value)
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        users = self._users(ref, share)
        before = self.known.get(ref, key)
        self.bench.run(ref, lambda device: quantity.write(device, parsed))
        self.known.update(ref, {key: parsed})
        self.events.publish(QuantitySet(ref, key, parsed, before, origin))
        self._note(users, origin, ref, key=key, before=before, value=parsed)
        return parsed

    def proposed(self, ref: str, key: str, value: Any) -> Ask:
        """A set as a person reads it before allowing it: from what to what in
        the unit of the quantity, a jump, the danger, a sweep it disturbs."""
        quantity = self.quantity(ref, key)
        if not quantity.settable:
            raise LabError(ErrorCode.NOT_ALLOWED, f"{ref}: {key} cannot be set")
        try:
            after = quantity.parse(value)
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        before = self.known.get(ref, key)
        leap = jump(before, after)
        unusual = self.bench.station.guard(ref).unusual(quantity, after)
        warning = self._warning(ref, quantity.danger, unusual)
        return Ask(
            f"{ref} · {quantity.title}",
            f"{shown(quantity, before)} → {shown(quantity, after)}{leap}",
            warning,
            ref if quantity.danger else "",
            shown(quantity, after),
            risky=bool(leap or warning),
        )

    def proposed_action(self, ref: str, key: str, arguments: Dict[str, Any]) -> Ask:
        action = self.action(ref, key)
        try:
            bound = action.bind(arguments)
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        given = [
            f"{argument.title} {shown(argument, bound[argument.key])}"
            for argument in action.arguments
            if argument.key in bound
        ]
        warning = self._warning(ref, action.danger)
        return Ask(
            f"{ref} · {action.title}",
            ", ".join(given) or "no arguments",
            warning,
            ref if action.danger else "",
            risky=bool(warning),
        )

    def _warning(self, ref: str, danger: str, unusual: Optional[str] = None) -> str:
        """The danger of a step, a value beyond the warn range and the sweep of
        another measurement it disturbs (allowing it shares the device)."""
        swept = tuple(lease for lease in self.leases.of(ref) if lease.mode == EXCLUSIVE)
        sweeps = f"{LeaseConflict(swept)}: it notes the change" if swept else ""
        return "; ".join(filter(None, (danger, unusual, sweeps)))

    def safe_state(self, origin: str, share: bool = False) -> Tuple[SafeValue, ...]:
        """Every value of the profile's safe state, in its order; one that
        fails does not stop the others."""
        done = []
        for ref, values in self.bench.station.config.safety.safe_state.items():
            for key, value in values.items():
                try:
                    value = self.write(ref, key, value, origin, share)
                except (LabError, InstrumentError) as e:
                    done.append(SafeValue(ref, key, value, str(e)))
                else:
                    done.append(SafeValue(ref, key, value))
        return tuple(done)

    def actions(self, ref: str) -> List[Action]:
        self.bench.info(ref)  # an unknown device is NOT_FOUND
        return self.bench.station.actions(ref)

    def action(self, ref: str, key: str) -> Action:
        for action in self.actions(ref):
            if action.key == key:
                return action
        keys = ", ".join(a.key for a in self.actions(ref)) or "none"
        raise LabError(
            ErrorCode.NOT_FOUND, f"{ref} has no action {key!r}", f"it has: {keys}"
        )

    def act(
        self,
        ref: str,
        key: str,
        arguments: Dict[str, Any],
        origin: str,
        share: bool = False,
    ) -> Any:
        """Run an action; its arguments as given (a text may carry its unit) are
        parsed by the action. Returns what the action returns (a trace)."""
        action = self.action(ref, key)
        try:
            bound = action.bind(arguments)
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        users = self._users(ref, share) if action.changes else []
        result = self.bench.run(ref, lambda device: action.call(device, **bound))
        if action.changes:
            self.events.publish(ActionDone(ref, key, bound, origin))
            self._note(users, origin, ref, action=key, arguments=bound)
        return result

    def _users(self, ref: str, share: bool) -> List[Lease]:
        """The runs using a device; one sweeping it refuses a change without share."""
        users = self.leases.of(ref)
        swept = [lease for lease in users if lease.mode == EXCLUSIVE]
        if swept and not share:
            raise LabError(
                ErrorCode.CONFLICT,
                str(LeaseConflict(tuple(swept))),
                "call again with share to go on: the measurement notes it",
            )
        return users

    def _note(self, users: List[Lease], origin: str, ref: str, **what: Any) -> None:
        """Who changed what, into the runs using the device."""
        change = {"at": wall_time(), "by": origin, "device": ref, **what}
        for lease in users:
            kind = CONFLICTS if lease.mode == EXCLUSIVE else INTERACTIONS
            self.note(lease.owner, kind, change)
