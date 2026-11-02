"""The daemon's process: one per machine (the simulator's is another), found by
its host file, ended by a stop, an idle timeout or a signal.

It lives while clients listen or measurements run; after the last of them it
waits idle_timeout seconds (0: forever) and ends. A client that finds it gone
starts it again (thzdaq_api.host.connect_or_start).
"""

import logging
import os
import secrets
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import msgspec
from thzdaq_api.daemon import (
    API_VERSION,
    ClientInfo,
    DaemonSettings,
    Health,
    HostInfo,
    ProcessInfo,
)
from thzdaq_api.events import StationChanged
from thzdaq_api.host import (
    DaemonFiles,
    app_version,
    log_tail,
    remove_host,
    spawn,
    start_command,
    write_host,
)
from thzdaq_api.lock import FileLock
from thzdaq_api.operation import Rights
from thzdaq_api.rights import Decision
from thzdaq_api.transport import HEARTBEAT_S
from thzdaq_core.application.clock import wall_time
from thzdaq_api.measurements import DATA

from thzdaq_daemon.compose import Composed, compose
from thzdaq_daemon.server import Clients, Server

logger = logging.getLogger(__name__)

IDLE_S = 600.0  # default idle timeout
LOCK_S = 10.0  # a restarted daemon waits this long for the old one to let go


class Settings(msgspec.Struct):
    """What the daemon keeps between runs, in its home folder (daemon.json; the
    simulator's in daemon-sim.json: its profile is not the bench's)."""

    station: Optional[str] = None  # the last profile it worked with
    idle_timeout: float = IDLE_S
    agents: Dict[Rights, Decision] = {}  # what agents may do, as a person set it

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            return msgspec.json.decode(path.read_bytes(), type=cls)
        except FileNotFoundError:
            return cls()

    def save(self, path: Path) -> None:
        partial = path.with_suffix(".partial")
        partial.write_bytes(msgspec.json.format(msgspec.json.encode(self)))
        os.replace(partial, path)


@dataclass
class Options:
    home: Path  # daemon.json; data/ unless given
    files: DaemonFiles  # the real daemon's or the simulator's
    station: Optional[str] = None
    data: Optional[Path] = None
    simulate: bool = False
    port: int = 0
    idle_timeout: Optional[float] = None  # None: as daemon.json says
    lively: bool = True

    @property
    def settings_path(self) -> Path:
        return self.home / ("daemon-sim.json" if self.simulate else "daemon.json")

    def arguments(self, station: Optional[str]) -> List[str]:
        """How to start a daemon like this one again."""
        found = ["--home", str(self.home), "--port", "0"]
        if station:
            found += ["--station", station]
        if self.data is not None:
            found += ["--data", str(self.data)]
        if self.simulate:
            found.append("--simulate")
        if self.idle_timeout is not None:
            found += ["--idle-timeout", str(self.idle_timeout)]
        return found


class Daemon:
    """Implements the DaemonControl port for the use cases."""

    def __init__(self, options: Options):
        self.options = options
        self.saved = Settings.load(options.settings_path)
        self.started = wall_time()
        self.listening = Clients()
        self.server: Optional[Server] = None
        self.composed: Optional[Composed] = None
        self.restart = False
        self._stopping = threading.Event()

    @property
    def idle_timeout(self) -> float:
        given = self.options.idle_timeout
        return self.saved.idle_timeout if given is None else given

    def run(self) -> int:
        files = self.options.files
        lock = FileLock(files.lock)
        if not lock.acquire(LOCK_S):
            logger.error(f"Another daemon runs (it holds {files.lock})")
            return 1
        try:
            self._serve()
        finally:
            lock.release()
        if self.restart:
            station = self.composed.bench.path if self.composed else None
            spawn(start_command() + self.options.arguments(station), files)
        return 0

    def _serve(self) -> None:
        options = self.options
        station = options.station or self.saved.station
        data = options.data or options.home / DATA
        logger.info(
            f"Starting (pid {os.getpid()}, station {station}, data {data}"
            f"{' on simulators' if options.simulate else ''})"
        )
        self.composed = compose(
            station, options.home, data, options.simulate, self, options.lively
        )
        if station:
            self.saved.station = station
            self.saved.save(options.settings_path)
        assembled = self.composed.assembled
        assembled.events.subscribe(self._remember)
        self.server = Server(
            assembled.dispatcher,
            assembled.events,
            assembled.daemon,
            secrets.token_urlsafe(32),
            Health(os.getpid(), API_VERSION, app_version(), options.simulate),
            self.listening,
            options.port,
        )
        serving = threading.Thread(
            target=self.server.serve_forever, name="http", daemon=True
        )
        serving.start()
        write_host(options.files, self._host(station))
        logger.info(f"Serving on port {self.server.port}")
        self._on_signals()
        watching = threading.Thread(target=self._watch, name="idle", daemon=True)
        watching.start()
        try:
            self._stopping.wait()
        finally:
            logger.info("Stopping")
            remove_host(options.files, os.getpid())
            self.server.stop()
            self.composed.close()
            logger.info("Stopped")

    def _host(self, station: Optional[str]) -> HostInfo:
        return HostInfo(
            pid=os.getpid(),
            port=self.server.port,
            token=self.server.token,
            api_version=API_VERSION,
            app_version=app_version(),
            executable=sys.executable,
            started=self.started,
            station=station,
            simulate=self.options.simulate,
        )

    def _on_signals(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return  # a daemon in a thread (tests) is stopped by its owner
        for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), lambda *_: self.stop(False))

    def _watch(self) -> None:
        """End after idle_timeout with no client and no measurement."""
        quiet_since: Optional[float] = None
        while not self._stopping.wait(HEARTBEAT_S):
            timeout = self.idle_timeout
            busy = (
                self.composed.assembled.runs.active() or not self.listening.idle_for()
            )
            if busy or timeout <= 0:
                quiet_since = None
                continue
            now = time.monotonic()
            quiet_since = now if quiet_since is None else quiet_since
            if now - quiet_since >= timeout:
                logger.info(f"Idle for {timeout:g} s: stopping")
                self.stop(False)

    def _remember(self, event) -> None:
        """The profile worked with last is where the next start begins."""
        if isinstance(event.body, StationChanged) and event.body.path:
            self.saved.station = event.body.path
            self.saved.save(self.options.settings_path)

    # DaemonControl
    def process(self) -> ProcessInfo:
        return ProcessInfo(
            os.getpid(), API_VERSION, app_version(), sys.executable, self.started,
            self.server.port if self.server else 0, self.options.simulate,
        )  # fmt: skip

    def clients(self) -> Tuple[ClientInfo, ...]:
        return self.listening.all()

    def stop(self, restart: bool) -> None:
        self.restart = restart
        self._stopping.set()

    def settings(self) -> DaemonSettings:
        return DaemonSettings(self.idle_timeout, dict(self.saved.agents))

    def change(self, settings: DaemonSettings) -> None:
        if settings.idle_timeout != self.idle_timeout:
            self.saved.idle_timeout = settings.idle_timeout
            self.options.idle_timeout = None  # what it was started with gives way
        self.saved.agents = dict(settings.agents)
        self.saved.save(self.options.settings_path)

    def log(self, lines: int) -> Tuple[str, ...]:
        return tuple(log_tail(self.options.files, lines).splitlines())
