"""The bench as a client sees it: operations called by their arguments, events
heard as they happen.

RemoteLab calls the daemon; LocalLab (thzdaq-core) calls its use cases in the
same process. Both raise LabError when an operation fails.
"""

from typing import Callable, Optional, Protocol, TypeVar

from thzdaq_api.events import Event
from thzdaq_api.operation import Operation

R = TypeVar("R")


class Lab(Protocol):
    origin: str  # who calls (gui, cli, mcp:<name>); the runs it starts carry it

    def call(self, operation: Operation[R]) -> R:
        ...

    def subscribe(
        self, listener: Callable[[Event], None], since: Optional[int] = None
    ) -> Callable[[], None]:
        """Hear every event after `since` (a snapshot's seq; None: from now);
        returns what stops it. The listener runs in the lab's thread: it hands
        the event on (a Qt signal, a queue) and returns."""
        ...
