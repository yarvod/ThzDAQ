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

Clients hear a script start, what it prints and its end as events: the thread
that waits for its end reads its log as it grows (the process writes it
itself) and tells each new part, a character cut at the end of a part waits
for its rest.

A script has the rights of whoever started it (thzdaq_core's Policy): the
daemon keeps who started each (by), and runs an agent's script as the agent's
(AGENT_ENV in its environment, so it names itself an agent's script) and a
person's without the marks of an agent's shell the daemon may have inherited.

What a person allowed it (set:<ref>, call:<ref>, run:<procedure>,
raw:<instrument>) is not asked again while it runs, but for a dangerous step
or another's sweep; a session it starts is allowed when every device it names
is. The measurements it starts note what it was allowed. An agent's --allow
and --share allow nothing: what its script does is asked as the agent's.
"""

import codecs
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

import msgspec
from thzdaq_api.custom import INPUTS_ENV, Inputs
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ScriptEnded, ScriptOutput, ScriptStarted
from thzdaq_api.measurement_file import ALLOWED
from thzdaq_api.measurements import DATA
from thzdaq_api.origins import AGENT_ENV, AGENT_SHELLS, script, script_number
from thzdaq_api.workspace import WORKSPACE_ENV
from thzdaq_api.scripts import (
    CALL,
    EXITED,
    KINDS,
    OUTPUT_ENV,
    RAW,
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
from thzdaq_core.application.events import EventBus
from thzdaq_core.application.ports import Launched, Launcher
from thzdaq_core.application.runs import Runs
from thzdaq_core.application.scripts import Sessions
from thzdaq_core.application.workspaces import Workspaces
from thzdaq_core.domain.errors import ProcedureError

LOG_PART = 65536  # bytes of a script's log one read gives at most
LAST_WORDS = 8192  # bytes of the end of a log that tell how a script ended
TRACEBACK = "Traceback (most recent call last):"
OUTPUT_S = 0.2  # how often a running script's log is looked at for its output
KEPT = 100  # scripts that ended, remembered for list and logs


@dataclass
class _Script:
    info: ScriptInfo
    launched: Launched
    ended: threading.Event = field(default_factory=threading.Event)
    stopping: bool = False

    @property
    def running(self) -> bool:
        return not self.ended.is_set()


def read_part(log: str, since: int, final: bool) -> Tuple[str, int]:
    """The text of a log from byte since, up to LOG_PART, and the byte after
    it. A character cut at the end of the part is left for the next one,
    unless the log is final (its script ended) and the part is its end."""
    try:
        with open(log, "rb") as file:
            file.seek(max(0, since))
            data = file.read(LOG_PART)
    except FileNotFoundError:
        data = b""
    ended = final and len(data) < LOG_PART
    # CRLF can straddle reads; keep its CR until the next byte arrives.
    if not ended and data.endswith(b"\r"):
        data = data[:-1]
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = decoder.decode(data, final=ended)
    waiting, _ = decoder.getstate()
    return text.replace("\r\n", "\n"), since + len(data) - len(waiting)


def last_words(log: str) -> str:
    """How a script ended, by the end of its log: its last traceback, else
    its last lines."""
    try:
        with open(log, "rb") as file:
            file.seek(0, 2)
            file.seek(max(0, file.tell() - LAST_WORDS))
            text = file.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    found = text.rfind(TRACEBACK)
    return (text[found:] if found >= 0 else text).strip()


def last_log(folder: Path) -> int:
    """The highest number of the logs a folder holds; 0 for none."""
    numbers = [int(p.stem) for p in folder.glob("*.log") if p.stem.isdigit()]
    return max(numbers, default=0)


def inputs_text(inputs: Inputs) -> str:
    return msgspec.json.encode(inputs).decode()


class ScriptProcesses:
    def __init__(
        self,
        bench: Bench,
        workspaces: Workspaces,
        runs: Runs,
        events: EventBus,
        sessions: Sessions,
        launcher: Launcher,
        simulate: Callable[[], bool],
        procedure: Callable[[str], object],
        grace: float = STOP_S,
    ):
        """simulate: whether the daemon works on simulators (its scripts too);
        procedure(name): a procedure of the catalog (ProcedureError for none);
        grace: how long a stopped script has to end after its cancel."""
        self.bench = bench
        self.procedure = procedure
        self.grace = grace
        self.workspaces = workspaces
        self.runs = runs
        self.events = events
        self.sessions = sessions
        self.launcher = launcher
        self.simulate = simulate
        self._scripts: Dict[int, _Script] = {}
        self._last = 0
        self._lock = threading.Lock()

    def start(
        self,
        args: StartScript,
        origin: str,
        by_agent: bool,
        inputs: Optional[Inputs] = None,
        starting: Callable[[str], None] = lambda origin: None,
        measurement: Optional[int] = None,
    ) -> ScriptInfo:
        """by_agent: an agent (or its script) starts it: it runs as the
        agent's, allowed nothing in advance. inputs: what a run of the bench's
        own measurement (number measurement) gives its script; starting(origin):
        told what the script will call itself, before it starts."""
        if by_agent:
            args = msgspec.structs.replace(args, allow=(), share=())
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
                **({AGENT_ENV: "1"} if by_agent else {}),
                **({} if inputs is None else {INPUTS_ENV: inputs_text(inputs)}),
                **OUTPUT_ENV,
            }
            removed = () if by_agent else AGENT_SHELLS
            starting(script(path.stem, number, by_agent))
            try:
                launched = self.launcher.launch(
                    command, folder, environment, log, removed
                )
            except OSError as e:
                raise LabError(
                    ErrorCode.INVALID_ARGUMENTS, f"{command[0]} did not start: {e}"
                ) from None
            info = ScriptInfo(
                id=number, name=path.stem, path=str(path), command=command,
                workspace=str(folder), log=str(log),
                origin=script(path.stem, number, by_agent),
                by=origin, pid=launched.pid, status=RUNNING, started=wall_time(),
                allow=tuple(args.allow), share=tuple(args.share),
                measurement=measurement,
            )  # fmt: skip
            found = self._scripts[number] = _Script(info, launched)
            self._forget_old()
        self.events.publish(ScriptStarted(info))
        threading.Thread(
            target=self._watch, args=(found,), name=f"script {number}", daemon=True
        ).start()
        return info

    def check(self, allow: Iterable[Grant]) -> None:
        """What is allowed names devices, procedures and instruments (that take
        raw commands) that exist: a typo would allow nothing."""
        exists: Dict[str, Callable[[str], object]] = {
            SET: self.bench.info,
            CALL: self.bench.info,
            RUN: self.procedure,
            RAW: self.bench.raw_parts,
        }
        for grant in allow:
            if grant.kind not in exists:
                raise LabError(
                    ErrorCode.INVALID_ARGUMENTS,
                    f"{grant}: allow {', '.join(KINDS)}",
                )
            try:
                exists[grant.kind](grant.target)
            except ProcedureError as e:
                raise LabError(ErrorCode.NOT_FOUND, f"{grant}: {e}") from None

    def _watch(self, found: _Script) -> None:
        """Tells what it prints while it runs, then the rest and its end."""
        told = 0
        while (code := found.launched.wait(OUTPUT_S)) is None:
            told = self._tell(found.info, told, final=False)
        self._tell(found.info, told, final=True)
        status = STOPPED if found.stopping else EXITED
        found.info = msgspec.structs.replace(
            found.info, status=status, ended=wall_time(), exit_code=code, pid=None
        )
        found.ended.set()
        self.sessions.ended(
            found.info.origin, code, f"its script {status}", last_words(found.info.log)
        )
        self.events.publish(ScriptEnded(found.info))

    def _tell(self, info: ScriptInfo, since: int, final: bool) -> int:
        """Its output from byte since as events, part by part; where it ends."""
        while True:
            text, after = read_part(info.log, since, final)
            if not text:
                return after
            self.events.publish(ScriptOutput(info.id, text, since, after))
            since = after

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
        text, after = read_part(found.info.log, since, final=not running)
        return ScriptLog(text, after, running)

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

    def started_by(self, origin: str) -> Optional[str]:
        """Who started the script that calls as origin (the origin of the
        call that started it), by its number whatever it calls itself; None
        for a script the daemon did not run."""
        number = script_number(origin)
        with self._lock:
            found = self._scripts.get(number) if number is not None else None
        return None if found is None else found.info.by

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

    def noted(self, origin: str) -> Dict[str, Any]:
        """What a measurement its script starts notes from its start: what the
        script was allowed (nothing when it was allowed nothing)."""
        info = self._allowed(origin)
        if info is None or not (info.allow or info.share):
            return {}
        allowed = {
            "script": info.id,
            "by": info.by,
            "allow": [str(grant) for grant in info.allow],
            "share": list(info.share),
        }
        return {ALLOWED: [allowed]}
