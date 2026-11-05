"""The tools an agent gets: operations of the catalog, each with its name, its
docstring and the JSON schema of its arguments (thzdaq_api.catalog), and the
short text it answers with.

The set is chosen: an agent looks at the bench, sets and calls with a person's
consent, asks an instrument a raw query with a person's consent, runs
measurements and follows them, asks the person. It does not edit the profile,
answer for a person, write raw commands or stop the daemon (those are a
person's, and the daemon would refuse them anyway), nor take what it cannot
use (polls, streams of records).
"""

from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional, Tuple, Type

import anyio
import anyio.from_thread
import anyio.lowlevel
import mcp_types as types
import msgspec
from thzdaq_api import approvals, catalog, daemon, devices, measurements, station
from thzdaq_api.events import Event, MeasurementProgress
from thzdaq_api.measurement_file import RUNNING
from thzdaq_api.operation import Operation, Rights

from thzdaq_mcp import present
from thzdaq_mcp.bench import Bench

# How a tool tells how far it is: (done, total, message)
Progress = Callable[[float, Optional[float], Optional[str]], Awaitable[None]]


class Tool:
    """An operation as a tool: called with its arguments, answered in text."""

    def __init__(self, operation: Type[Operation]):
        self.operation = operation

    @property
    def name(self) -> str:
        return self.operation.name

    def definition(self) -> types.Tool:
        return types.Tool(
            name=self.name,
            description=catalog.description(self.operation),
            input_schema=catalog.tool_schema(self.operation),
            annotations=types.ToolAnnotations(
                read_only_hint=self.operation.rights is Rights.READ,
                destructive_hint=False,
            ),
        )

    async def call(
        self, bench: Bench, args: Operation, progress: Optional[Progress]
    ) -> str:
        raise NotImplementedError


class Plain(Tool):
    """Called once, its result told by text()."""

    def __init__(self, operation: Type[Operation], text: Callable[..., str]):
        super().__init__(operation)
        self.text = text

    async def call(self, bench, args, progress):
        return self.text(await bench.call(args))


class Values(Tool):
    """A read or a set, answered with the units of the device's quantities."""

    async def call(self, bench, args, progress):
        result = await bench.call(args)
        described = await bench.call(devices.DescribeDevice(ref=result.ref))
        found = (
            result.values
            if isinstance(result, devices.Reading)
            else {result.key: result.value}
        )
        return present.values(result.ref, found, described)


class Procedure(Tool):
    """A procedure with the devices of the bench that suit each slot."""

    async def call(self, bench, args, progress):
        info = await bench.call(args)
        return present.procedure(info, await bench.call(devices.ListDevices()))


class Start(Plain):
    """A start goes to the agent's workspace unless it names another: the file
    lands in its data/, next to the agent's work (with none, in the
    program's)."""

    def __init__(self, workspace: Optional[Path]):
        super().__init__(measurements.StartMeasurement, present.run)
        self.workspace = workspace

    async def call(self, bench, args, progress):
        if args.workspace is None and self.workspace is not None:
            args = msgspec.structs.replace(args, workspace=str(self.workspace))
        return await super().call(bench, args, progress)


class Wait(Tool):
    """Waits for a measurement to end; tells its progress meanwhile when the
    client asked for it (a progress token), and answers with the summary of
    what it holds once it ended. A cancelled wait leaves it running."""

    async def call(self, bench, args, progress):
        now = await bench.call(msgspec.structs.replace(args, timeout=0.0))
        if now.status == RUNNING:
            if progress is None:
                now = await bench.call(args)
            else:
                await progress(now.done, now.total, None)
                now = await self._following(bench, args, progress)
        if now.status == RUNNING:
            return present.run(now)
        return present.summary(
            await bench.call(measurements.SummarizeMeasurement(id=now.id))
        )

    @staticmethod
    async def _following(
        bench: Bench, args: measurements.WaitMeasurement, progress: Progress
    ) -> measurements.RunInfo:
        loop = anyio.lowlevel.current_token()

        def heard(event: Event) -> None:
            """In the stream's thread: the progress goes out in the loop's."""
            body = event.body
            if isinstance(body, MeasurementProgress) and body.id == args.id:
                anyio.from_thread.run(progress, body.done, body.total, None, token=loop)

        stop = bench.listen(heard)
        try:
            return await bench.call(args)
        finally:
            stop()


def tools(workspace: Optional[Path]) -> Tuple[Tool, ...]:
    """The agent's tools; a measurement goes to the workspace unless named."""
    return (
        Plain(devices.ListDevices, present.devices),
        Plain(devices.DescribeDevice, present.description),
        Values(devices.ReadDevice),
        Values(devices.SetQuantity),
        Plain(devices.CallAction, present.action_result),
        Plain(devices.RawCommand, present.raw),
        Plain(station.ListConnections, present.connections),
        Plain(measurements.ListProcedures, present.procedures),
        Procedure(measurements.DescribeProcedure),
        Start(workspace),
        Wait(measurements.WaitMeasurement),
        Plain(measurements.SummarizeMeasurement, present.summary),
        Plain(measurements.CancelMeasurement, present.run),
        Plain(measurements.ListRuns, present.runs),
        Plain(approvals.AskUser, present.answer),
        Plain(approvals.WaitAnswer, present.answer),
        Plain(daemon.GetDaemonStatus, present.status),
    )


def by_name(found: Tuple[Tool, ...]) -> Dict[str, Tool]:
    return {tool.name: tool for tool in found}
