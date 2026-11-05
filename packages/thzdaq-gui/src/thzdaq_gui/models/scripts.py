"""The scripts of a window: the files in the script folders of its workspace
(scripts/ and the folders added to it), and the scripts the daemon runs or
ran, whoever started them, with what they printed.

Run is StartScript with this program's Python (host.script_python) in the
window's workspace; Stop is StopScript: their measurements are cancelled,
then a script that goes on is ended. The daemon tells every client a script's
start, what it prints, part by part, and its end; a run heard of later (the
daemon's list), or one whose part was missed, reads its log up to the parts
first (ReadScriptLog). A stop may wait seconds for its script, so the calls
of scripts have a worker of their own, apart from the devices'.

A new script is a copy of a template (thzdaq_api.templates) in scripts/; the
script of a measurement (its text kept with it) is the file it ran while that
holds the same text, else a copy, scripts/<name>_<id>.py.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import msgspec
from PySide6.QtCore import QFileSystemWatcher, QObject, Signal
from thzdaq_api import host, templates
from thzdaq_api.errors import LabError
from thzdaq_api.events import ScriptEnded, ScriptOutput, ScriptStarted
from thzdaq_api.measurement_file import SCRIPT, Measurement
from thzdaq_api.scripts import (
    RUNNING,
    ListScripts,
    ReadScriptLog,
    ScriptInfo,
    StartScript,
    StopScript,
)
from thzdaq_api.sessions import ScriptSource

from thzdaq_gui.dock_names import SCRIPTS
from thzdaq_gui.processes import Process
from thzdaq_gui.workers import DeviceWorker

OUTPUT_KEPT = 200_000  # characters of a run's output kept here; its log has all
SUFFIX = ".py"
CALLS, STOPS = "scripts", "stops"  # lanes: a stop does not hold a start
SKIPPED = ("__pycache__",)  # folders of no scripts; hidden ones too


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


def same_text(path: Path, source: ScriptSource) -> bool:
    """The file holds the text the script was run with."""
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == (
        source.sha256
    )


def scripts_in(folder: Path) -> List[Path]:
    """The scripts of a folder and its folders (not hidden ones, no caches)."""
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.rglob(f"*{SUFFIX}")
        if not any(
            part.startswith(".") or part in SKIPPED
            for part in path.relative_to(folder).parts
        )
    )


class ScriptsModel(QObject):
    files_changed = Signal()  # folders, or the scripts in them
    runs_changed = Signal()  # a run started, ended, or the daemon listed them
    printed = Signal(int, str)  # a run's id, what it printed more
    output_reset = Signal(int)  # a run's output is told anew (whole)
    chosen = Signal(object)  # a script to show: made, or kept from a measurement
    started_here = Signal(int)  # a run this window started
    failed = Signal(str)  # a call refused or failed: why

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.calls = DeviceWorker(self)
        self.runs: Dict[int, ScriptRun] = {}
        self._heard: Set[int] = set()  # runs told of while the list is asked
        self.processes: Dict[int, Process] = {}  # the runs this window started
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.refresh_files)
        session.workspace.changed.connect(self._moved)
        bridge = session.bridge
        bridge.script_started.connect(self._started)
        bridge.script_output.connect(self._printed)
        bridge.script_ended.connect(self._ended)
        session.station_changed.connect(self.load)  # another lab, or events lost
        self.refresh_files()

    def _moved(self) -> None:
        """Another workspace: its scripts; runs here are others now."""
        self.refresh_files()
        self.runs_changed.emit()

    def close(self, timeout: float = 2.0) -> None:
        """The window goes: no more calls (scripts run on in the daemon)."""
        self.calls.stop(timeout)

    # Files
    def folders(self) -> Tuple[Path, ...]:
        """scripts/ of the workspace, then the folders added to it (a broken
        thzdaq.toml is told, and only scripts/ shown)."""
        workspace = self.session.workspace
        try:
            return workspace.script_folders()
        except LabError as e:
            self.failed.emit(str(e))
            return (workspace.scripts,)

    def files(self) -> Dict[Path, List[Path]]:
        """The scripts of each folder."""
        return {folder: scripts_in(folder) for folder in self.folders()}

    def refresh_files(self, *_) -> None:
        """Watch the folders (each folder within them too) and tell anew."""
        watched = self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        for folder in self.folders():
            if folder.is_dir():
                inner = (p for p in folder.rglob("*") if p.is_dir())
                self.watcher.addPaths([str(folder), *(str(p) for p in inner)])
        self.files_changed.emit()

    def keeps_folders(self) -> bool:
        return self.session.workspace.keeps_folders()

    def add_folder(self, folder: Path) -> None:
        """LabError when the workspace cannot keep it."""
        self.session.workspace.add_script_folder(folder)
        self.refresh_files()

    def remove_folder(self, folder: Path) -> None:
        self.session.workspace.remove_script_folder(folder)
        self.refresh_files()

    @staticmethod
    def templates() -> Tuple[templates.Template, ...]:
        return templates.templates()

    def new_script(self, template: str) -> Path:
        """A copy of a template in scripts/, shown (OSError when it cannot be
        written)."""
        path = templates.create(template, self.session.workspace.scripts)
        self._show(path)
        return path

    def script_of(self, measurement: Measurement) -> Optional[Path]:
        """The script that measured it, as a file of the window's workspace:
        the one it ran while it holds the same text, else a copy in scripts/
        named after it and the measurement; shown. None: no script measured
        it (a built-in procedure, a file of an older version)."""
        kept = measurement.metadata.get(SCRIPT)
        if not kept:
            return None
        source = msgspec.convert(kept, ScriptSource)
        workspace = self.session.workspace
        ran = workspace.folder / source.path  # a path outside it is whole
        if same_text(ran, source):
            path = ran
        else:
            name = f"{Path(source.path).stem}_{measurement.id}"
            copy = workspace.scripts / f"{name}{SUFFIX}"
            path = (
                copy
                if same_text(copy, source)
                else templates.write_new(workspace.scripts, name, source.text)
            )
        self._show(path)
        return path

    def _show(self, path: Path) -> None:
        self.refresh_files()
        self.chosen.emit(path)

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

    def here(self, run: ScriptRun) -> bool:
        """Run in the window's workspace."""
        return self.session.workspace.holds(run.info.workspace)

    def run(self, path: Path) -> None:
        """Start the script in the daemon, apart from the window."""
        start = StartScript(
            path=str(path),
            python=host.script_python(),
            workspace=str(self.session.workspace.folder),
        )
        lab = self.session.lab
        self.calls.submit(
            lambda: lab.call(start), self._run_started, self._failed, key=CALLS
        )

    def _run_started(self, info: ScriptInfo) -> None:
        self._heard.add(info.id)
        run = self._know(info)
        if run.running and info.id not in self.processes:
            self.processes[info.id] = self.session.processes.start(
                f"Script {info.name}",
                "language-python",
                SCRIPTS,
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
