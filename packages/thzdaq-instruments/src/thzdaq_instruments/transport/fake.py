"""In-memory link for driver tests: records commands, answers from a script."""

import time
from collections import deque
from typing import Callable, Dict, List, Optional, Tuple, Union

from thzdaq_instruments.errors import InstrumentTimeoutError
from thzdaq_instruments.transport.base import Link, MessageTransport

Responder = Callable[[str], Optional[str]]


class FakeLink(Link):
    """Each written line may produce a reply that the next read returns.

    responses: {command: reply} or a callable command -> reply/None.
    events: ("w", line) / ("r", reply) in order, to check command sequences.
    """

    def __init__(
        self,
        responses: Union[Dict[str, str], Responder, None] = None,
        delay: float = 0.0,
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

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def written(self) -> List[str]:
        return [line for kind, line in self.events if kind == "w"]

    def open(self) -> None:
        self._open = True
        self.open_count += 1

    def close(self) -> None:
        self._open = False
        self.close_count += 1
        self._replies.clear()  # like a socket: unread bytes go with it

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


def fake_transport(
    responses: Union[Dict[str, str], Responder, None] = None,
) -> Tuple[MessageTransport, FakeLink]:
    link = FakeLink(responses)
    link.open()
    return MessageTransport(link), link
