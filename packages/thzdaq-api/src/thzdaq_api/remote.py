"""RemoteLab: the bench in the daemon, over HTTP. Operations are POSTed as JSON,
events come on a stream (SSE) read by a thread per subscription.

When call() returns, every subscription has heard the events the operation
caused (the daemon names its last event in the answer), so a client sees the
change it made as everyone else does, in the same order. A stream that breaks
reconnects with the number of the last event it heard and gets what it missed,
or Resync when the daemon no longer has it. A restarted daemon serves on
another port: the lab finds it again by its host file (find), and its
listeners get Resync, since the new daemon numbers its events anew.
"""

import http.client
import os
import socket
import threading
from typing import Callable, List, Optional, TypeVar

import msgspec

from thzdaq_api import wire
from thzdaq_api.daemon import Health, Heartbeat, HostInfo
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import Event, Resync
from thzdaq_api.operation import Operation
from thzdaq_api.transport import (
    CLIENT,
    EVENTS,
    HEALTH,
    HEARTBEAT,
    HEARTBEAT_S,
    LAST_EVENT,
    LOCALHOST,
    OPERATIONS,
    ORIGIN,
    PID,
    SEQ,
    TOKEN,
    WINDOW,
    bearer,
    frames,
    request,
)

R = TypeVar("R")

CATCH_UP_S = 5.0  # how long call() waits for its events to be heard
SILENT_S = 3 * HEARTBEAT_S  # a stream silent this long is broken: reconnect
RECONNECT_S = (0.5, 5.0)  # first and longest pause before reconnecting


def health(host: HostInfo, timeout: float = 1.0) -> Optional[Health]:
    """What the daemon of a host file says about itself; None if it does not answer."""
    try:
        status, _, data = request(host.port, host.token, "GET", HEALTH, timeout=timeout)
    except LabError:
        return None
    if status != 200:
        return None
    return msgspec.json.decode(data, type=Health)


Find = Callable[[], Optional[HostInfo]]  # where the daemon serves now


class RemoteLab:
    def __init__(
        self,
        host: HostInfo,
        origin: str = "client",
        kind: str = "client",
        find: Optional[Find] = None,
        window: str = "",
    ):
        """window: the id of the main window this client is (thzdaq_api.ui),
        told with its event streams: the daemon sends it what agents ask of
        the window."""
        self.host = host
        self.origin = origin
        self.kind = kind
        self.find = find
        self.window = window
        self.heartbeat: Optional[Heartbeat] = None  # the last one heard
        self._streams: List["_Stream"] = []
        self._lock = threading.Lock()

    def call(self, operation: Operation[R]) -> R:
        asked = self.host
        try:
            status, headers, data = self._post(asked, operation)
        except LabError as e:
            if e.code != ErrorCode.UNREACHABLE or self.current_host().pid == asked.pid:
                raise
            # The daemon restarted: the old one is gone, the new one is asked
            status, headers, data = self._post(self.host, operation)
        if status != 200:
            raise wire.decode_failure(data)
        with self._lock:
            streams = list(self._streams)
        for stream in streams:
            stream.wait_for(int(headers[SEQ]), CATCH_UP_S)
        return wire.decode_result(type(operation), data)

    def _post(self, host: HostInfo, operation: Operation):
        return request(
            host.port,
            host.token,
            "POST",
            OPERATIONS + operation.name,
            wire.encode(operation),
            {ORIGIN: self.origin},
        )

    def current_host(self) -> HostInfo:
        """Where the daemon serves now, as its host file says when it is known."""
        if self.find is not None:
            found = self.find()
            if found is not None:
                self.host = found
        return self.host

    def subscribe(
        self, listener: Callable[[Event], None], since: Optional[int] = None
    ) -> Callable[[], None]:
        stream = _Stream(self, listener, since)
        with self._lock:
            self._streams.append(stream)
        stream.start()
        stream.wait_connected(CATCH_UP_S)
        return lambda: self._stop(stream)

    def close(self) -> None:
        with self._lock:
            streams = list(self._streams)
        for stream in streams:
            self._stop(stream)

    def _stop(self, stream: "_Stream") -> None:
        stream.stop()
        with self._lock:
            if stream in self._streams:
                self._streams.remove(stream)


class _Stream:
    """One subscription: a thread reading the event stream, reconnecting."""

    def __init__(
        self, lab: RemoteLab, listener: Callable[[Event], None], since: Optional[int]
    ):
        self.lab = lab
        self.listener = listener
        self.seq = since  # the last event heard
        self.pid: Optional[int] = None  # the daemon heard
        self.connected = False
        self.caught_up = False  # the first heartbeat: what was missed is heard
        self._heard = threading.Condition()
        self._stopped = threading.Event()
        self._connection: Optional[http.client.HTTPConnection] = None
        self._socket: Optional[socket.socket] = None
        self._thread = threading.Thread(target=self._run, name="events", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        sock = self._socket
        if sock is not None:
            # The reader blocks on the socket: shutting it down wakes it
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # already closed by the other side
        with self._heard:
            self._heard.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(2.0)

    def wait_connected(self, timeout: float) -> None:
        """Until the daemon has answered (its first heartbeat), or timeout."""
        with self._heard:
            self._heard.wait_for(
                lambda: self.caught_up or self._stopped.is_set(), timeout
            )

    def wait_for(self, seq: int, timeout: float) -> None:
        """Until this stream has heard event seq (or it is down: nothing to wait for)."""
        with self._heard:
            self._heard.wait_for(
                lambda: not self.connected
                or self._stopped.is_set()
                or (self.seq is not None and self.seq >= seq),
                timeout,
            )

    def _run(self) -> None:
        pause = RECONNECT_S[0]
        while not self._stopped.is_set():
            try:
                self._listen()
                pause = RECONNECT_S[0]
            except (OSError, http.client.HTTPException, LabError):
                pass  # the daemon went or restarts: try again after a pause
            finally:
                self._down()
            if self._stopped.wait(pause):
                return
            pause = min(pause * 2, RECONNECT_S[1])

    def _listen(self) -> None:
        host = self.lab.current_host()
        if self.pid is not None and host.pid != self.pid:
            self.seq = None  # a new daemon numbers its events anew
            self.listener(Event(0, "", Resync()))
        self.pid = host.pid
        headers = {
            TOKEN: bearer(host.token),
            CLIENT: self.lab.kind,
            ORIGIN: self.lab.origin,
            PID: str(os.getpid()),
        }
        if self.lab.window:
            headers[WINDOW] = self.lab.window
        if self.seq is not None:
            headers[LAST_EVENT] = str(self.seq)
        self._connection = http.client.HTTPConnection(
            LOCALHOST, host.port, timeout=SILENT_S
        )
        self._connection.connect()
        # The response takes the socket over; stop() needs it to wake the reader
        self._socket = self._connection.sock
        self._connection.request("GET", EVENTS, headers=headers)
        response = self._connection.getresponse()
        if response.status != 200:
            raise wire.decode_failure(response.read())
        for frame in frames(iter(response.readline, b"")):
            if self._stopped.is_set():
                return
            if frame.event == HEARTBEAT:
                beat = msgspec.json.decode(frame.data, type=Heartbeat)
                self.lab.heartbeat = beat
                self.caught_up = True
                self._heard_up_to(beat.seq)
                continue
            event = wire.decode_event(frame.data.encode())
            self.listener(event)
            self._heard_up_to(event.seq)
        if not self._stopped.is_set():
            raise LabError(ErrorCode.UNREACHABLE, "The event stream ended")

    def _heard_up_to(self, seq: int) -> None:
        with self._heard:
            self.connected = True
            self.seq = seq if self.seq is None else max(self.seq, seq)
            self._heard.notify_all()

    def _down(self) -> None:
        with self._heard:
            self.connected = False
            self._heard.notify_all()
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
