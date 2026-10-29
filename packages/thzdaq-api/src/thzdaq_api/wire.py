"""Operations, results and failures as JSON: one codec for the daemon, its clients
and LocalLab, so a call in the same process goes through what a remote one does."""

from typing import Any, Type

import msgspec

from thzdaq_api import catalog
from thzdaq_api.errors import ErrorCode, Failure, LabError
from thzdaq_api.operation import Operation


def encode(value: Any) -> bytes:
    return msgspec.json.encode(value)


def decode_arguments(name: str, data: bytes) -> Operation:
    op = catalog.operation(name)
    try:
        return msgspec.json.decode(data, type=op)
    except msgspec.ValidationError as e:
        raise LabError(ErrorCode.INVALID_ARGUMENTS, f"{name}: {e}") from None


def decode_result(op: Type[Operation], data: bytes) -> Any:
    return msgspec.json.decode(data, type=op.result_type())


def decode_failure(data: bytes) -> LabError:
    return LabError.from_failure(msgspec.json.decode(data, type=Failure))
