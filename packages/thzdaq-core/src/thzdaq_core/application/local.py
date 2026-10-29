"""LocalLab: the bench's use cases called in this process, through the same JSON a
remote call travels as, so it behaves as RemoteLab does (contract tests use both)."""

from typing import TypeVar

from thzdaq_api import wire
from thzdaq_api.operation import Operation

from thzdaq_core.application.dispatch import Dispatcher

R = TypeVar("R")


class LocalLab:
    def __init__(self, dispatcher: Dispatcher, origin: str = "local"):
        self.dispatcher = dispatcher
        self.origin = origin

    def call(self, operation: Operation[R]) -> R:
        data = self.dispatcher.dispatch_json(
            operation.name, wire.encode(operation), self.origin
        )
        return wire.decode_result(type(operation), data)
