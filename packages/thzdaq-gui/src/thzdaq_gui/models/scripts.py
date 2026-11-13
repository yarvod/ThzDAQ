"""The scripts the daemon runs or ran, whoever started them, with what they
printed: the window's own (Run of a script's file, the bench's own
measurements started here) and the others'.

Run is StartScript in the window's workspace with its Python
(thzdaq_api.interpreters: the one its thzdaq.toml names, else the program's); Stop is StopScript: their measurements are cancelled,
then a script that goes on is ended. The daemon tells every client a script's
start, what it prints, part by part, and its end; a run heard of later (the
daemon's list), or one whose part was missed, reads its log up to the parts
first (ReadScriptLog). A stop may wait seconds for its script, so the calls
of scripts have a worker of their own, apart from the devices'.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, Signal
from thzdaq_api.interpreters import scripts_python
from thzdaq_api.events import ScriptEnded, ScriptOutput, ScriptStarted
from thzdaq_api.scripts import (
    RUNNING,
    ListScripts,
    ReadScriptLog,
    ScriptInfo,
    StartScript,
    StopScript,
)

from thzdaq_gui.processes import Process
from thzdaq_gui.workers import DeviceWorker

OUTPUT_KEPT = 200_000  # characters of a run's output kept here; its log has all
CALLS, STOPS = "scripts", "stops"  # lanes: a stop does not hold a start
SCRIPT_ICON = "language-python"


@dataclass
class ScriptRun:
    """A script of the daemon as the window knows it, with what it printed."""

    info: ScriptInfo
    output: str = ""
    next: int = 0  # the byte of its log after what output holds
    read: bool = False  # its log was read once (it may have printed before)
    reading: bool = False  # its log is read now: parts heard meanwhile wait
    waiting: List[ScriptOutput] = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.info.id

    @property
    def running(self) -> bool:
        return self.info.status == RUNNING


class ScriptsModel(QObject):
    runs_changed = Signal()  # a run started, ended, or the daemon listed them
    printed = Signal(int, str)  # a run's id, what it printed more
    output_reset = Signal(int)  # a run's output is told anew (whole)
    started_here = Signal(int)  # a run this window started
    failed = Signal(str)  # a call refused or failed: why

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.calls = DeviceWorker(self)
        self.runs: Dict[int, ScriptRun] = {}
        self._heard: Set[int] = set()  # runs told of while the list is asked
        self.processes: Dict[int, Process] = {}  # the runs this window started
        session.workspace.changed.connect(self.runs_changed)
        bridge = session.bridge
        bridge.script_started.connect(self._started)
        bridge.script_output.connect(self._printed)
        bridge.script_ended.connect(self._ended)
        session.station_changed.connect(self.load)  # another lab, or events lost

    def close(self, timeout: float = 2.0) -> None:
        """The window goes: no more calls (scripts run on in the daemon)."""
        self.calls.stop(timeout)

    # Runs
    def load(self, *_) -> None:
        """What the daemon runs and ran lately, in place of what the window
        knew (another lab, or events lost: a run of a daemon gone is gone)."""
        lab = self.session.lab
        self._heard = set()
        self.calls.submit(
            lambda: lab.call(ListScripts()), self._listed, self._failed, key=CALLS
        )

    def _listed(self, found: Tuple[ScriptInfo, ...]) -> None:
        kept = {id: self.runs[id] for id in self._heard if id in self.runs}
        for info in found:
            kept[info.id] = self._know(info)
        for id in set(self.runs) - set(kept):
            self._gone(id)
        self.runs = kept
        self.runs_changed.emit()

    def _know(self, info: ScriptInfo) -> ScriptRun:
        """The run as the daemon tells it now; another daemon's run of the
        same number (its log elsewhere) is another run."""
        run = self.runs.get(info.id)
        if run is None or run.info.log != info.log:
            run = self.runs[info.id] = ScriptRun(info)
        else:
            run.info = info
        return run

    def newest_first(self) -> List[ScriptRun]:
        return sorted(self.runs.values(), key=lambda run: run.id, reverse=True)

    def last_run_of(self, path: Path) -> Optional[ScriptRun]:
        return next(
            (run for run in self.newest_first() if Path(run.info.path) == path),
            None,
        )

    def of_measurement(self, id: int) -> Optional[ScriptRun]:
        """The script started for a run of the bench's own measurement."""
        return next(
            (run for run in self.runs.values() if run.info.measurement == id), None
        )

    def here(self, run: ScriptRun) -> bool:
        """Run in the window's workspace."""
        return self.session.workspace.holds(run.info.workspace)

    def run(self, path: Path, dock: str) -> None:
        """Start the script in the daemon, apart from the window; dock: where
        the window shows it (its Processes entry leads there)."""
        lab, folder = self.session.lab, self.session.workspace.folder

        def start() -> ScriptInfo:
            """LabError when the workspace names a Python not there."""
            python = scripts_python(folder)
            return lab.call(StartScript(str(path), python, workspace=str(folder)))

        self.calls.submit(
            start,
            lambda info: self._run_started(info, dock),
            self._failed,
            key=CALLS,
        )

    def _run_started(self, info: ScriptInfo, dock: str) -> None:
        self._heard.add(info.id)
        run = self._know(info)
        if run.running and info.id not in self.processes:
            self.processes[info.id] = self.session.processes.start(
                f"Script {info.name}",
                SCRIPT_ICON,
                dock,
                stop=lambda: self.stop(info.id),
            )
        self.runs_changed.emit()
        self.started_here.emit(info.id)

    def stop(self, id: int) -> None:
        """Cancel its measurements, then end it if it goes on."""
        run = self.runs.get(id)
        if run is None or not run.running:
            return
        lab, stop = self.session.lab, StopScript(id=id)
        self.calls.submit(
            lambda: lab.call(stop), self._stopped, self._failed, key=STOPS
        )

    def _stopped(self, info: ScriptInfo) -> None:
        self._know(info)
        self._gone(info.id)
        self.runs_changed.emit()

    def _gone(self, id: int) -> None:
        self.session.processes.finish(self.processes.pop(id, None))

    def _failed(self, error: BaseException) -> None:
        self.failed.emit(str(error))

    # What the daemon tells
    def _started(self, body: ScriptStarted) -> None:
        self._heard.add(body.script.id)
        self._know(body.script)
        self.runs_changed.emit()

    def _ended(self, body: ScriptEnded) -> None:
        self._heard.add(body.script.id)
        self._know(body.script)
        self._gone(body.script.id)
        self.runs_changed.emit()

    def _printed(self, part: ScriptOutput) -> None:
        run = self.runs.get(part.id)
        if run is None:
            return  # its start was not heard: its log is read when it is shown
        if run.reading:
            run.waiting.append(part)
        elif not self._add(run, part):
            run.waiting.append(part)
            self._read(run)

    def output(self, id: int) -> str:
        """What a run printed, as far as heard; its log is read the first time
        (it may have printed before the window heard it)."""
        run = self.runs.get(id)
        if run is None:
            return ""
        if not run.read and not run.reading:
            self._read(run)
        return run.output

    def _add(self, run: ScriptRun, part: ScriptOutput) -> bool:
        """A part of its output after what it holds; False when the part
        before it is missing."""
        if part.next <= run.next:
            return True  # held already
        if part.since > run.next:
            return False
        text = part.text
        if part.since < run.next:  # partly held: the rest of its bytes
            rest = text.encode()[run.next - part.since :]
            text = rest.decode("utf-8", errors="replace")
        run.output += text
        run.next = part.next
        if len(run.output) > OUTPUT_KEPT:
            run.output = run.output[-OUTPUT_KEPT:]
            self.output_reset.emit(run.id)
        else:
            self.printed.emit(run.id, text)
        return True

    def _read(self, run: ScriptRun) -> None:
        """Its log from what it holds up to now, then the parts heard
        meanwhile."""
        run.reading, run.read = True, True
        lab, id, since = self.session.lab, run.id, run.next

        def read() -> ScriptOutput:
            text, after = "", since
            while True:
                part = lab.call(ReadScriptLog(id=id, since=after))
                if not part.text:
                    return ScriptOutput(id, text, since, after)
                text, after = text + part.text, part.next

        def done(part: ScriptOutput) -> None:
            run.reading = False
            self._add(run, part)
            waiting, run.waiting = run.waiting, []
            for index, heard in enumerate(waiting):
                if self._add(run, heard):
                    continue
                if part.next > since:  # it printed more meanwhile: read on
                    run.waiting = waiting[index:]
                    self._read(run)
                    return
                run.next = heard.since  # the log lacks it: go on from the part
                self._add(run, heard)

        def failed(error: BaseException) -> None:
            run.reading = False
            self._failed(error)

        self.calls.submit(read, done, failed, key=CALLS)
