"""The daemon as an agent reaches it: connected at the agent's first call, as
mcp:<its name from initialize>, so the window shows who asks. It listens from
then on as a client of the kind mcp: the daemon lists the agent among its
clients and stays while the agent works; tools hear its events through it.

RemoteLab is synchronous (stdlib HTTP): a call waits in a worker thread, and
the event loop goes on serving, so a call that waits for a person or a
measurement can be cancelled. A cancelled call is left to end in its thread:
what it asked of the daemon goes on (a measurement is not cancelled with it).
"""

import threading
from typing import Callable, List, Optional, TypeVar

import anyio
from thzdaq_api.events import Event
from thzdaq_api.operation import Operation
from thzdaq_api.origins import MCP
from thzdaq_api.remote import RemoteLab

R = TypeVar("R")

Connect = Callable[[str], RemoteLab]  # the daemon, called as an origin
Listener = Callable[[Event], None]  # runs in the event stream's thread


class Bench:
    def __init__(self, connect: Connect):
        self._connect = connect
        self._lab: Optional[RemoteLab] = None
        self._listeners: List[Listener] = []
        self._lock = threading.Lock()

    async def open(self, agent: str) -> None:
        """Connect as mcp:<agent> once (starting the daemon when none runs)."""
        await anyio.to_thread.run_sync(self._open, agent)

    def _open(self, agent: str) -> None:
        with self._lock:
            if self._lab is None:
                self._lab = self._connect(MCP + agent)
                self._lab.subscribe(self._heard)

    def _heard(self, event: Event) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            listener(event)

    def listen(self, listener: Listener) -> Callable[[], None]:
        """Hear the events from now on; returns what stops it."""
        with self._lock:
            self._listeners.append(listener)

        def stop() -> None:
            with self._lock:
                self._listeners.remove(listener)

        return stop

    async def call(self, operation: Operation[R]) -> R:
        return await anyio.to_thread.run_sync(
            self._lab.call, operation, abandon_on_cancel=True
        )

    def close(self) -> None:
        if self._lab is not None:
            self._lab.close()
