"""Use cases: one handler per operation of the contract (thzdaq_api.catalog).

A handler is stateless: what it needs comes in its constructor, so the
dispatcher may call it from many threads at once. It also tells what a call
needs (the rights of its operation, fewer for one that changes nothing) and,
when an agent's call waits for a person, what the person reads and what the
call becomes once allowed.
"""

from typing import ClassVar, Generic, Type, TypeVar

import msgspec
from thzdaq_api.approvals import Answer
from thzdaq_api.operation import Operation, Rights

from thzdaq_core.application.approvals import Ask

A = TypeVar("A", bound=Operation)
R = TypeVar("R")


class Handler(Generic[A, R]):
    operation: ClassVar[Type[Operation]]

    def handle(self, args: A, origin: str) -> R:
        """origin: who calls (gui, cli, mcp:<name>, assistant, script:<name>)."""
        raise NotImplementedError

    def needs(self, args: A) -> Rights:
        return self.operation.rights

    def approval(self, args: A) -> Ask:
        """What a person reads to allow this call; it may refuse a call that
        could not go anyway, before anybody is asked."""
        given = msgspec.structs.asdict(args)
        return Ask(
            args.name.replace("_", " ").capitalize(),
            ", ".join(f"{key} {value}" for key, value in given.items()) or args.name,
        )

    def amended(self, args: A, answer: Answer) -> A:
        """The call as the person allowed it."""
        return args
