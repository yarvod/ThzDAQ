"""The daemon as an agent reaches it: connected at the agent's first call, as
mcp:<its name from initialize>, so the window shows who asks. It listens from
then on as a client of the kind mcp: the daemon lists the agent among its
clients and stays while the agent works (thzdaq_api.tools.Reach).

RemoteLab is synchronous (stdlib HTTP): a call or a tool waits in a worker
thread, and the event loop goes on serving, so a call that waits for a person
or a measurement can be cancelled. A cancelled call is left to end in its
thread: what it asked of the daemon goes on (a measurement is not cancelled
with it), and its progress is told no more.
"""

import threading
from typing import Awaitable, Callable, Optional, TypeVar

import anyio
import anyio.from_thread
import anyio.lowlevel
from thzdaq_api.operation import Operation
from thzdaq_api.origins import MCP
from thzdaq_api.remote import RemoteLab
from thzdaq_api.tools import Reach, Tool

R = TypeVar("R")

Connect = Callable[[str], RemoteLab]  # the daemon, called as an origin
# How a tool tells the client how far it is: (done, total, message)
Progress = Callable[[float, Optional[float], Optional[str]], Awaitable[None]]


class Bench:
    def __init__(self, connect: Connect):
        self._connect = connect
        self._reach: Optional[Reach] = None
        self._lock = threading.Lock()

    async def open(self, agent: str) -> None:
        """Connect as mcp:<agent> once (starting the daemon when none runs)."""
        await anyio.to_thread.run_sync(self._open, agent)

    def _open(self, agent: str) -> None:
        with self._lock:
            if self._reach is None:
                self._reach = Reach(self._connect(MCP + agent))

    async def call(self, operation: Operation[R]) -> R:
        return await anyio.to_thread.run_sync(
            self._reach.call, operation, abandon_on_cancel=True
        )

    async def run(
        self, tool: Tool, args: Operation, progress: Optional[Progress]
    ) -> str:
        """The tool's answer; its progress told in the loop while it is awaited."""
        if progress is None:
            return await anyio.to_thread.run_sync(
                tool.call, self._reach, args, None, abandon_on_cancel=True
            )
        loop = anyio.lowlevel.current_token()
        awaited = threading.Event()
        awaited.set()

        def told(done: float, total: Optional[float], message: Optional[str]):
            """In the stream's thread: the progress goes out in the loop's."""
            if awaited.is_set():
                anyio.from_thread.run(progress, done, total, message, token=loop)

        try:
            return await anyio.to_thread.run_sync(
                tool.call, self._reach, args, told, abandon_on_cancel=True
            )
        finally:
            awaited.clear()

    def close(self) -> None:
        if self._reach is not None:
            self._reach.close()
            self._reach.lab.close()
