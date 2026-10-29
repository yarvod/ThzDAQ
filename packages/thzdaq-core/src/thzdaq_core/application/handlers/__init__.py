"""Use cases: one handler per operation of the contract (thzdaq_api.catalog).

A handler is stateless: what it needs comes in its constructor, so the
dispatcher may call it from many threads at once.
"""

from typing import ClassVar, Generic, Type, TypeVar

from thzdaq_api.operation import Operation

A = TypeVar("A", bound=Operation)
R = TypeVar("R")


class Handler(Generic[A, R]):
    operation: ClassVar[Type[Operation]]

    def handle(self, args: A, origin: str) -> R:
        """origin: who calls (gui, cli, mcp:<name>, assistant, script:<name>)."""
        raise NotImplementedError
