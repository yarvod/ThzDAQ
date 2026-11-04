"""Script sessions: a script's own measurement, kept by the daemon while the
script drives it from outside (thzdaq_api.sessions, lab.measurement).

A session is a measurement of Runs whose procedure (ScriptSession) waits for
the script: its records, progress and log come in calls, and so does its end.
A cancel (thzdaq cancel, Stop in a window) reaches the script in keep_session,
and the script ends the session cancelled; one that does not within CANCEL_S
is ended by the daemon. A script silent longer than its session allows (it
died, its terminal closed) ends it interrupted. However it ends, the runner
restores what the script asked to (restore_on_exit, call_on_exit) through
DeviceAccess: in the instrument's lane, through the guarded device, in steps
to the end.

A device the script reads or sets without naming it at the start joins the
session then (a lease, a place among its devices); the log says to name it.
"""

import threading
import time
from dataclasses import replace
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

import msgspec
from thzdaq_api.data import decode_values
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.leases import EXCLUSIVE, READ, SHARED
from thzdaq_api.measurement_file import (
    CANCELLED,
    COMPLETED,
    FAILED,
    INTERRUPTED,
    RUNNING,
    Column,
    DeviceUse,
    column_for,
)
from thzdaq_api.measurements import PlotInfo, RunInfo
from thzdaq_api.origins import script
from thzdaq_api.sessions import ScriptSource, SessionState, StartSession, SweepValues
from thzdaq_instruments.units import unit_scale

from thzdaq_core.application.approvals import Ask
from thzdaq_core.application.devices import DeviceAccess, Within
from thzdaq_core.application.runner import Cancelled, Context, Failed, Interrupted
from thzdaq_core.application.runs import STRENGTH, Runs
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.leases import Lease, LeaseConflict
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.parameters import SweepParameter

TICK_S = 0.1  # how often a waiting session looks at the cancel and the clock
CANCEL_S = 3.0  # a cancelled script has this long to end its session itself
KEEP_MAX_S = 5.0  # the longest keep_session waits for a cancel
END_S = 60.0  # how long end_session waits for the restores to finish
KEPT = 100  # ended sessions remembered for the script's late calls
HINT = "name it in devices= of lab.measurement"


class ScriptSession(Procedure):
    """The procedure of a script's session: the runner runs it while the
    script drives the measurement through the daemon's calls."""

    def __init__(
        self,
        title: str,
        origin: str,
        modes: Mapping[str, str],
        shared: Iterable[str] = (),
        parameters: Optional[Mapping[str, Any]] = None,
        columns: Iterable[Column] = (),
        total: Optional[int] = None,
        silent: float = 10.0,
        source: Optional[ScriptSource] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name = script(title)
        self.title = title
        self.origin = origin
        self.modes = dict(modes)  # device -> how the session uses it
        self.shared = set(shared)
        self.given = dict(parameters or {})
        self.columns = {column.key: column for column in columns}
        self.total = total
        self.silent = silent
        self.source = source
        self.clock = clock
        self.owner: Optional[int] = None  # its number, once it runs
        self._ctx: Optional[Context] = None
        self._changed = threading.Condition()
        self._open = True  # until it ends: the script's calls go on
        self._outcome: Optional[BaseException] = None  # how it ends; None: completed
        self._ending = False
        self.status = RUNNING  # how it ends, once it does
        self._heard = clock()
        self._keeping = 0  # keep_session calls waiting now: the script is there
        self._cancelled_at: Optional[float] = None

    # A procedure as the runner runs it
    def slots(self):
        return {ref: object for ref in self.modes}

    def slot_mode(self, slot: str) -> str:
        return self.modes[slot]

    def to_json(self) -> Dict[str, Any]:
        return dict(self.given)

    def estimate_steps(self) -> Optional[int]:
        return self.total

    def run(self, ctx: Context) -> None:
        with self._changed:
            self._ctx = ctx
            self.owner = ctx.measurement.id
            if self.source is not None:
                ctx.measurement.metadata["script"] = msgspec.to_builtins(self.source)
            self._heard = self.clock()
            self._changed.notify_all()
            while not self._ending:
                self._changed.wait(TICK_S)
                self._look(ctx)
            self._open = False
            self._changed.notify_all()
        if self._outcome is not None:
            raise self._outcome

    def _look(self, ctx: Context) -> None:
        """A cancel the script is told of, and how long ago it was heard."""
        now = self.clock()
        if self._ending:
            return
        if ctx.cancelled and self._cancelled_at is None:
            self._cancelled_at = now
            self._changed.notify_all()  # keep_session answers at once
        if self._cancelled_at is not None and now - self._cancelled_at > CANCEL_S:
            self._end(CANCELLED, Cancelled())
        elif not self._keeping and now - self._heard > self.silent:
            silent = Interrupted(f"the script was silent for {self.silent:g} s")
            self._end(INTERRUPTED, silent)

    def _end(self, status: str, outcome: Optional[BaseException]) -> None:
        self.status, self._outcome, self._ending = status, outcome, True
        self._changed.notify_all()

    # What the script does, each under the lock: the runner's thread waits
    def _live(self) -> Context:
        """Its context, the script heard from now; LabError once it ended."""
        self._changed.wait_for(lambda: self._ctx is not None)
        if not self._open or self._ending:
            raise LabError(
                ErrorCode.NOT_ALLOWED,
                f"measurement #{self.owner} ({self.title}) has ended",
                "start another session",
            )
        self._heard = self.clock()
        return self._ctx

    @property
    def running(self) -> bool:
        with self._changed:
            return self._open and not self._ending

    @property
    def cancelled(self) -> bool:
        return self._cancelled_at is not None

    def state(self) -> SessionState:
        with self._changed:
            return SessionState(self.owner or 0, self.status, self.cancelled)

    def alive(self) -> None:
        """The script is heard; LabError once the session ended."""
        with self._changed:
            self._live()

    def keep(self, wait: float) -> None:
        """The script is alive; returns at once when a cancel comes or the
        session ends, else after wait."""
        with self._changed:
            if self._ending or not self._open:
                return
            self._live()
            told = self.cancelled
            self._keeping += 1
            self._changed.wait_for(
                lambda: self._ending or self.cancelled != told, min(wait, KEEP_MAX_S)
            )
            self._keeping -= 1
            self._heard = self.clock()

    def record(
        self, table: str, rows: Iterable[Dict[str, Any]], columns: Iterable[Column]
    ) -> None:
        with self._changed:
            ctx = self._live()
            for column in columns:
                self.columns[column.key] = column
                for found in ctx.measurement.tables.values():
                    found.describe(column)
            for row in rows:
                ctx.record(table, **decode_values(row))
            ctx.flush()  # a call of records is a batch already

    def advance(self, done: Optional[int], total: Optional[int]) -> None:
        with self._changed:
            self._live().progress(done, total)

    def log(self, message: str) -> None:
        with self._changed:
            self._live().log(message)

    def plot(self, plot: PlotInfo) -> PlotInfo:
        """The plot with what was left empty: labels from the columns, a
        title and a key of its own."""
        with self._changed:
            ctx = self._live()
            x, y = (column_for(key, self.columns) for key in (plot.x, plot.y))
            drawn = msgspec.structs.replace(
                plot,
                key=plot.key or f"{self.name}.{plot.table}.{plot.x}.{plot.y}",
                title=plot.title or f"{y.title} – {x.title} ({self.title})",
                x_label=plot.x_label or x.label,
                y_label=plot.y_label or y.label,
            )
            ctx.plot(drawn)
            return drawn

    def on_exit(self, callback: Callable[[], None]) -> None:
        with self._changed:
            self._live().on_exit(callback)

    def end(self, status: str, outcome: Optional[BaseException]) -> None:
        """As the script ended it, but cancelled when it was asked to stop and
        went on to its end; nothing when it has ended already."""
        with self._changed:
            if not self._open or self._ending:
                return
            if status == COMPLETED and self.cancelled:
                status, outcome = CANCELLED, Cancelled()
            self._end(status, outcome)

    # The devices it holds, and its calls as Within
    def holds(self, ref: str, mode: str) -> bool:
        """It uses the device at least so (a set needs shared, a read read)."""
        held = self.modes.get(ref)
        return held is not None and STRENGTH.index(held) >= STRENGTH.index(mode)

    def grants(self, ref: str) -> bool:
        """A person allowed it to set the device when it started (or later)."""
        return self.holds(ref, SHARED)

    def joined(self, ref: str, mode: str, use: DeviceUse) -> None:
        """A device it had not named: in the measurement's devices, and a hint."""
        with self._changed:
            ctx = self._live()
            new = ref not in self.modes
            self.modes[ref] = max(self.modes.get(ref, READ), mode, key=STRENGTH.index)
            ctx.measurement.devices[ref] = use
            if new:
                ctx.log(f"{ref} joined as {mode}: {HINT}")

    def shares(self, ref: str) -> bool:
        return ref in self.shared

    def tell(self, ref: str, key: str, value: Any, before: Any, origin: str) -> None:
        """A set of the session goes with its run's sets."""
        with self._changed:
            self._ctx.told(ref, key, value)


ENDINGS: Dict[str, Callable[[str, str], Optional[BaseException]]] = {
    COMPLETED: lambda error, traceback: None,
    CANCELLED: lambda error, traceback: Cancelled(),
    INTERRUPTED: lambda error, traceback: Interrupted(error or "stopped by hand"),
    FAILED: lambda error, traceback: Failed(error or "the script failed", traceback),
}


def modes_of(args: StartSession) -> Dict[str, str]:
    """device -> how a session uses it: exclusive what it sweeps, else shared."""
    modes = {ref: SHARED for ref in args.devices}
    modes.update({ref: EXCLUSIVE for ref in args.exclusive})
    return modes


def sweep_values(text: str, unit: str) -> SweepValues:
    """A sweep typed start:stop:points in a unit, as SI values."""
    si, factor = unit_scale(unit)
    parameter = SweepParameter(
        "Sweep", unit=si, display_unit=unit, display_scale=factor
    )
    try:
        return SweepValues(tuple(parameter.parse(text).values()), si)
    except ProcedureError as e:
        raise LabError(ErrorCode.INVALID_ARGUMENTS, f"{text!r}: {e}") from None


class Sessions:
    def __init__(self, runs: Runs, devices: DeviceAccess):
        self.runs = runs
        self.devices = devices
        self._sessions: Dict[int, ScriptSession] = {}
        self._lock = threading.Lock()

    def start(self, args: StartSession, origin: str) -> RunInfo:
        session = self._session(args, origin)
        info = self.runs.start(
            session,
            {ref: ref for ref in session.modes},
            args.comment,
            origin,
            workspace=args.workspace,
            shares=args.share,
        )
        with self._lock:
            self._sessions[info.id] = session
            ended = [i for i, s in self._sessions.items() if not s.running]
            for old in ended[: max(0, len(ended) - KEPT)]:
                del self._sessions[old]
        return info

    def _session(self, args: StartSession, origin: str) -> ScriptSession:
        return ScriptSession(
            args.title, origin, modes_of(args), args.share, args.parameters,
            args.columns, args.total, args.silent, args.script,
        )  # fmt: skip

    def approval(self, args: StartSession) -> Ask:
        """The session a start would make, checked as a dry run; a conflict
        is the person's to allow (both measurements note it)."""
        planned = self.runs.start(
            self._session(args, ""), {ref: ref for ref in modes_of(args)},
            args.comment, "", workspace=args.workspace, dry_run=True, share=True,
        )  # fmt: skip
        clashes = self.clashes(args)
        uses = ", ".join(f"{ref} {mode}" for ref, mode in modes_of(args).items())
        given = ", ".join(f"{key} {value}" for key, value in args.parameters.items())
        steps = f"{planned.total} steps" if planned.total else ""
        text = "; ".join(filter(None, (uses, given, steps, args.comment)))
        warning = f"{LeaseConflict(clashes)}: both note it" if clashes else ""
        return Ask(
            f"Start script {args.title}",
            text or "it names no device yet",
            warning,
            risky=bool(warning),
            grave=bool(warning),
        )

    def clashes(self, args: StartSession) -> Tuple[Lease, ...]:
        """Sweeps of other measurements the session would conflict with, but
        on the devices it shares."""
        found = self.runs.leases.clashes(0, modes_of(args))
        return tuple(lease for lease in found if lease.device not in args.share)

    def _found(self, id: int) -> ScriptSession:
        with self._lock:
            session = self._sessions.get(id)
        if session is None:
            raise LabError(ErrorCode.NOT_FOUND, f"No script session {id}")
        return session

    def of(self, id: int, origin: str) -> ScriptSession:
        """The session, when the caller is the script that started it."""
        session = self._found(id)
        if session.origin != origin:
            raise LabError(
                ErrorCode.DENIED,
                f"measurement #{id} is the session of {session.origin}",
                "only its script records into it; cancel_measurement stops it",
            )
        return session

    def found(self, id: Optional[int]) -> Within:
        """Where a call is made, as a person reads it before allowing it."""
        return self.devices.outside if id is None else self._found(id)

    def owns(self, id: int, origin: str) -> bool:
        """The caller's own session, running."""
        with self._lock:
            session = self._sessions.get(id)
        return session is not None and session.origin == origin and session.running

    def grants(self, id: Optional[int], origin: str, ref: str) -> bool:
        """A set of the device belongs to the caller's session, which a person
        allowed to set it."""
        return id is not None and self.owns(id, origin) and self._found(id).grants(ref)

    def within(self, id: Optional[int], origin: str, ref: str, mode: str) -> Within:
        """Where a call on a device is made; a device the session did not hold
        so joins it. LabError once the session ended."""
        if id is None:
            return self.devices.outside
        session = self.of(id, origin)
        session.alive()
        if not session.holds(ref, mode):
            self.runs.join(id, ref, mode, session.shares(ref))
            session.joined(ref, mode, self.devices.bench.station.device_use(ref))
        return session

    def keep(self, id: int, origin: str, wait: float) -> SessionState:
        session = self.of(id, origin)
        session.keep(wait)
        return session.state()

    def record(
        self,
        id: int,
        origin: str,
        table: str,
        rows: Iterable[Dict[str, Any]],
        columns: Iterable[Column],
    ) -> SessionState:
        session = self.of(id, origin)
        session.record(table, rows, columns)
        return session.state()

    def advance(
        self, id: int, origin: str, done: Optional[int], total: Optional[int]
    ) -> SessionState:
        session = self.of(id, origin)
        session.advance(done, total)
        return session.state()

    def log(self, id: int, origin: str, message: str) -> None:
        self.of(id, origin).log(message)

    def plot(self, id: int, origin: str, plot: PlotInfo) -> PlotInfo:
        return self.of(id, origin).plot(plot)

    def restore(self, id: int, origin: str, ref: str, key: str) -> Any:
        """At the end, the quantity back to the value it has now (returned)."""
        session = self.within(id, origin, ref, SHARED)
        _, value = self.devices.checked(ref, key, self.devices.current(ref, key))
        session.on_exit(
            lambda: self.devices.write(ref, key, value, origin, within=session)
        )
        return value

    def restore_ask(self, id: int, ref: str, key: str) -> Ask:
        """What a person reads before the session may restore a device."""
        quantity = self.devices.quantity(ref, key)
        self.found(id)  # an unknown session is refused before anybody is asked
        return Ask(
            f"{ref} · {quantity.title}",
            f"back to its value now when measurement #{id} ends",
            quantity.danger,
            ref if quantity.danger else "",
            risky=bool(quantity.danger),
            grave=bool(quantity.danger),
        )

    def on_exit(
        self, id: int, origin: str, ref: str, action: str, arguments: Mapping[str, Any]
    ) -> None:
        """At the end, the device does the action."""
        found, _ = self.devices.bound(ref, action, dict(arguments))
        mode = SHARED if found.changes else READ
        session = self.within(id, origin, ref, mode)
        session.on_exit(
            lambda: self.devices.act(
                ref, action, dict(arguments), origin, within=session
            )
        )

    def on_exit_ask(
        self, id: int, ref: str, action: str, arguments: Mapping[str, Any]
    ) -> Ask:
        ask = self.devices.proposed_action(ref, action, dict(arguments), self.found(id))
        return replace(ask, text=f"{ask.text}; when measurement #{id} ends")

    def end(
        self, id: int, origin: str, status: str, error: Optional[str], traceback: str
    ) -> RunInfo:
        """As the script ended it; returns once the daemon restored what it
        was asked to and the measurement ended."""
        if status not in ENDINGS:
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"A session ends {', '.join(ENDINGS)}, not {status!r}",
            )
        self.of(id, origin).end(status, ENDINGS[status](error, traceback))
        return self.runs.wait(id, END_S)
