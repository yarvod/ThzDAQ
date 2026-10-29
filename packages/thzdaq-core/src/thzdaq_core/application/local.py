"""LocalLab: the bench's use cases called in this process, through the same JSON a
remote call travels as, so it behaves as RemoteLab does (contract tests use both)."""

from typing import Callable, Optional, TypeVar

from thzdaq_api import wire
from thzdaq_api.events import Event
from thzdaq_api.operation import Operation

from thzdaq_core.application.assembly import Assembled

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
        return self.events.subscribe(
            lambda event: listener(wire.decode_event(wire.encode(event))), since
        )
