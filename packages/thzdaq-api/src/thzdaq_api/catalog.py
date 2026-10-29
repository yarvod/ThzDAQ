"""Every operation of the bench, listed explicitly: MCP tools, the assistant's tools
and the CLI help are built from this list, and the daemon has one handler for each."""

from typing import Any, Dict, Tuple, Type

import msgspec

from thzdaq_api import devices
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Operation

OPERATIONS: Tuple[Type[Operation], ...] = (
    devices.ListDevices,
    devices.DescribeDevice,
    devices.ReadDevice,
    devices.SetQuantity,
)
BY_NAME: Dict[str, Type[Operation]] = {op.name: op for op in OPERATIONS}


def operation(name: str) -> Type[Operation]:
    try:
        return BY_NAME[name]
    except KeyError:
        raise LabError(
            ErrorCode.UNKNOWN_OPERATION,
            f"No operation {name!r}",
            f"known: {', '.join(sorted(BY_NAME))}",
        ) from None


def schema(op: Type[Operation]) -> Dict[str, Any]:
    """JSON schema of the arguments; its description is the operation's docstring."""
    return msgspec.json.schema(op)
