"""The bench as a client sees it: operations called by their arguments, events
heard as they happen (Lab); and as a script uses it (Bench, connect).

RemoteLab calls the daemon; LocalLab (thzdaq-core) calls its use cases in the
same process. Both raise LabError when an operation fails.

A script's bench has the commands of the thzdaq command line as functions,
each one operation, and its devices as objects whose attributes are their
quantities and whose methods are their actions:

    from thzdaq import connect

    lab = connect()                      # finds the daemon, or starts it
    bias, pm = lab["sis_bias_1"], lab["power_meter_1"]
    bias.voltage_set = "2.3mV"           # = lab.set(...) = thzdaq set ...
    bias.read()                          # = thzdaq read sis_bias_1: SI values
    pm.power                             # one quantity
    lab["chopper_1"].to_hot()            # an action
    lab.raw("signal_generator_1", "*IDN?")   # a raw command, as typed
    run = lab.run("sis.iv_curve", bias=bias, voltage="0:7:351")
    run.show()                           # its plots in a window of their own
    run.wait()
    iv = run.table("iv")

Readings are Measured: floats in SI units that know their unit, title and
device. Values to set are SI numbers or texts with their unit.
"""

import os
import sys
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    Tuple,
    TypeVar,
    Union,
)

from thzdaq_api import host, windows
from thzdaq_api.data import Measured, decode_values
from thzdaq_api.devices import (
    CallAction,
    DescribeDevice,
    DeviceDescription,
    DeviceInfo,
    ListDevices,
    RawCommand,
    ReadDevice,
    SetQuantity,
    Value,
    shown,
)
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import Event
from thzdaq_api.measurement_file import RUNNING, Measurement, Table, read_measurement
from thzdaq_api.measurements import (
    CancelMeasurement,
    DescribeProcedure,
    GetRunSnapshot,
    ListRuns,
    RunInfo,
    StartMeasurement,
    WaitMeasurement,
    fill_slots,
)
from thzdaq_api.operation import Operation
from thzdaq_api.origins import ANSWERING_CLI, CLI, GUI, PLOTS, SCRIPT_CLIENT, script
from thzdaq_api.procedures import entry
from thzdaq_api.remote import RemoteLab
from thzdaq_api.script import (
    AnsweredHere,
    Described,
    Session,
    Where,
    described,
    place,
    ref_of,
    script_source,
)
from thzdaq_api.scripts import SCRIPT_ID_ENV, SIMULATE_ENV
from thzdaq_api.sessions import SILENT_S, StartSession
from thzdaq_api.terminal import person_here
from thzdaq_api.workspace import chosen, expected_profile, profile_warning

R = TypeVar("R")
WAIT_S = 1.0  # how often wait() tells the progress


class Lab(Protocol):
    origin: str  # who calls (gui, cli, mcp:<name>); the runs it starts carry it

    def call(self, operation: Operation[R]) -> R:
        ...

    def subscribe(
        self, listener: Callable[[Event], None], since: Optional[int] = None
    ) -> Callable[[], None]:
        """Hear every event after `since` (a snapshot's seq; None: from now);
        returns what stops it. The listener runs in the lab's thread: it hands
        the event on (a Qt signal, a queue) and returns."""
        ...


class Readout(dict):
    """What a device read, by quantity: readout["voltage"] or readout.voltage."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(
                f"nothing read as {key!r}: {', '.join(self)}"
            ) from None


def plain(value: Any) -> Any:
    """A value as it travels: a Measured as a float."""
    return float(value) if isinstance(value, float) else value


class Device:
    """A device of the bench as an object: its quantities are attributes (read
    when looked at, set when assigned; device["key"] too) and its actions
    methods, as describe_device lists them. It only calls the bench's functions."""

    def __init__(self, bench: "Bench", ref: str):
        object.__setattr__(self, "bench", bench)
        object.__setattr__(self, "ref", ref)

    def describe(self) -> DeviceDescription:
        return self.bench.describe(self.ref)

    def read(self, *keys: str, display: bool = False) -> Readout:
        return self.bench.read(self.ref, *keys, display=display)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        found = self.describe()
        if any(q.key == name for q in found.quantities):
            return self[name]
        if any(a.key == name for a in found.actions):
            return lambda **arguments: self.bench.call(self.ref, name, **arguments)
        raise AttributeError(f"{self.ref} has no quantity or action {name!r}")

    def __setattr__(self, name: str, value: Any) -> None:
        self.bench.set(self.ref, name, value)

    def __getitem__(self, key: str) -> Any:
        return self.read(key)[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.bench.set(self.ref, key, value)

    def __dir__(self) -> Iterable[str]:
        found = self.describe()
        return [q.key for q in found.quantities] + [a.key for a in found.actions]

    def __repr__(self) -> str:
        return f"<device {self.ref}>"


class Run:
    """A measurement started in the daemon, followed from here."""

    def __init__(self, bench: "Bench", info: RunInfo):
        self.bench = bench
        self.info = info
        self.id = info.id

    def wait(self, progress: bool = True) -> RunInfo:
        """Until it ends; its progress on stderr."""
        self.info = self.bench.wait(self.id, progress)
        return self.info

    def cancel(self) -> RunInfo:
        self.info = self.bench.cancel(self.id)
        return self.info

    def show(self, where: Where = PLOTS) -> None:
        """Its plots on screen as it runs: in a window of their own (plots),
        or in the main window (gui); see Bench.show."""
        self.bench.show(self.id, where)

    def measurement(self) -> Measurement:
        """What it holds: its file once it ended, its records so far while it
        runs."""
        self.info = self.bench.lab.call(WaitMeasurement(id=self.id, timeout=0))
        if self.info.status != RUNNING:
            return read_measurement(self.info.path)
        snapshot = self.bench.lab.call(GetRunSnapshot(id=self.id))
        found = Measurement(self.info.procedure, self.info.title, self.id)
        for table, rows in snapshot.rows.items():
            for row in rows:
                found.append(table, decode_values(row))
        return found

    def table(self, name: str) -> Table:
        """A table of its records: columns by key (iv["voltage"]), in SI units."""
        tables = self.measurement().tables
        if name not in tables:
            raise LabError(
                ErrorCode.NOT_FOUND,
                f"#{self.id} has no table {name!r}",
                f"it has: {', '.join(tables) or 'none yet'}",
            )
        return tables[name]

    def __repr__(self) -> str:
        return f"<run #{self.id} {self.info.title}: {self.info.status}>"


class Bench:
    """The bench as a script uses it: the CLI's commands as functions, its
    devices as objects (bench["sis_bias_1"]), its own measurements as sessions
    (bench.measurement)."""

    def __init__(
        self,
        lab: Lab,
        workspace: Union[str, Path, None] = None,
        script=None,
        approve: Optional[Callable[[Callable[[], Any]], Any]] = None,
        simulate: bool = False,
    ):
        """workspace: the folder whose data/ gets its measurements (None: the
        program's, where the daemon writes); script: the ScriptSource its
        sessions keep; approve: how a call a person allows is made (asked in
        this terminal too); simulate: the lab is the simulator's daemon,
        the windows it opens work with it too."""
        self.lab = lab
        self.workspace = Path(workspace).resolve() if workspace else None
        self.script = script
        self.approve = approve or (lambda call: call())
        self.simulate = simulate
        self.session: Optional[Session] = None  # the with block running now
        self._described: Dict[str, DeviceDescription] = {}

    @property
    def origin(self) -> str:
        return self.lab.origin

    def _folder(self) -> Optional[str]:
        """The workspace as operations name it."""
        return str(self.workspace) if self.workspace else None

    def _session_id(self) -> Optional[int]:
        return self.session.id if self.session is not None else None

    def _entered(self, session: Optional[Session]) -> None:
        self.session = session

    # Devices
    def __getitem__(self, ref: str) -> Device:
        return Device(self, ref)

    def devices(self) -> Tuple[DeviceInfo, ...]:
        return self.lab.call(ListDevices())

    def describe(self, ref: str) -> DeviceDescription:
        if ref not in self._described:
            self._described[ref] = self.lab.call(DescribeDevice(ref=ref))
        return self._described[ref]

    def read(self, ref: str, *keys: str, display: bool = False) -> Readout:
        """Every readable quantity, or the keys: SI numbers that know their
        unit (Measured); display: texts in the units people read."""
        values = self.lab.call(
            ReadDevice(ref=ref, keys=keys or None, session=self._session_id())
        ).values
        quantities = {q.key: q for q in self.describe(ref).quantities}
        return Readout(
            (key, self._value(ref, quantities[key], value, display))
            for key, value in values.items()
        )

    @staticmethod
    def _value(ref: str, quantity, value: Value, display: bool) -> Any:
        if display:
            return shown(value, quantity.unit, quantity.prefixes)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return Measured(
                value, quantity.unit, quantity.title, entry(ref, quantity.key)
            )
        return value

    def set(self, ref: str, key: str, value: Any, share: bool = False) -> Value:
        """An SI number or a text with its unit ("2.3mV"); returns what was set."""
        done = self.lab.call(
            SetQuantity(
                ref=ref, key=key, value=plain(value), share=share,
                session=self._session_id(),
            )
        )  # fmt: skip
        return done.value

    def call(
        self, ref: str, action: str, /, share: bool = False, **arguments: Any
    ) -> Any:
        """A device's action; arguments as SI numbers or texts with units."""
        done = self.lab.call(
            CallAction(
                ref=ref, action=action,
                arguments={k: plain(v) for k, v in arguments.items()},
                share=share, session=self._session_id(),
            )
        )  # fmt: skip
        return done.result

    def raw(
        self, instrument: str, command: str, answer: bool = False, share: bool = False
    ) -> Optional[str]:
        """Send an instrument (its id in the profile) a command as typed, for
        what its driver does not wrap yet; returns its answer: of a query
        (with ?), or of a write with answer. No limit checks a write: it waits
        for a person, unless the script was started with --allow
        raw:<instrument>. Put a command used often into the driver."""
        command = RawCommand(
            instrument=instrument, command=command, answer=answer, share=share,
            session=self._session_id(),
        )  # fmt: skip
        if command.query:
            return self.lab.call(command).answer
        return self.approve(lambda: self.lab.call(command)).answer

    # Procedures
    def start(
        self,
        procedure: str,
        devices: Optional[Mapping[str, Any]] = None,
        comment: str = "",
        share: bool = False,
        **parameters: Any,
    ) -> RunInfo:
        """Start a procedure (thzdaq run --detach). A device given as a
        parameter (bias=bias) fills its slot, a text is typed as describe
        shows it ("0:7:351" in mV), a number is SI; a slot left out takes the
        only device that suits it."""
        given = {slot: ref_of(d) for slot, d in (devices or {}).items()}
        given.update(
            (name, value.ref)
            for name, value in parameters.items()
            if isinstance(value, Device)
        )
        typed = {k: v for k, v in parameters.items() if isinstance(v, str)}
        values = {
            k: plain(v)
            for k, v in parameters.items()
            if not isinstance(v, (str, Device))
        }
        info = self.lab.call(
            DescribeProcedure(procedure=procedure, parameters=values, typed=typed)
        )
        chosen, choices = fill_slots(info.slots, self.devices(), given)
        if choices:
            slot, refs = next(iter(choices.items()))
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"{slot}: one of {', '.join(refs)}",
                f"name it: {slot}=lab[...]",
            )
        return self.lab.call(
            StartMeasurement(
                procedure=procedure, parameters=values, typed=typed,
                devices=chosen, comment=comment, share=share,
                workspace=self._folder(),
            )
        )  # fmt: skip

    def run(
        self,
        procedure: str,
        devices: Optional[Mapping[str, Any]] = None,
        comment: str = "",
        share: bool = False,
        **parameters: Any,
    ) -> Run:
        """Start a procedure and follow it: run.wait(), run.table("iv")."""
        return Run(self, self.start(procedure, devices, comment, share, **parameters))

    def status(self) -> Tuple[RunInfo, ...]:
        """The measurements running now."""
        return tuple(run for run in self.measurements() if run.status == RUNNING)

    def measurements(self) -> Tuple[RunInfo, ...]:
        """The daemon's measurements: running and lately ended."""
        return self.lab.call(ListRuns())

    def cancel(self, id: int) -> RunInfo:
        return self.lab.call(CancelMeasurement(id=id))

    # Windows: each a program of its own, apart from this script
    def plot(
        self,
        measurement: Union[int, str, Path],
        table: Optional[str] = None,
        x: Optional[str] = None,
        y: Optional[str] = None,
        group_by: Iterable[str] = (),
    ) -> None:
        """The plots of a measurement in a window of their own (thzdaq plot):
        one of the daemon by its number, drawn as it runs, or a file. With
        table, x and y the window draws that plot instead (curves by the
        values of group_by). The script does not wait for the window."""
        which = measurement if isinstance(measurement, int) else str(measurement)
        own = windows.OwnPlot.asked(table, x, y, tuple(group_by))
        windows.open_plots(self.lab.call, which, self.simulate, own)

    def show(self, id: int, where: Where = PLOTS) -> None:
        """A measurement of the daemon on screen as it runs: in a window of
        its own with only its plots (plots, or True), or in the main window
        (gui), opened in this workspace unless one is open already."""
        shows = {PLOTS: self.plot, GUI: self._main_window}
        if place(where) not in shows:
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"No window {where!r} to show #{id} in",
                f"one of: {', '.join(shows)}",
            )
        shows[place(where)](id)

    def _main_window(self, id: int) -> None:
        """A main window draws every measurement running: one is opened
        when none listens."""
        if not windows.window_open(self.lab.call):
            host.start_apart(windows.gui_command(self.workspace, self.simulate))

    def wait(self, id: int, progress: bool = False) -> RunInfo:
        """Until the measurement ends; progress: told on stderr as it goes."""
        info = self.lab.call(WaitMeasurement(id=id, timeout=0))
        while info.status == RUNNING:
            if progress:
                done = f"{info.done}/{info.total}" if info.total else f"{info.done}"
                print(f"\r#{id} {info.title}: {done}", end="", file=sys.stderr)
            info = self.lab.call(WaitMeasurement(id=id, timeout=WAIT_S))
        if progress:
            print(f"\r#{id} {info.title}: {info.status}", file=sys.stderr)
        return info

    # A script's own measurement
    def measurement(
        self,
        title: str,
        devices: Iterable[Any] = (),
        exclusive: Iterable[Any] = (),
        share: Iterable[Any] = (),
        parameters: Optional[Mapping[str, Any]] = None,
        comment: str = "",
        columns: Optional[Mapping[str, Described]] = None,
        total: Optional[int] = None,
        silent: float = SILENT_S,
    ) -> Session:
        """A measurement of this script (with ... as m): devices it uses,
        those it sweeps (exclusive), those it shares while another measurement
        sweeps them (share); columns: (title, unit) of record keys."""
        start = StartSession(
            title=title,
            devices=tuple(ref_of(d) for d in devices),
            exclusive=tuple(ref_of(d) for d in exclusive),
            share=tuple(ref_of(d) for d in share),
            parameters=dict(parameters or {}),
            comment=comment,
            workspace=self._folder(),
            script=self.script,
            columns=tuple(described(k, c) for k, c in (columns or {}).items()),
            total=total,
            silent=silent,
        )
        return Session(self.lab, start, self.approve, self._entered, self.show)

    def __repr__(self) -> str:
        return f"<bench of {self.origin}>"


def connect(
    simulate: Optional[bool] = None,
    name: Optional[str] = None,
    workspace: Union[str, Path, None] = None,
) -> Bench:
    """The bench of this machine (its simulator with simulate) as this script
    uses it, as script:<name> (the script's file name by default); the daemon
    is started when none runs. A person at this terminal is asked here too
    what a measurement's start needs allowed. A script the daemon started
    (thzdaq script start) finds that daemon, its own number and its workspace
    by its environment, and is allowed what it was started with. Its
    measurements go to the workspace given, else to the nearest one from here
    up (thzdaq.toml), else to the program's; a daemon started here loads the
    profile that workspace expects."""
    path = getattr(sys.modules["__main__"], "__file__", None)  # none in a notebook
    name = name or (Path(path).stem if path else "interactive")
    number = os.environ.get(SCRIPT_ID_ENV)
    if simulate is None:
        simulate = os.environ.get(SIMULATE_ENV) == "1"
    origin = script(name, int(number) if number else None)
    folder = chosen(workspace)
    lab = host.connect_or_start(
        simulate, expected_profile(folder), origin, SCRIPT_CLIENT
    )
    warning = profile_warning(lab, folder)
    if warning:
        print(warning, file=sys.stderr)
    approve = None
    if person_here():
        person = RemoteLab(lab.host, CLI, ANSWERING_CLI, find=lab.find)
        approve = AnsweredHere(person, lab.origin)
    return Bench(lab, folder, script_source(path, folder), approve, simulate)
