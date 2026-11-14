"""The one way into the use cases: an operation goes to its handler, and what
goes wrong comes back as a LabError with a code clients can act on.

The policy comes first: a call its origin may not make is denied, one that
needs a person waits for the answer (outside every lock) and goes on as the
person allowed it, perhaps with another value. A call a person allowed already
(inside a script's session) is asked again only for a dangerous step or
another measurement's sweep.
"""

import functools
import logging
from typing import Any, Dict, Iterable, Type

from thzdaq_api import catalog, wire
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.lanes import LaneReset
from thzdaq_api.operation import Operation
from thzdaq_api.rights import Decision
from thzdaq_instruments.errors import InstrumentError, LimitError

from thzdaq_core.application.approvals import Approvals
from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.policy import Policy

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(
        self, handlers: Iterable[Handler], policy: Policy, approvals: Approvals
    ):
        self.policy = policy
        self.approvals = approvals
        self.handlers: Dict[Type[Operation], Handler] = {}
        for handler in handlers:
            if handler.operation in self.handlers:
                raise ValueError(f"Two handlers for {handler.operation.name}")
            self.handlers[handler.operation] = handler

    def dispatch(self, args: Operation, origin: str) -> Any:
        handler = self.handlers.get(type(args))
        if handler is None:
            raise LabError(ErrorCode.UNKNOWN_OPERATION, f"{args.name} has no handler")
        try:
            return handler.handle(self._allowed(handler, args, origin), origin)
        except LabError:
            raise
        except LimitError as e:
            raise LabError(ErrorCode.OUT_OF_LIMITS, str(e)) from e
        except (InstrumentError, LaneReset) as e:
            raise LabError(ErrorCode.INSTRUMENT, str(e)) from e
        except Exception as e:
            logger.exception(f"{args.name} failed ({origin})")
            raise LabError(ErrorCode.INTERNAL, f"{args.name} failed: {e}") from e

    def _allowed(self, handler: Handler, args: Operation, origin: str) -> Operation:
        """The call as it may go, or LabError DENIED with the reason."""
        # Each made once, if needed
        ask = functools.cache(lambda: handler.approval(args, origin))
        granted = functools.cache(lambda: handler.granted(args, origin))
        decision = self.policy.decide(
            handler.needs(args),
            origin,
            lambda: ask().grave if granted() else ask().risky,
            granted,
        )
        if decision is Decision.DENY:
            raise LabError(
                ErrorCode.DENIED,
                f"{args.name} is not for {origin}",
                "a person does it in the ThzDAQ window",
            )
        if decision is Decision.ALLOW:
            return args
        answer = self.approvals.ask(ask(), args.name, origin)
        if not answer.allowed:
            raise LabError(
                ErrorCode.DENIED,
                f"{args.name} not allowed: {answer.text or 'no reason given'}",
                "the person's words say what to do instead",
            )
        return handler.amended(args, answer)

    def dispatch_json(self, name: str, data: bytes, origin: str) -> bytes:
        """An operation and its result as JSON, as they travel."""
        args = wire.decode_arguments(name, data)
        result = self.dispatch(args, origin)
        return wire.encode(result)

    def missing(self) -> Iterable[Type[Operation]]:
        """Operations of the contract no handler serves."""
        return [op for op in catalog.OPERATIONS if op not in self.handlers]
