"""The bench's own measurements (Custom): the scripts of its library, described
into procedures custom.<name>, and their runs.

The library (the Library port: measurements/ of the program's folder) is
looked at when the catalog is asked and every POLL_S: a script new or changed
since it was described is described again (its text checked, then its
process run described up to its last declaration; cached by its hash); one
that cannot be stays in the catalog with its error. Any change is told to clients (procedures_changed).

A run of one (start_measurement custom.<name>) is a session made before its
script starts (CustomRun): the daemon starts the script's process as the
caller would (thzdaq script start), with the devices and values chosen
(Inputs), and the script's lab.measurement takes the session over. A script
that opens none leaves it to its process: the run ends when the process does,
completed or failed by its exit code. A cancel reaches the script as any
session's does, and its process is ended STOP_S later if it goes on.
"""

import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence, Tuple, Type

from thzdaq_api.custom import (
    CustomInfo,
    CustomLibrary,
    CustomText,
    DeclarationError,
    Declarations,
    Inputs,
    declared_names,
    file_name,
    procedure_name,
    title_of,
    valid_name,
)
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ProceduresChanged
from thzdaq_api.leases import READ
from thzdaq_api.measurement_file import CANCELLED, COMPLETED, FAILED
from thzdaq_api.measurements import ProcedureSummary
from thzdaq_api.scripts import ScriptInfo, StartScript
from thzdaq_api.sessions import ScriptSource, StartSession

from thzdaq_core.application.describe import procedure_summary
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.ports import DescribeFailed, Library, LibraryFile
from thzdaq_core.application.processes import ScriptProcesses
from thzdaq_core.application.runner import Cancelled, Context, Failed
from thzdaq_core.application.runs import STRENGTH, Runs
from thzdaq_core.application.scripts import ScriptSession, Sessions, modes_of
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.custom import CustomProcedure, custom_procedure
from thzdaq_core.domain.measurements.procedure import Procedure

POLL_S = 1.0  # how often the library is looked at for changes


@dataclass(frozen=True)
class Described:
    """A script of the library as the catalog knows it: its procedure, or why
    it has none."""

    file: LibraryFile
    procedure: Optional[Type[CustomProcedure]]
    error: str = ""

    def summary(self) -> ProcedureSummary:
        if self.procedure is not None:
            return procedure_summary(self.procedure)
        title, about = title_of(self.file.text, self.file.name)
        return ProcedureSummary(
            procedure_name(self.file.name), title, about, error=self.error
        )


def info(found: Described) -> CustomInfo:
    file = found.file
    summary = found.summary()
    return CustomInfo(
        file.name, summary.name, summary.title, file.path, file.sha256, found.error
    )


def described(file: LibraryFile, library: Library) -> Described:
    """A script described: its text checked, then its process run described
    when it declares anything; its error (with the traceback) when it cannot
    be."""
    title, about = title_of(file.text, file.name)
    try:
        declares = declared_names(file.text)
        declarations = library.describe(file) if declares else Declarations()
        made = custom_procedure(file.name, title, about, declarations)
    except SyntaxError as e:
        return Described(file, None, f"line {e.lineno}: {e.msg}")
    except (DeclarationError, DescribeFailed, ProcedureError) as e:
        return Described(file, None, str(e))
    return Described(file, made)


class CustomMeasurements:
    """The library as procedures, described anew when a script changes."""

    def __init__(self, library: Library, events: EventBus, poll: float = POLL_S):
        self.library = library
        self.events = events
        self.poll = poll
        self._cache: Dict[Tuple[str, str], Described] = {}  # by name and hash
        self._now: Dict[str, Described] = {}  # by name
        self._lock = threading.Lock()  # one look at a time
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Look at the library every poll, apart from the calls."""
        self._thread = threading.Thread(
            target=self._watch, name="custom measurements", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join()

    def _watch(self) -> None:
        while not self._stopped.is_set():
            self.refresh()
            self._stopped.wait(self.poll)

    def refresh(self) -> Dict[str, Described]:
        """The library as it is now; a change is told to clients."""
        with self._lock:
            files = self.library.files()
            now: Dict[str, Described] = {}
            for file in files:
                key = (file.name, file.sha256)
                if key not in self._cache:
                    self._cache[key] = described(file, self.library)
                now[file.name] = self._cache[key]
            for key in [k for k in self._cache if now.get(k[0]) is not self._cache[k]]:
                del self._cache[key]  # an older text, or a file gone
            changed = now != self._now
            self._now = now
        if changed:
            self.events.publish(ProceduresChanged(self.summaries(now)))
        return now

    def summaries(
        self, now: Optional[Dict[str, Described]] = None
    ) -> Tuple[ProcedureSummary, ...]:
        """Every procedure of the library, those that cannot run with why."""
        found = self.refresh() if now is None else now
        return tuple(item.summary() for _, item in sorted(found.items()))

    def described(self, procedure: str) -> Described:
        """ProcedureError for a name the library has no script of."""
        name = file_name(procedure)
        found = self.refresh().get(name) if name else None
        if found is None:
            raise ProcedureError(f"Unknown procedure {procedure!r}")
        return found

    def listed(self) -> CustomLibrary:
        """The library's folder and its scripts, as the catalog knows them."""
        found = self.refresh()
        return CustomLibrary(
            str(self.library.folder),
            tuple(info(item) for _, item in sorted(found.items())),
        )

    def text(self, name: str) -> CustomText:
        """LabError NOT_FOUND for a name the library has no script of."""
        found = self.refresh().get(name)
        if found is None:
            raise LabError(
                ErrorCode.NOT_FOUND,
                f"No script {name!r} in the library",
                "list_custom lists them",
            )
        return CustomText(info(found), found.file.text)

    def write(self, name: str, text: str) -> Described:
        """The script saved and described; LabError for a name no file
        takes."""
        if not valid_name(name):
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"{name!r} is no name of a measurement",
                "letters, digits and _, from a letter: pv_hot_cold",
            )
        self.library.write(name, text)
        return self.refresh()[name]

    def of_text(self, name: str, text: str) -> Described:
        """A text described as the script name, saved or not (a check)."""
        file = self.library.file(name, text)
        key = (file.name, file.sha256)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = described(file, self.library)
            return self._cache[key]

    def get(self, procedure: str) -> Type[CustomProcedure]:
        """ProcedureError for an unknown one or one whose script is not
        described."""
        found = self.described(procedure)
        if found.procedure is None:
            raise ProcedureError(f"{procedure} is not described: {found.error}")
        return found.procedure


class CustomRun(ScriptSession):
    """A run of the bench's own measurement: a session made before its script
    starts, which the script's lab.measurement takes over."""

    def __init__(
        self,
        procedure: CustomProcedure,
        file: LibraryFile,
        launch: Callable[["CustomRun", Context], ScriptInfo],
        stop: Callable[[int], object],
    ):
        """launch(run, ctx): its script's process started, its origin told
        to the run before; stop(script): that process stopped."""
        super().__init__(
            procedure.title, "", {}, parameters=procedure.to_json(),
            source=ScriptSource(file.path, file.sha256, file.text),
            plots=procedure.declarations.plots,
        )  # fmt: skip
        self.name = procedure.name
        self.description = procedure.description
        self.procedure = procedure
        self.adopted = False  # its script's lab.measurement took it over
        self.script: Optional[int] = None  # the number of its script
        self._launch = launch
        self._stop = stop

    # As its procedure goes
    def slots(self):
        return self.procedure.slots()

    def slot_mode(self, slot: str) -> str:
        """Read until its script says how it uses them: reading conflicts
        with no other measurement (a procedure the script runs may sweep
        them)."""
        return READ

    def validate(self) -> None:
        self.procedure.validate()

    def planned(self):
        return self.procedure.planned()

    def run(self, ctx: Context) -> None:
        self.modes = {use.ref: READ for use in ctx.measurement.devices.values()}
        self.script = self._launch(self, ctx).id
        super().run(ctx)

    def _silent(self, now: float) -> bool:
        """Until its script takes it over, its process keeps it."""
        return self.adopted and super()._silent(now)

    def _cancelling(self) -> None:
        """Its script hears the cancel; its process is ended if it goes on."""
        threading.Thread(
            target=self._stop, args=(self.script,), name=f"stop {self.name}",
            daemon=True,
        ).start()  # fmt: skip

    def adopt(self, args: StartSession, runs: Runs) -> None:
        """The script's lab.measurement: what it says of the measurement, and
        the devices it names (those it sweeps exclusive)."""
        with self._changed:
            ctx = self._live()
            self.adopted = True
            self.silent = args.silent
            self.shared.update(args.share)
            self.columns.update((column.key, column) for column in args.columns)
            measurement = ctx.measurement
            if args.comment and not measurement.comment:
                measurement.comment = args.comment
            for key, value in args.parameters.items():
                measurement.parameters.setdefault(key, value)
            if args.total is not None:
                ctx.progress(ctx.done, args.total)
        station = runs.bench.station
        for ref, mode in modes_of(args).items():
            if not self.holds(ref, mode):
                runs.join(self.owner, ref, mode, self.shares(ref))
                self.named(ref, mode, station.device_use(ref))
        for plot in args.plots:
            self.plot(plot)

    def named(self, ref: str, mode: str, use) -> None:
        """A device its script names: among its devices, so used."""
        with self._changed:
            self.modes[ref] = max(self.modes.get(ref, mode), mode, key=STRENGTH.index)
            self._live().measurement.devices.setdefault(ref, use)

    def process_ended(self, code: Optional[int], why: str, told: str) -> None:
        """Taken over, as any session; else as its process ended."""
        if self.adopted:
            super().process_ended(code, why, told)
        elif self.cancelled:
            self.end(CANCELLED, Cancelled())
        elif code == 0:
            self.end(COMPLETED, None)
        else:
            self.end(FAILED, Failed(f"its script exited with code {code}", told))


class CustomRuns:
    """Runs of the bench's own measurements: their scripts' processes."""

    def __init__(
        self,
        customs: CustomMeasurements,
        processes: ScriptProcesses,
        sessions: Sessions,
        python: Callable[[], Sequence[str]],
    ):
        """python: how a script is run (this program's Python)."""
        self.customs = customs
        self.processes = processes
        self.sessions = sessions
        self.python = python

    def runnable(
        self,
        procedure: Procedure,
        origin: str,
        by_agent: bool,
        workspace: Optional[str],
    ) -> Procedure:
        """What runs a procedure: a built-in one runs itself; the bench's own
        one its script, started as origin would start it (by_agent: an
        agent's) in workspace, once the run has its number."""
        if not isinstance(procedure, CustomProcedure):
            return procedure
        file = self.customs.described(procedure.name).file

        def launch(run: CustomRun, ctx: Context) -> ScriptInfo:
            devices = ctx.measurement.devices
            inputs = Inputs(
                devices={slot: use.ref for slot, use in devices.items()},
                values=procedure.given(),
            )
            start = StartScript(
                path=file.path, python=tuple(self.python()), workspace=workspace
            )

            def starting(script: str) -> None:
                run.origin = script
                self.sessions.made(run, ctx.measurement.id)

            try:
                return self.processes.start(start, origin, by_agent, inputs, starting)
            except LabError as e:
                self.sessions.ended(run.origin, None, str(e), "")
                raise

        return CustomRun(procedure, file, launch, self.processes.stop)
