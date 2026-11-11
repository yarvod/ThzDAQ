"""Reading and setting device quantities and running device actions, each in
its instrument's lane; what is read or set becomes the known value, a set or an
action is an event. The safe state of the profile is a set per value.

A set or an action that changes a device a running measurement sweeps needs
share; the measurements using the device note who changed what
(thzdaq_core.domain.leases). Leases change only when runs start and end, so the
check just before the write holds.

A call may be made within a measurement (a script's session, Within): its own
leases do not conflict, the devices it agreed to share are shared, and what it
sets is told as its run's sets are.

A raw command goes to an instrument as typed, past every guard. A write may
change any device on the instrument: it checks and notes the leases of all of
them, and leaves their values unknown, forgotten by the daemon and the guards
and read again in the lane. Every raw command is an event and a line of the
daemon's log, with who sent it and what came back.
"""

import functools
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from thzdaq_api.devices import UNCHECKED, RawReply, SafeValue, raw_query
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ActionDone, QuantitySet, RawSent, ReadFailed, Values
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

logger = logging.getLogger(__name__)

# note(run id, metadata key, entry) into a running measurement
Note = Callable[[int, str, Dict[str, Any]], None]
JUMP = 10.0  # a set that changes a value this many times is pointed out
RAW_QUERY, RAW_WRITE = "raw query", "raw write"  # how a person reads which it is


class Within(Protocol):
    """Where a call is made: outside any measurement, or within one."""

    owner: Optional[int]  # the measurement whose leases are the caller's own

    def shares(self, ref: str) -> bool:
        """It agreed to share the device while another measurement sweeps it."""

    def tell(self, ref: str, key: str, value: Any, before: Any, origin: str) -> None:
        """What a set set."""

    def allow_raw(self, instrument: str, command: str) -> None:
        """A raw write to the instrument went (a person allowed it): within a
        measurement, its next ones go without asking until it ends."""


class Outside:
    """A call outside any measurement: a set is an event of its own, and
    every raw write is asked."""

    owner = None

    def __init__(self, events: EventBus):
        self.events = events

    def shares(self, ref: str) -> bool:
        return False

    def tell(self, ref: str, key: str, value: Any, before: Any, origin: str) -> None:
        self.events.publish(QuantitySet(ref, key, value, before, origin))

    def allow_raw(self, instrument: str, command: str) -> None:
        pass


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
        self.outside = Outside(events)

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
        self,
        ref: str,
        key: str,
        value: Any,
        origin: str,
        share: bool = False,
        within: Optional[Within] = None,
    ) -> Any:
        """Set a quantity; the value as given (a text may carry its unit) is
        parsed by the quantity. Returns the value set."""
        within = within or self.outside
        quantity, parsed = self.checked(ref, key, value)
        users = self._users((ref,), share, within)
        before = self.known.get(ref, key)
        self.bench.run(ref, lambda device: quantity.write(device, parsed))
        self.known.update(ref, {key: parsed})
        within.tell(ref, key, parsed, before, origin)
        self._note(users, origin, ref, key=key, before=before, value=parsed)
        return parsed

    def checked(self, ref: str, key: str, value: Any) -> Tuple[Quantity, Any]:
        """The quantity and the value it would be set to (a text may carry its
        unit); one outside the limits of the device is refused before anything
        is sent or anybody asked."""
        quantity = self.quantity(ref, key)
        if not quantity.settable:
            raise LabError(ErrorCode.NOT_ALLOWED, f"{ref}: {key} cannot be set")
        try:
            parsed = quantity.parse(value)
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        if quantity.kind in ("float", "int"):
            problems = self.bench.station.limit_problems(ref, key, [parsed])
            if problems:
                raise LabError(ErrorCode.OUT_OF_LIMITS, "; ".join(problems))
        return quantity, parsed

    def proposed(
        self, ref: str, key: str, value: Any, within: Optional[Within] = None
    ) -> Ask:
        """A set as a person reads it before allowing it: from what to what in
        the unit of the quantity, a jump, the danger, a sweep it disturbs."""
        quantity, after = self.checked(ref, key, value)
        before = self.known.get(ref, key)
        leap = jump(before, after)
        unusual = self.bench.station.guard(ref).unusual(quantity, after)
        sweeps = self._sweeps((ref,), within or self.outside)
        warning = "; ".join(filter(None, (quantity.danger, unusual, sweeps)))
        return Ask(
            f"{ref} · {quantity.title}",
            f"{shown(quantity, before)} → {shown(quantity, after)}{leap}",
            warning,
            ref if quantity.danger else "",
            shown(quantity, after),
            risky=bool(leap or warning),
            grave=bool(quantity.danger or sweeps),
        )

    def proposed_action(
        self,
        ref: str,
        key: str,
        arguments: Dict[str, Any],
        within: Optional[Within] = None,
    ) -> Ask:
        action, bound = self.bound(ref, key, arguments)
        given = [
            f"{argument.title} {shown(argument, bound[argument.key])}"
            for argument in action.arguments
            if argument.key in bound
        ]
        sweeps = self._sweeps((ref,), within or self.outside) if action.changes else ""
        warning = "; ".join(filter(None, (action.danger, sweeps)))
        return Ask(
            f"{ref} · {action.title}",
            ", ".join(given) or "no arguments",
            warning,
            ref if action.danger else "",
            risky=bool(warning),
            grave=bool(warning),
        )

    def _sweeps(self, refs: Iterable[str], within: Within) -> str:
        """The sweeps of other measurements a change disturbs (allowing it
        shares the devices); none where the caller shares them already."""
        swept = self._swept(refs, within)
        return f"{LeaseConflict(swept)}: it notes the change" if swept else ""

    def _swept(self, refs: Iterable[str], within: Within) -> Tuple[Lease, ...]:
        """Leases of other measurements sweeping these devices, but for those
        the caller shares."""
        return tuple(
            lease
            for ref in refs
            if not within.shares(ref)
            for lease in self.leases.of(ref)
            if lease.mode == EXCLUSIVE and lease.owner != within.owner
        )

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

    def bound(
        self, ref: str, key: str, arguments: Dict[str, Any]
    ) -> Tuple[Action, Dict[str, Any]]:
        """An action and its arguments as given (a text may carry its unit),
        parsed by the action."""
        action = self.action(ref, key)
        try:
            return action, action.bind(arguments)
        except ValueError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None

    def current(self, ref: str, key: str) -> Any:
        """The value a quantity has now: the last one set or read, else read."""
        value = self.known.get(ref, key)
        if value is None:
            value = self.read(ref, [key])[key]
        return value

    def act(
        self,
        ref: str,
        key: str,
        arguments: Dict[str, Any],
        origin: str,
        share: bool = False,
        within: Optional[Within] = None,
    ) -> Any:
        """Run an action; its arguments as given (a text may carry its unit) are
        parsed by the action. Returns what the action returns (a trace)."""
        within = within or self.outside
        action, bound = self.bound(ref, key, arguments)
        users = self._users((ref,), share, within) if action.changes else []
        result = self.bench.run(ref, lambda device: action.call(device, **bound))
        if action.changes:
            # What it held may have changed with it (a grid's zero): known
            # again once read, and its guard reads where a change starts from
            self.known.forget((ref,))
            self.bench.run(ref, lambda device: device.forget())
            self.events.publish(ActionDone(ref, key, bound, origin))
            self._note(users, origin, ref, action=key, arguments=bound)
        return result

    def _users(self, refs: Iterable[str], share: bool, within: Within) -> List[Lease]:
        """The other runs using the devices; one sweeping a device the caller
        does not share refuses a change without share."""
        refs = tuple(refs)
        swept = self._swept(refs, within)
        if swept and not share:
            raise LabError(
                ErrorCode.CONFLICT,
                str(LeaseConflict(swept)),
                "call again with share to go on: the measurement notes it",
            )
        return [
            lease
            for ref in refs
            for lease in self.leases.of(ref)
            if lease.owner != within.owner
        ]

    def raw(
        self,
        instrument: str,
        command: str,
        answer: bool,
        origin: str,
        share: bool = False,
        within: Optional[Within] = None,
    ) -> RawReply:
        """Send an instrument a command as typed (answer: read the answer of a
        write too); a query (with ?) changes nothing and reads its answer."""
        within = within or self.outside
        refs = self.bench.raw_parts(instrument)
        query = raw_query(command)
        users = [] if query else self._users(refs, share, within)
        unknown = () if query else tuple(refs)
        sent = f"raw {instrument} {command!r} by {origin}"
        try:
            got = self.bench.raw(instrument, command, answer or query)
        except InstrumentError as e:
            logger.warning(f"{sent} failed: {e}")
            raise
        finally:
            if unknown:  # a write that failed half way changed what it did
                self.known.forget(unknown)
                self.bench.station.forget_setpoints(instrument)
        logger.info(f"{sent}: {got!r}")
        self.events.publish(RawSent(instrument, command, got, unknown, origin))
        if unknown:
            self._note(users, origin, instrument, raw=command, answer=got)
            for ref in unknown:
                self._read_again(ref)
        return RawReply(instrument, command, got, unknown)

    def proposed_raw(
        self, instrument: str, command: str, within: Optional[Within] = None
    ) -> Ask:
        """A raw command as a person reads it before allowing it: a write with
        the warning that nothing checks it, and the sweeps it disturbs."""
        refs = self.bench.raw_parts(instrument)
        if raw_query(command):
            return Ask(f"{instrument} · {RAW_QUERY}", command)
        within = within or self.outside
        sweeps = self._sweeps(refs, within)
        until = (
            f"allowed, measurement #{within.owner} writes to {instrument}"
            " without asking until it ends"
            if within.owner is not None
            else ""
        )
        return Ask(
            f"{instrument} · {RAW_WRITE}",
            command,
            "; ".join(filter(None, (UNCHECKED, until, sweeps))),
            risky=True,
            grave=bool(sweeps),
        )

    def _read_again(self, ref: str) -> None:
        """A device whose values nobody knows, read in its lane: a values
        event, or read_failed."""
        if any(quantity.readable for quantity in self.quantities(ref)):
            self.read_later(ref, None, functools.partial(self._read, ref))

    def _read(self, ref: str, values: Any, error: Optional[BaseException]) -> None:
        if error is None:
            self.events.publish(Values(ref, values))
        else:
            self.events.publish(ReadFailed(ref, str(error)))

    def _note(self, users: List[Lease], origin: str, ref: str, **what: Any) -> None:
        """Who changed what, into the runs using the devices: once a run, as a
        conflict where it sweeps one of them."""
        change = {"at": wall_time(), "by": origin, "device": ref, **what}
        kinds: Dict[int, str] = {}
        for lease in users:
            if kinds.get(lease.owner) != CONFLICTS:
                kinds[lease.owner] = (
                    CONFLICTS if lease.mode == EXCLUSIVE else INTERACTIONS
                )
        for owner, kind in kinds.items():
            self.note(owner, kind, change)
