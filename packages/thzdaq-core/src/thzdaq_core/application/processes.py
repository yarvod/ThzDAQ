"""Scripts the daemon runs as processes (thzdaq script start), and what a person
allowed them in advance.

A script runs apart from any terminal (the Launcher port) in its workspace,
its output in data/scripts/<id>.log; it knows its number and its daemon by
THZDAQ_SCRIPT_ID and THZDAQ_SIMULATE and calls the daemon as
script:<name>@<id>. Its number is the daemon's next, past the logs its folder
holds already. A thread waits for its end; its sessions still open then end at
once (interrupted), as they would when it fell silent.

Stopping cancels the measurements it started and gives it STOP_S to end
(its with blocks end them cancelled); a script that goes on is ended.

What it was allowed (set:<ref>, call:<ref>, run:<procedure>) is not asked
again while it runs, but for a dangerous step or another's sweep; a session it
starts is allowed when every device it names is. The measurements it starts
note what it was allowed.
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

import msgspec
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import ALLOWED
from thzdaq_api.measurements import DATA
from thzdaq_api.origins import script, script_number
from thzdaq_api.workspace import WORKSPACE_ENV
from thzdaq_api.scripts import (
    CALL,
    EXITED,
    KINDS,
    RUN,
    RUNNING,
    SCRIPT_ID_ENV,
    SCRIPTS,
    SET,
    SIMULATE_ENV,
    STOP_S,
    STOPPED,
    Grant,
    ScriptInfo,
    ScriptLog,
    StartScript,
)

from thzdaq_core.application.bench import Bench
from thzdaq_core.application.clock import wall_time
from thzdaq_core.application.ports import Launched, Launcher
from thzdaq_core.application.runs import Runs
from thzdaq_core.application.scripts import Sessions
from thzdaq_core.application.workspaces import Workspaces
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.catalog import get_procedure

LOG_PART = 65536  # bytes of a script's log one read gives at most
KEPT = 100  # scripts that ended, remembered for list and logs
UNBUFFERED = {"PYTHONUNBUFFERED": "1"}  # its output reaches the log as it prints


@dataclass
class _Script:
    info: ScriptInfo
    launched: Launched
    ended: threading.Event = field(default_factory=threading.Event)
    stopping: bool = False

    @property
    def running(self) -> bool:
        return not self.ended.is_set()


def last_log(folder: Path) -> int:
    """The highest number of the logs a folder holds; 0 for none."""
    numbers = [int(p.stem) for p in folder.glob("*.log") if p.stem.isdigit()]
    return max(numbers, default=0)


class ScriptProcesses:
    def __init__(
        self,
        bench: Bench,
        workspaces: Workspaces,
        runs: Runs,
        sessions: Sessions,
        launcher: Launcher,
        simulate: Callable[[], bool],
        grace: float = STOP_S,
    ):
        """simulate: whether the daemon works on simulators (its scripts too);
        grace: how long a stopped script has to end after its cancel."""
        self.bench = bench
        self.grace = grace
        self.workspaces = workspaces
        self.runs = runs
        self.sessions = sessions
        self.launcher = launcher
        self.simulate = simulate
        self._scripts: Dict[int, _Script] = {}
        self._last = 0
        self._lock = threading.Lock()

    def start(self, args: StartScript, origin: str) -> ScriptInfo:
        folder = self.workspaces.folder(args.workspace)
        path = folder / Path(args.path).expanduser()
        if not path.is_file():
            raise LabError(ErrorCode.INVALID_ARGUMENTS, f"No script {str(path)!r}")
        if not args.python:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, "No python to run it with")
        self.check(args.allow)
        logs = folder / DATA / SCRIPTS
        with self._lock:
            number = self._last = max(self._last, last_log(logs)) + 1
            log = logs / f"{number}.log"
            command = (*args.python, str(path), *args.arguments)
            environment = {
                SCRIPT_ID_ENV: str(number),
                SIMULATE_ENV: "1" if self.simulate() else "0",
                WORKSPACE_ENV: str(folder),
                **UNBUFFERED,
            }
            try:
                launched = self.launcher.launch(command, folder, environment, log)
            except OSError as e:
                raise LabError(
                    ErrorCode.INVALID_ARGUMENTS, f"{command[0]} did not start: {e}"
                ) from None
            info = ScriptInfo(
                id=number, name=path.stem, path=str(path), command=command,
                workspace=str(folder), log=str(log), origin=script(path.stem, number),
                by=origin, pid=launched.pid, status=RUNNING, started=wall_time(),
                allow=tuple(args.allow), share=tuple(args.share),
            )  # fmt: skip
            found = self._scripts[number] = _Script(info, launched)
            self._forget_old()
        threading.Thread(
            target=self._watch, args=(found,), name=f"script {number}", daemon=True
        ).start()
        return info

    def check(self, allow: Iterable[Grant]) -> None:
        """What is allowed names devices and procedures that exist: a typo
        would allow nothing."""
        for grant in allow:
            if grant.kind not in KINDS:
                raise LabError(
                    ErrorCode.INVALID_ARGUMENTS,
                    f"{grant}: allow {', '.join(KINDS)}",
                )
            if grant.kind == RUN:
                try:
                    get_procedure(grant.target)
                except ProcedureError as e:
                    raise LabError(ErrorCode.NOT_FOUND, f"{grant}: {e}") from None
            else:
                self.bench.info(grant.target)  # an unknown device is NOT_FOUND

    def _watch(self, found: _Script) -> None:
        code = found.launched.wait()
        status = STOPPED if found.stopping else EXITED
        found.info = msgspec.structs.replace(
            found.info, status=status, ended=wall_time(), exit_code=code, pid=None
        )
        found.ended.set()
        self.sessions.interrupt(found.info.origin, f"its script {status}")

    def _forget_old(self) -> None:
        ended = [n for n, s in self._scripts.items() if not s.running]
        for number in ended[: max(0, len(ended) - KEPT)]:
            del self._scripts[number]

    def _get(self, id: int) -> _Script:
        with self._lock:
            found = self._scripts.get(id)
        if found is None:
            raise LabError(ErrorCode.NOT_FOUND, f"No script {id} in the daemon")
        return found

    def all(self) -> Tuple[ScriptInfo, ...]:
        with self._lock:
            return tuple(s.info for s in self._scripts.values())

    def running(self) -> Tuple[ScriptInfo, ...]:
        return tuple(info for info in self.all() if info.status == RUNNING)

    def log(self, id: int, since: int) -> ScriptLog:
        found = self._get(id)
        running = found.running  # before the read: what it printed last is read
        try:
            with open(found.info.log, "rb") as file:
                file.seek(max(0, since))
                data = file.read(LOG_PART)
        except FileNotFoundError:
            data = b""
        return ScriptLog(
            data.decode("utf-8", errors="replace"), since + len(data), running
        )

    def stop(self, id: int) -> ScriptInfo:
        """Cancel what it measures, give it grace to end, then end it."""
        found = self._get(id)
        if not found.running:
            return found.info
        found.stopping = True
        for run in self.runs.active():
            if run.origin == found.info.origin:
                self.runs.cancel(run.id)
        if found.launched.wait(self.grace) is None:
            found.launched.terminate()
        found.ended.wait(self.grace)
        return found.info

    def stop_all(self) -> None:
        for info in self.running():
            self.stop(info.id)

    # What a person allowed in advance
    def _allowed(self, origin: str) -> Optional[ScriptInfo]:
        """The running script that calls as origin."""
        number = script_number(origin)
        with self._lock:
            found = self._scripts.get(number) if number is not None else None
        if found is None or not found.running or found.info.origin != origin:
            return None
        return found.info

    def allows(self, origin: str, kind: str, target: str) -> bool:
        info = self._allowed(origin)
        return info is not None and Grant(kind, target) in info.allow

    def allows_devices(self, origin: str, refs: Iterable[str]) -> bool:
        """It may set or call every one of these devices: a session it starts
        with them goes without asking."""
        info = self._allowed(origin)
        return info is not None and all(
            self.allows(origin, SET, ref) or self.allows(origin, CALL, ref)
            for ref in refs
        )

    def shared(self, origin: str) -> Tuple[str, ...]:
        """Devices its measurements share while another one sweeps them."""
        info = self._allowed(origin)
        return () if info is None else info.share

    def note(self, run_id: int, origin: str) -> None:
        """What a measurement's script was allowed, into the measurement."""
        info = self._allowed(origin)
        if info is not None and (info.allow or info.share):
            self.runs.note(
                run_id,
                ALLOWED,
                {
                    "script": info.id,
                    "by": info.by,
                    "allow": [str(grant) for grant in info.allow],
                    "share": list(info.share),
                },
            )
