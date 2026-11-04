"""Every operation of the bench, listed explicitly: MCP tools, the assistant's tools
and the CLI help are built from this list, and the daemon has one handler for each."""

from typing import Any, Dict, Tuple, Type

import msgspec

from thzdaq_api import (
    analysis,
    approvals,
    daemon,
    devices,
    events,
    leases,
    measurements,
    sessions,
    station,
)
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Operation

OPERATIONS: Tuple[Type[Operation], ...] = (
    devices.ListDevices,
    devices.DescribeDevice,
    devices.ReadDevice,
    devices.SetQuantity,
    devices.CallAction,
    devices.SafeState,
    devices.SubscribePoll,
    devices.CancelPoll,
    events.GetSnapshot,
    measurements.ListProcedures,
    measurements.DescribeProcedure,
    measurements.StartMeasurement,
    measurements.ListRuns,
    measurements.GetRunSnapshot,
    measurements.WaitMeasurement,
    measurements.SummarizeMeasurement,
    measurements.CancelMeasurement,
    measurements.AbortMeasurement,
    measurements.SetComment,
    sessions.StartSession,
    sessions.KeepSession,
    sessions.RecordSession,
    sessions.AdvanceSession,
    sessions.LogSession,
    sessions.PlotSession,
    sessions.RestoreOnExit,
    sessions.CallOnExit,
    sessions.EndSession,
    sessions.ParseSweep,
    station.GetStation,
    station.LoadStation,
    station.NewStation,
    station.UpdateStation,
    station.ListDrivers,
    station.ListConnectionKinds,
    station.ConnectInstrument,
    station.GetSisCalibration,
    station.SetSisCalibration,
    station.ListConnections,
    station.ResetConnection,
    leases.ListLeases,
    analysis.AnalyzeIv,
    approvals.ListApprovals,
    approvals.AnswerApproval,
    approvals.AskUser,
    approvals.WaitAnswer,
    daemon.GetDaemonStatus,
    daemon.GetDaemonSettings,
    daemon.SetDaemonSettings,
    daemon.ReadDaemonLog,
    daemon.ResetLane,
    daemon.StopDaemon,
    daemon.RestartDaemon,
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


def description(op: Type[Operation]) -> str:
    """What the operation does, for a model: its docstring in one paragraph."""
    return " ".join((op.__doc__ or "").split())


def tool_schema(op: Type[Operation]) -> Dict[str, Any]:
    """The arguments as a tool takes them (MCP, a model's tools): the object at
    the top, the types it refers to under $defs; the description goes apart."""
    found = schema(op)
    types = dict(found.get("$defs", {}))
    arguments = dict(types.pop(op.__name__))
    arguments.pop("title", None)
    arguments.pop("description", None)
    if types:
        arguments["$defs"] = types
    return arguments
