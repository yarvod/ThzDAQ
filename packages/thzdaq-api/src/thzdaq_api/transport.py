"""HTTP between a client and the daemon: one request, and the frames of the
event stream (server-sent events). Only 127.0.0.1, only with the token."""

import http.client
from dataclasses import dataclass
from typing import Dict, Iterator, Optional, Tuple

from thzdaq_api.errors import ErrorCode, LabError

LOCALHOST = "127.0.0.1"
# Headers of the contract
TOKEN = "Authorization"
ORIGIN = "X-Thzdaq-Origin"  # who calls: gui, cli, mcp:<name>, assistant
CLIENT = "X-Thzdaq-Client"  # what kind of client listens
PID = "X-Thzdaq-Pid"
WINDOW = "X-Thzdaq-Window"  # the id of the main window a client is (thzdaq_api.ui)
SEQ = "X-Thzdaq-Seq"  # the last event when an operation ended
LAST_EVENT = "Last-Event-ID"

HEALTH = "/health"
STATUS = "/status"
EVENTS = "/events"
OPERATIONS = "/ops/"
HEARTBEAT = "heartbeat"  # the event type of the stream's heartbeats
JSON = "application/json"  # operations, answers and failures
HEARTBEAT_S = 2.0


def bearer(token: str) -> str:
    return f"Bearer {token}"


def request(
    port: int,
    token: str,
    method: str,
    path: str,
    body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> Tuple[int, Dict[str, str], bytes]:
    """(status, headers, body); LabError UNREACHABLE when nothing answers."""
    connection = http.client.HTTPConnection(LOCALHOST, port, timeout=timeout)
    try:
        sent = {TOKEN: bearer(token), "Content-Type": JSON, **(headers or {})}
        connection.request(method, path, body, sent)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    except OSError as e:
        raise LabError(
            ErrorCode.UNREACHABLE,
            f"The daemon on port {port} does not answer: {e}",
            "is it running? connect_or_start() starts it",
        ) from None
    finally:
        connection.close()


@dataclass
class Frame:
    """One message of the event stream."""

    event: str = ""
    data: str = ""
    id: Optional[str] = None


def frames(lines: Iterator[bytes]) -> Iterator[Frame]:
    """Frames of an event stream from its lines; comments (": ping") are skipped."""
    frame = Frame()
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if frame.event or frame.data:
                yield frame
            frame = Frame()
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "event":
                frame.event = value
            elif field == "data":
                frame.data = f"{frame.data}\n{value}" if frame.data else value
            elif field == "id":
                frame.id = value


def frame(event: str, data: bytes, id: Optional[int] = None) -> bytes:
    """A frame as the daemon writes it; data is one line of JSON."""
    head = f"id: {id}\n" if id is not None else ""
    return f"{head}event: {event}\ndata: ".encode() + data + b"\n\n"
