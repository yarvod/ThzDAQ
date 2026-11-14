"""A script's own measurement as the script writes it: the daemon keeps a
session (thzdaq_api.sessions), a measurement with its file, number and events,
and the script fills it.

    with lab.measurement("pv_fine", devices=[bias, pm], exclusive=[bias]) as m:
        m.plot("scan", x="voltage", y="power")     # a live plot where it is followed
        m.show()                                   # in a window of its own (or "gui")
        m.restore(bias, "voltage_set")             # set back however it ends
        for v in m.sweep("2:3:51", unit="mV"):     # each step looks for a cancel
            bias.voltage_set = v
            m.record("scan", voltage=v, power=pm.power)
            m.progress()

The daemon does what restore and on_exit name when the session ends, however
it ends: at the end of the with block; at a cancel (thzdaq cancel <id>, Stop
in a window), where m.sweep, m.sleep and m.check_cancel raise Cancelled and the
with block ends the session cancelled and goes on after it; at Ctrl+C
(interrupted); or when the script dies and falls silent (interrupted too).

While the with block runs, a thread tells the daemon the script is alive and
hears a cancel at once (keep_session).
"""

import hashlib
import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    Optional,
    Set,
    TypeVar,
    Union,
)

from thzdaq_api.approvals import AnswerApproval, Approval
from thzdaq_api.data import Measured, encode_values
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ApprovalAnswered, ApprovalRequested
from thzdaq_api.measurement_file import (
    CANCELLED,
    COMPLETED,
    FAILED,
    INTERRUPTED,
    RUNNING,
    Column,
    column_for,
)
from thzdaq_api.measurements import PlotInfo, RunInfo
from thzdaq_api.origins import PLOTS
from thzdaq_api.sessions import (
    KEEP_S,
    AdvanceSession,
    CallOnExit,
    EndSession,
    KeepSession,
    LogSession,
    ParseSweep,
    PlotSession,
    RecordSession,
    RestoreOnExit,
    ScriptSource,
    SessionState,
    StartSession,
    Swept,
)
from thzdaq_api.terminal import ALLOW, line, yes

# A device as a session names it: its ref, or the bench's object (lab["ref"])
Device = Union[str, Any]
# A column described by a script: (title, unit), or a Column
Described = Union[Column, tuple]
Typed = Callable[[str, threading.Event], Optional[str]]  # a person's line, or None
# Where a measurement is shown: a window of its plots (plots, True), the main
# window (gui); False: nowhere
Where = Union[bool, str]
Show = Callable[[int, str], None]  # the bench's: a measurement in a window


def place(where: Where) -> str:
    """Where a measurement is shown, by the name of its window."""
    return PLOTS if where is True else str(where)


R = TypeVar("R")


class Cancelled(Exception):
    """The measurement was asked to stop: its session ends cancelled."""


def ref_of(device: Device) -> str:
    return device if isinstance(device, str) else device.ref


def described(key: str, given: Described) -> Column:
    return given if isinstance(given, Column) else Column(key, *given)


def script_source(
    path: Optional[str], workspace: Optional[Path]
) -> Optional[ScriptSource]:
    """The script a process runs, kept with its measurements: its path (within
    the workspace when it is in one), hash and text; None without a file (a
    notebook, the interpreter's prompt)."""
    if path is None:
        return None
    file = Path(path).resolve()
    data = file.read_bytes()
    inside = workspace is not None and file.is_relative_to(workspace)
    shown = file.relative_to(workspace) if inside else file
    text = data.decode("utf-8", errors="replace")
    return ScriptSource(shown.as_posix(), hashlib.sha256(data).hexdigest(), text)


def ending(kind, error, trace) -> tuple:
    """How a with block ended, as its session ends: status, error, traceback."""
    if kind is None:
        return COMPLETED, None, ""
    if issubclass(kind, Cancelled):
        return CANCELLED, None, ""
    if issubclass(kind, KeyboardInterrupt):
        return INTERRUPTED, "stopped by Ctrl+C", ""
    told = "".join(traceback.format_exception(kind, error, trace))
    return FAILED, f"{kind.__name__}: {error}", told


class Session:
    """A script's measurement while its with block runs (lab.measurement)."""

    def __init__(
        self,
        lab,
        start: StartSession,
        approve: Callable[[Callable[[], RunInfo]], RunInfo],
        entered: Callable[[Optional["Session"]], None],
        show: Show,
    ):
        """lab: the bench's Lab; approve(call): the start as a person allows
        it; entered(session): the bench's calls belong to it (None: no more);
        show(id, where): the bench's window of a measurement."""
        self.lab = lab
        self._start = start
        self._approve = approve
        self._entered = entered
        self._show = show
        self._shown: Set[str] = set()  # where it is on screen already
        self.run: Optional[RunInfo] = None  # as it started; as it ended, after
        self.id = 0
        self._columns: Dict[str, Column] = {c.key: c for c in start.columns}
        self._sent: Dict[str, Column] = dict(self._columns)
        self._cancel = threading.Event()
        self._stopped = threading.Event()
        self._status = RUNNING
        self._keeper = threading.Thread(target=self._keep, daemon=True)

    def __enter__(self) -> "Session":
        self.run = self._approve(lambda: self.lab.call(self._start))
        self.id = self.run.id
        self._keeper.name = f"keep session #{self.id}"
        self._keeper.start()
        self._entered(self)
        return self

    def __exit__(self, kind, error, trace) -> bool:
        self._entered(None)
        self._stopped.set()
        status, message, told = ending(kind, error, trace)
        try:
            self.run = self.lab.call(EndSession(self.id, status, message, told))
        finally:
            self._keeper.join()
        return kind is not None and issubclass(kind, Cancelled)

    def _keep(self) -> None:
        while not self._stopped.is_set() and self._status == RUNNING:
            try:
                self._heard(self.lab.call(KeepSession(id=self.id, wait=KEEP_S)))
            except LabError:
                self._cancel.set()  # the daemon is gone: stop at the next check
                return

    def _heard(self, state: SessionState) -> None:
        self._status = state.status
        if state.cancelled or state.status != RUNNING:
            self._cancel.set()

    # Cancel
    @property
    def cancelled(self) -> bool:
        """It was asked to stop (or the daemon ended it)."""
        return self._cancel.is_set()

    def check_cancel(self) -> None:
        if self._cancel.is_set():
            raise Cancelled(f"measurement #{self.id} was asked to stop")

    def sleep(self, seconds: float) -> None:
        """Sleep that ends at once with Cancelled when a cancel comes."""
        self._cancel.wait(max(0.0, seconds))
        self.check_cancel()

    def sweep(
        self, values: Union[str, Swept, Iterable[float]], unit: str = ""
    ) -> Iterator[Measured]:
        """The values of a sweep, typed as people type it ("2:3:51" with unit
        "mV"), declared (value(...) of a sweep) or given (SI); each in SI
        units with its unit, after a look for a cancel."""
        if isinstance(values, Swept):
            values, unit = values.typed(), values.unit
        if isinstance(values, str):
            parsed = self.lab.call(ParseSweep(text=values, unit=unit))
            values, unit = parsed.values, parsed.unit
        for value in values:
            self.check_cancel()
            yield Measured(value, unit)

    # Data
    def columns(self, **given: Described) -> None:
        """Titles and units of record keys, (title, unit) or a Column: over what
        a value knows of itself (a device's reading), and for computed values."""
        for key, column in given.items():
            self._columns[key] = described(key, column)

    def record(self, table: str, /, **values: Any) -> None:
        """A record of a table: each key a column, values in SI units (a
        reading, a swept value or a number of the script's)."""
        fresh = []
        for key, value in values.items():
            column = self._column(key, value)
            if column is not None and self._sent.get(key) != column:
                fresh.append(column)
                self._sent[key] = column
        row = encode_values(values)
        self._heard(
            self.lab.call(
                RecordSession(
                    id=self.id, table=table, rows=(row,), columns=tuple(fresh)
                )
            )
        )

    def _column(self, key: str, value: Any) -> Optional[Column]:
        if key in self._columns:
            return self._columns[key]
        if isinstance(value, Measured):
            title = value.title or column_for(key).title
            return Column(key, title, value.unit, value.source)
        return None

    def progress(self, done: Optional[int] = None, total: Optional[int] = None) -> None:
        """Steps done (one more when not given) of total."""
        self._heard(self.lab.call(AdvanceSession(id=self.id, done=done, total=total)))

    def log(self, message: str) -> None:
        self.lab.call(LogSession(id=self.id, message=message))

    def plot(
        self,
        table: str,
        x: str,
        y: str,
        group_by: Iterable[str] = (),
        title: str = "",
        kind: str = "line",
        z: Optional[str] = None,
        show: Where = False,
        into: Optional[str] = None,
    ) -> PlotInfo:
        """A live plot of a table where the measurement is followed, kept in
        its file for Data to draw again; curves by the values of group_by.
        into: a graph of the window (its title) it is drawn into, when there
        is one of the same units; show: the measurement on screen at once
        (see show)."""
        plot = PlotInfo(
            key="", title=title, table=table, x=x, y=y,
            group_by=tuple(group_by), kind=kind, z=z, into=into,
        )  # fmt: skip
        drawn = self.lab.call(PlotSession(id=self.id, plot=plot))
        if show:
            self.show(show)
        return drawn

    def show(self, where: Where = PLOTS) -> None:
        """Its plots on screen as it runs, once for each place: in a window
        of their own (plots, True), or in the main window (gui), opened in
        the script's workspace unless one is open already."""
        shown = place(where)
        if shown not in self._shown:
            self._show(self.id, shown)
            self._shown.add(shown)

    # What the daemon does at the end
    def restore(self, device: Device, key: str) -> Any:
        """Set the quantity back to its value now when the session ends,
        however it ends; returns that value."""
        kept = self.lab.call(RestoreOnExit(id=self.id, ref=ref_of(device), key=key))
        return kept.value

    def on_exit(self, device: Device, action: str, **arguments: Any) -> None:
        """Make the device do an action when the session ends (to_cold)."""
        self.lab.call(
            CallOnExit(
                id=self.id, ref=ref_of(device), action=action, arguments=arguments
            )
        )


class AnsweredHere:
    """While a call waits for a person, the person at this terminal is asked
    too; the first answer, here or in a window, counts."""

    def __init__(self, person, origin: str, typed: Typed = line):
        """person: the bench as the person here answers in it (cli:answers);
        origin: whose requests are asked here (the script's)."""
        self.person = person
        self.origin = origin
        self.typed = typed

    def __call__(self, call: Callable[[], R]) -> R:
        asked: "queue.Queue[Optional[Approval]]" = queue.Queue()
        gone: Dict[int, threading.Event] = {}

        def heard(event) -> None:
            body = event.body
            if (
                isinstance(body, ApprovalRequested)
                and body.approval.origin == self.origin
            ):
                gone.setdefault(body.approval.id, threading.Event())
                asked.put(body.approval)
            elif isinstance(body, ApprovalAnswered):
                gone.setdefault(body.id, threading.Event()).set()

        outcome: Dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["result"] = call()
            except LabError as e:  # handed to the thread that waits for it
                outcome["error"] = e
            finally:
                for event in list(gone.values()):
                    event.set()
                asked.put(None)

        stop = self.person.subscribe(heard)
        try:
            threading.Thread(target=run, daemon=True).start()
            for approval in iter(asked.get, None):
                self._ask(approval, gone[approval.id])
        finally:
            stop()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["result"]

    def _ask(self, approval: Approval, gone: threading.Event) -> None:
        print(f"\n{approval.title}: {approval.text}", file=sys.stderr)
        if approval.warning:
            print(f"warning: {approval.warning}", file=sys.stderr)
        typed = self.typed(ALLOW, gone)
        if typed is None:
            return  # answered in a window
        confirm = ""
        allowed = yes(typed)
        if allowed and approval.confirm:
            confirm = self.typed(f"type {approval.confirm} to allow it: ", gone) or ""
        try:
            self.person.call(
                AnswerApproval(id=approval.id, allowed=allowed, confirm=confirm)
            )
        except LabError as e:
            if e.code != ErrorCode.NOT_FOUND:
                raise
            print("answered elsewhere first", file=sys.stderr)
