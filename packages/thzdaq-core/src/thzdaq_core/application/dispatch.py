"""The one way into the use cases: an operation goes to its handler, and what
goes wrong comes back as a LabError with a code clients can act on."""

import logging
from typing import Any, Dict, Iterable, Type

from thzdaq_api import catalog, wire
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Operation
from thzdaq_instruments.errors import InstrumentError, LimitError

from thzdaq_core.application.handlers import Handler

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, handlers: Iterable[Handler]):
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
            return handler.handle(args, origin)
        except LabError:
            raise
        except LimitError as e:
            raise LabError(ErrorCode.OUT_OF_LIMITS, str(e)) from e
        except InstrumentError as e:
            raise LabError(ErrorCode.INSTRUMENT, str(e)) from e
        except Exception as e:
            logger.exception(f"{args.name} failed ({origin})")
            raise LabError(ErrorCode.INTERNAL, f"{args.name} failed: {e}") from e

    def dispatch_json(self, name: str, data: bytes, origin: str) -> bytes:
        """An operation and its result as JSON, as they travel."""
        args = wire.decode_arguments(name, data)
        result = self.dispatch(args, origin)
        return wire.encode(result)

    def missing(self) -> Iterable[Type[Operation]]:
        """Operations of the contract no handler serves."""
        return [op for op in catalog.OPERATIONS if op not in self.handlers]
