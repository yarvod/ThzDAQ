"""The kernel of a console: an IPython kernel process (thzdaq_api.console)
and the window's client of it over the Jupyter protocol (jupyter_client).

Kernel is the one owner of a kernel: a thread of its own runs an asyncio loop
with jupyter_client's async manager and client. In it the kernel is started,
interrupted, restarted and stopped, and its channels are read; what the
kernel tells reaches the window as signals of Kernel, queued into the
window's thread. The window's thread never waits for the kernel: a request is
handed to the loop and returns at once, named by the id it returns, and what
answers it carries that id.

A thread and not the Qt loop: jupyter_client works in asyncio, which the Qt
loop does not run without one more library, and a restart or a stop waits up
to seconds for the old process to end; in the thread neither stalls the
window.

A restart or a stop ends the kernel as jupyter_client does: code that runs is
interrupted first, as Ctrl+C does (a with block of lab.measurement ends its
session interrupted and the daemon restores what it was asked to), then the
kernel is asked to end, and ended when it does not (shutdown_wait_time). A
restart then starts a new kernel. A kernel that ends by itself is told
(died) and stays ended until restarted.
"""

import asyncio
import logging
import threading
import uuid
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence

from jupyter_client import AsyncKernelManager
from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
from PySide6.QtCore import QObject, Signal
from thzdaq_api import host
from traitlets import Instance

logger = logging.getLogger(__name__)

START_S = 60.0  # how long a kernel may take to answer after its start
NAME = "thzdaq"  # the kernel's name, as jupyter_client asks for one
# Kinds of messages a kernel sends
STREAM, RESULT, DISPLAY, ERROR, STATUS = (
    "stream", "execute_result", "display_data", "error", "status",
)  # fmt: skip
EXECUTE, COMPLETE, HISTORY = "execute_request", "complete_request", "history_request"
INPUT_REQUEST, INPUT_REPLY = "input_request", "input_reply"
TEXT = "text/plain"
TYPES = "_jupyter_types_experimental"  # a completion's kind, IPython's metadata


class GivenSpec(KernelSpecManager):
    """jupyter_client looks a kernel up by name among those installed; the
    kernel of a console is given."""

    spec = Instance(KernelSpec)

    def get_kernel_spec(self, kernel_name: str) -> KernelSpec:
        return self.spec


class Kernel(QObject):
    started = Signal()  # it takes code: started, or restarted
    failed = Signal(str)  # it did not start: why
    died = Signal(str)  # it ended by itself: how
    busy_changed = Signal(bool)  # it runs code
    # What answers a request (its id first)
    printed = Signal(str, str, str)  # stdout or stderr, text
    shown = Signal(str, str)  # a result or a display, as text
    raised = Signal(str, list)  # the lines of a traceback (with colours)
    finished = Signal(str, str)  # ok, error or aborted
    completed = Signal(str, list, int, int)  # (text, kind) of each, the text's span
    history_found = Signal(str, list)  # inputs, the oldest first
    input_requested = Signal(str, bool)  # the prompt, whether a password

    def __init__(self, command: Sequence[str], parent=None):
        """command: how the kernel starts, with {connection_file}; parent:
        what deletes it, in the window's thread, once its thread has ended
        (the session, with the program), never a tab that closes. Deleted
        from its own thread, or while that thread runs, it would take Qt's
        memory with it."""
        super().__init__(parent)
        self.command = list(command)
        self.manager: Optional[AsyncKernelManager] = None
        self.client = None
        self.tasks: List[asyncio.Task] = []
        self.ready = False  # in the loop: requests go to the kernel
        self.busy = False
        self.loop = asyncio.new_event_loop()
        # The window stops its kernels and waits for them as it closes; a
        # program that ends otherwise does not wait for this thread, and its
        # kernel ends once it sees its parent gone (ipykernel's parent poller)
        self.thread = threading.Thread(target=self._run, name="kernel", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        self.loop.run_forever()
        self.loop.close()

    def _soon(self, coroutine: Coroutine) -> None:
        """Into the loop; a failure nobody expected goes to the log."""
        asyncio.run_coroutine_threadsafe(coroutine, self.loop).add_done_callback(
            self._log_failure
        )

    @staticmethod
    def _log_failure(done: Future) -> None:
        if not done.cancelled() and done.exception() is not None:
            logger.error("The console's kernel failed", exc_info=done.exception())

    # Its life, from the window's thread
    def start(self, environment: Dict[str, str], folder: Path) -> None:
        """environment: the whole environment of its process; folder: where
        it runs."""
        self._soon(self._start(environment, folder))

    def interrupt(self) -> None:
        self._soon(self._interrupt())

    def restart(self, environment: Dict[str, str], folder: Path) -> None:
        """Anew, with this environment and folder."""
        self._soon(self._restart(environment, folder))

    def stop(self) -> None:
        """It ends, then this thread; nothing is told after."""
        self._soon(self._stop())

    def join(self, timeout: Optional[float] = None) -> bool:
        """Until it has stopped; False when it has not within timeout."""
        self.thread.join(timeout)
        return not self.thread.is_alive()

    # Requests, from the window's thread: each returns its id
    def execute(self, code: str, history: bool = True) -> str:
        """history: kept among the inputs a console browses."""
        return self._request(
            "shell", EXECUTE,
            dict(
                code=code, silent=False, store_history=history,
                user_expressions={}, allow_stdin=True, stop_on_error=True,
            ),
        )  # fmt: skip

    def complete(self, code: str, cursor: int) -> str:
        return self._request("shell", COMPLETE, dict(code=code, cursor_pos=cursor))

    def history(self, last: int) -> str:
        """The last inputs of every console, each once."""
        return self._request(
            "shell", HISTORY,
            dict(output=False, raw=True, hist_access_type="tail", n=last, unique=True),
        )  # fmt: skip

    def answer(self, text: str) -> None:
        """What input() asked for."""
        self._request("stdin", INPUT_REPLY, dict(value=text))

    def _request(self, channel: str, kind: str, content: Dict[str, Any]) -> str:
        request = uuid.uuid4().hex
        self.loop.call_soon_threadsafe(self._send, channel, kind, content, request)
        return request

    # In the loop
    def _send(self, channel: str, kind: str, content: Dict[str, Any], id: str):
        if not self.ready:
            return  # it is not there yet, or no longer: the request is moot
        session = self.client.session
        header = session.msg_header(kind)
        header["msg_id"] = id
        getattr(self.client, f"{channel}_channel").send(
            session.msg(kind, content, header=header)
        )

    async def _start(self, environment: Dict[str, str], folder: Path) -> None:
        spec = KernelSpec(
            argv=self.command, language="python", display_name="ThzDAQ",
            interrupt_mode="signal",
        )  # fmt: skip
        self.manager = AsyncKernelManager(
            kernel_spec_manager=GivenSpec(spec=spec), kernel_name=NAME
        )
        try:
            await self.manager.start_kernel(
                env=environment, cwd=str(folder), **host.windowless()
            )
            await self._connect()
        except (OSError, RuntimeError) as e:  # not started, or died at once
            await self._failed(e)

    async def _failed(self, error: Exception) -> None:
        await self._end()
        self.failed.emit(str(error) or type(error).__name__)

    async def _connect(self) -> None:
        """A client of the kernel that has started: once it answers, its
        channels are read."""
        self.client = self.manager.client()
        self.client.start_channels()
        await self.client.wait_for_ready(timeout=START_S)
        self.tasks = [
            asyncio.create_task(self._read(self.client.iopub_channel, self._iopub)),
            asyncio.create_task(self._read(self.client.shell_channel, self._shell)),
            asyncio.create_task(self._read(self.client.stdin_channel, self._stdin)),
            asyncio.create_task(self._watch()),
        ]
        self.ready = True
        self._busy(False)
        self.started.emit()

    async def _disconnect(self) -> None:
        self.ready = False
        for task in self.tasks:
            task.cancel()
        # They end by the cancel: their CancelledError is collected, not raised
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []
        if self.client is not None:
            self.client.stop_channels()
            self.client = None

    async def _interrupt(self) -> None:
        if self.manager is not None and self.manager.has_kernel:
            await self.manager.interrupt_kernel()

    async def _restart(self, environment: Dict[str, str], folder: Path) -> None:
        await self._end()
        await self._start(environment, folder)

    async def _stop(self) -> None:
        try:
            await self._end()
        finally:  # the thread ends even when the kernel did not end well
            self.loop.stop()

    async def _end(self) -> None:
        """The kernel ended, whether it runs, died or never started:
        jupyter_client interrupts it, asks it to end, then ends it. Once per
        manager: its shutdown destroys its zmq context."""
        if self.manager is None:
            return
        manager, self.manager = self.manager, None
        await self._disconnect()
        await manager.shutdown_kernel()

    async def _watch(self) -> None:
        """The kernel's process, until it ends by itself."""
        code = await self.manager.provisioner.wait()
        self.ready = False
        self._busy(False)
        self.died.emit(f"exit code {code}")

    @staticmethod
    async def _read(channel, handle: Callable[[Dict[str, Any]], None]) -> None:
        while True:
            handle(await channel.get_msg())

    def _busy(self, busy: bool) -> None:
        if busy != self.busy:
            self.busy = busy
            self.busy_changed.emit(busy)

    def _iopub(self, message: Dict[str, Any]) -> None:
        kind, content = message["msg_type"], message["content"]
        parent = message["parent_header"]
        id = parent.get("msg_id", "")
        if kind == STREAM:
            self.printed.emit(id, content["name"], content["text"])
        elif kind in (RESULT, DISPLAY):
            self.shown.emit(id, content["data"].get(TEXT, ""))
        elif kind == ERROR:
            self.raised.emit(id, list(content["traceback"]))
        elif kind == STATUS and parent.get("msg_type") == EXECUTE:
            self._busy(content["execution_state"] == "busy")

    def _shell(self, message: Dict[str, Any]) -> None:
        kind, content = message["msg_type"], message["content"]
        id = message["parent_header"].get("msg_id", "")
        if kind == "execute_reply":
            self.finished.emit(id, content["status"])
        elif kind == "complete_reply":
            kinds = {
                c["text"]: c.get("type", "")
                for c in content.get("metadata", {}).get(TYPES, [])
            }
            found = [(text, kinds.get(text, "")) for text in content["matches"]]
            self.completed.emit(
                id, found, content["cursor_start"], content["cursor_end"]
            )
        elif kind == "history_reply":
            self.history_found.emit(id, [entry[2] for entry in content["history"]])

    def _stdin(self, message: Dict[str, Any]) -> None:
        if message["msg_type"] == INPUT_REQUEST:
            content = message["content"]
            self.input_requested.emit(content["prompt"], content["password"])
