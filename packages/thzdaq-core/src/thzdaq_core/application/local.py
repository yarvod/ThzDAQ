"""LocalLab: the bench's use cases called in this process, through the same JSON a
remote call travels as, so it behaves as RemoteLab does (contract tests use both)."""

import os
import sys
import threading
from typing import Callable, Dict, Optional, Tuple, TypeVar

from thzdaq_api import wire
from thzdaq_api.daemon import API_VERSION, ClientInfo, DaemonSettings, ProcessInfo
from thzdaq_api.events import Event
from thzdaq_api.host import app_version
from thzdaq_api.operation import Operation

from thzdaq_core.application.assembly import Assembled
from thzdaq_core.application.clock import wall_time

R = TypeVar("R")


class LocalLab:
    def __init__(self, assembled: Assembled, origin: str = "local"):
        self.assembled = assembled
        self.dispatcher = assembled.dispatcher
        self.events = assembled.events
        self.origin = origin

    def call(self, operation: Operation[R]) -> R:
        data = self.dispatcher.dispatch_json(
            operation.name, wire.encode(operation), self.origin
        )
        return wire.decode_result(type(operation), data)

    def subscribe(
        self, listener: Callable[[Event], None], since: Optional[int] = None
    ) -> Callable[[], None]:
        """While it listens it is a client of the daemon, as a stream is."""
        stop = self.events.subscribe(
            lambda event: listener(wire.decode_event(wire.encode(event))), since
        )
        leave = self.assembled.control.listen(self.origin)

        def unsubscribe() -> None:
            stop()
            leave()

        return unsubscribe


class LocalControl:
    """The process of a LocalLab is this one: its clients are the LocalLabs
    that listen, it keeps no log file and its settings only while it lives,
    and a stop is only noted (the owner of the bench ends it)."""

    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self.started = wall_time()
        self.stopped = threading.Event()
        self.restart = False
        self._settings = DaemonSettings(idle_timeout=0.0)
        self._clients: Dict[int, ClientInfo] = {}
        self._last = 0

    def process(self) -> ProcessInfo:
        return ProcessInfo(
            os.getpid(), API_VERSION, app_version(), sys.executable, self.started, 0,
            self.simulate,
        )  # fmt: skip

    def clients(self) -> Tuple[ClientInfo, ...]:
        return tuple(self._clients.values())

    def listen(self, origin: str) -> Callable[[], None]:
        """A client of the kind its origin names (gui, cli, mcp, ...) until
        what this returns is called."""
        self._last += 1
        key = self._last
        kind = origin.split(":")[0]
        self._clients[key] = ClientInfo(kind, os.getpid(), origin, wall_time())
        return lambda: self._clients.pop(key, None)

    def stop(self, restart: bool) -> None:
        self.restart = restart
        self.stopped.set()

    def settings(self) -> DaemonSettings:
        return self._settings

    def change(self, settings: DaemonSettings) -> None:
        self._settings = settings

    def log(self, lines: int) -> Tuple[str, ...]:
        return ()
