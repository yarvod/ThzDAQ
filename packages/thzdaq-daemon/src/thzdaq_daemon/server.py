"""HTTP + SSE over the dispatcher, on 127.0.0.1 only.

POST /ops/<name> calls an operation (JSON in, JSON out, a Failure with an HTTP
status when it fails; X-Thzdaq-Seq names the last event when it ended).
GET /events streams the events from Last-Event-ID (or from now), with a
heartbeat when nothing happens. GET /health and /status tell about the daemon.

Every request carries the token of the host file; one with a foreign Host
(DNS rebinding) or with a browser's Origin is refused: a web page open on the
bench computer must not set a bias.
"""

import hmac
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

import msgspec
from thzdaq_api import wire
from thzdaq_api.daemon import ClientInfo, Health
from thzdaq_api.errors import ErrorCode, Failure, LabError
from thzdaq_api.events import Event
from thzdaq_api.transport import (
    CLIENT,
    EVENTS,
    HEALTH,
    HEARTBEAT,
    HEARTBEAT_S,
    JSON,
    LAST_EVENT,
    LOCALHOST,
    OPERATIONS,
    ORIGIN,
    PID,
    SEQ,
    STATUS,
    TOKEN,
    bearer,
    frame,
)
from thzdaq_core.application.clock import wall_time
from thzdaq_core.application.daemon import DaemonService
from thzdaq_core.application.dispatch import Dispatcher
from thzdaq_core.application.events import EventBus

logger = logging.getLogger(__name__)

HTTP_STATUS = {
    ErrorCode.INVALID_ARGUMENTS: 400,
    ErrorCode.UNKNOWN_OPERATION: 404,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.NOT_ALLOWED: 403,
    ErrorCode.INSTRUMENT: 502,
    ErrorCode.OUT_OF_LIMITS: 422,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INTERNAL: 500,
    ErrorCode.UNREACHABLE: 503,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.WRONG_VERSION: 400,
}
SOCKET_S = 10.0  # a client that takes no bytes this long is gone


class Clients:
    """Who listens to the events now; idle is how long nobody has."""

    def __init__(self):
        self._clients: Dict[int, ClientInfo] = {}
        self._next = 0
        self._lock = threading.Lock()
        self._left = time.monotonic()

    def add(self, client: ClientInfo) -> int:
        with self._lock:
            self._next += 1
            self._clients[self._next] = client
            return self._next

    def remove(self, key: int) -> None:
        with self._lock:
            self._clients.pop(key, None)
            if not self._clients:
                self._left = time.monotonic()

    def all(self) -> Tuple[ClientInfo, ...]:
        with self._lock:
            return tuple(self._clients.values())

    def idle_for(self) -> float:
        """Seconds since the last client left; 0 while one listens."""
        with self._lock:
            return 0.0 if self._clients else time.monotonic() - self._left


class Server(ThreadingHTTPServer):
    # Request threads are joined on close, so an operation that stops the
    # daemon still answers; streams end within a heartbeat once stopping
    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        dispatcher: Dispatcher,
        events: EventBus,
        service: DaemonService,
        token: str,
        health: Health,
        clients: Clients,
        port: int = 0,
    ):
        super().__init__((LOCALHOST, port), _Handler)
        self.dispatcher = dispatcher
        self.events = events
        self.service = service
        self.token = token
        self.health = health
        self.clients = clients
        self.stopping = threading.Event()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self) -> None:
        """Stop serving; the call that asked for it answers first."""
        self.stopping.set()
        self.events.wake()
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.0"
    timeout = SOCKET_S

    def log_message(self, format, *args) -> None:
        logger.debug(f"{self.address_string()} {format % args}")

    def do_GET(self) -> None:
        if not self._allowed():
            return
        if self.path == HEALTH:
            self._answer(200, msgspec.json.encode(self.server.health))
        elif self.path == STATUS:
            self._answer(200, msgspec.json.encode(self.server.service.status()))
        elif self.path == EVENTS:
            self._stream()
        else:
            self._fail(ErrorCode.NOT_FOUND, f"No {self.path}")

    def do_POST(self) -> None:
        if not self._allowed():
            return
        if not self.path.startswith(OPERATIONS):
            self._fail(ErrorCode.NOT_FOUND, f"No {self.path}")
            return
        name = self.path[len(OPERATIONS) :]
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        origin = self.headers.get(ORIGIN, "client")
        try:
            data = self.server.dispatcher.dispatch_json(name, body, origin)
        except LabError as e:
            self._answer(HTTP_STATUS[e.code], wire.encode(e.failure()))
        else:
            self._answer(200, data)

    def _allowed(self) -> bool:
        port = self.server.port
        if self.headers.get("Host") not in (f"{LOCALHOST}:{port}", f"localhost:{port}"):
            self._fail(ErrorCode.NOT_ALLOWED, "Not for this host")
            return False
        if self.headers.get("Origin") is not None:
            self._fail(ErrorCode.NOT_ALLOWED, "Not for a web page")
            return False
        given = self.headers.get(TOKEN, "")
        if not hmac.compare_digest(given.encode(), bearer(self.server.token).encode()):
            self._fail(ErrorCode.UNAUTHORIZED, "Not this daemon's token")
            return False
        return True

    def _answer(self, status: int, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", JSON)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(SEQ, str(self.server.events.seq))
        self.end_headers()
        self.wfile.write(data)

    def _fail(self, code: ErrorCode, message: str) -> None:
        self._answer(HTTP_STATUS[code], wire.encode(Failure(code, message)))

    def _stream(self) -> None:
        events = self.server.events
        last = self.headers.get(LAST_EVENT)
        position = events.seq if last is None else int(last)
        client = ClientInfo(
            kind=self.headers.get(CLIENT, "client"),
            pid=int(self.headers.get(PID, 0)),
            origin=self.headers.get(ORIGIN, "client"),
            since=wall_time(),
        )
        key = self.server.clients.add(client)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            # What the client missed first, then a heartbeat: it is caught up
            position = self._send(events.wait(position, 0), position)
            self._beat(position)
            while not self.server.stopping.is_set():
                found = events.wait(position, HEARTBEAT_S)
                if found:
                    position = self._send(found, position)
                else:
                    self._beat(position)
        except OSError:
            pass  # the client went
        finally:
            self.server.clients.remove(key)

    def _send(self, found: List[Event], position: int) -> int:
        for event in found:
            self.wfile.write(_frame(event))
        self.wfile.flush()
        return found[-1].seq if found else position

    def _beat(self, position: int) -> None:
        beat = self.server.service.heartbeat(position)
        self.wfile.write(b": ping\n\n" + frame(HEARTBEAT, msgspec.json.encode(beat)))
        self.wfile.flush()


def _frame(event: Event) -> bytes:
    kind: Optional[str] = type(event.body).__struct_config__.tag
    return frame(kind or "", wire.encode(event), event.seq)
