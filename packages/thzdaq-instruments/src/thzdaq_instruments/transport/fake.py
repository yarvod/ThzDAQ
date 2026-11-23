"""In-memory link for driver tests: records commands, answers from a script."""

import time
from collections import deque
from typing import Callable, Dict, List, Optional, Tuple, Union

from thzdaq_instruments.errors import InstrumentTimeoutError
from thzdaq_instruments.transport.base import Link, MessageTransport

Responder = Callable[[str], Optional[str]]
FrameResponder = Callable[[bytes], Optional[bytes]]


class FakeLink(Link):
    """Each written line may produce a reply that the next read returns.

    responses: {command: reply} or a callable command -> reply/None.
    frames: a callable written frame -> the bytes it answers, or None; they
    are read as a stream, by count.
    events: ("w", line) / ("r", reply) / ("wb", frame) / ("rb", bytes) in
    order, to check command sequences.
    """

    def __init__(
        self,
        responses: Union[Dict[str, str], Responder, None] = None,
        delay: float = 0.0,
        frames: Optional[FrameResponder] = None,
    ):
        super().__init__()
        if responses is None:
            responses = {}
        self._responder: Responder = responses if callable(responses) else responses.get
        self.delay = delay
        self.events: List[Tuple[str, str]] = []
        self.open_count = 0
        self.close_count = 0
        self._open = False
        self._replies = deque()
        self._frames = frames
        self._stream = b""

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def written(self) -> List[str]:
        return [line for kind, line in self.events if kind == "w"]

    @property
    def written_frames(self) -> List[bytes]:
        return [frame for kind, frame in self.events if kind == "wb"]

    def open(self) -> None:
        self._open = True
        self.open_count += 1

    def close(self) -> None:
        self._open = False
        self.close_count += 1
        self._replies.clear()  # like a socket: unread bytes go with it
        self._stream = b""

    def write_line(self, line: str) -> None:
        self.events.append(("w", line))
        if self.delay:
            time.sleep(self.delay)
        reply = self._responder(line)
        if reply is not None:
            self._replies.append(reply)

    def read_line(self) -> str:
        if self.delay:
            time.sleep(self.delay)
        if not self._replies:
            raise InstrumentTimeoutError("FakeLink: no reply queued")
        reply = self._replies.popleft()
        self.events.append(("r", reply))
        return reply

    def write_bytes(self, data: bytes) -> None:
        if self._frames is None:
            super().write_bytes(data)
        self.events.append(("wb", data))
        self._stream += self._frames(data) or b""

    def read_bytes(self, count: int) -> bytes:
        if len(self._stream) < count:
            raise InstrumentTimeoutError(f"FakeLink: {count} bytes not queued")
        data, self._stream = self._stream[:count], self._stream[count:]
        self.events.append(("rb", data))
        return data


def fake_transport(
    responses: Union[Dict[str, str], Responder, None] = None,
) -> Tuple[MessageTransport, FakeLink]:
    link = FakeLink(responses)
    link.open()
    return MessageTransport(link), link
