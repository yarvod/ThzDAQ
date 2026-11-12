"""The tools of agents and of the assistant in the window: operations of the
catalog, each with its name, its docstring and the JSON schema of its arguments
(thzdaq_api.catalog), and the short text it answers with (present.py). The MCP
server (thzdaq-mcp) hands them to an agent, the assistant to its model: both
get the same set.

The set is chosen: an agent looks at the bench, sets and calls with a person's
consent, asks an instrument a raw query with a person's consent, runs
measurements and follows them, reads, checks and (with a person's consent)
writes the bench's own measurements, asks the person, and shows the person
where things are in the window (opens, fills a form, highlights). It does not edit the profile,
answer for a person, write raw commands or stop the daemon (those are a
person's, and the daemon would refuse them anyway), nor take what it cannot
use (polls, streams of records).

A tool is called in a thread of its own and waits as its operation does (for a
person, for a measurement); a client that must not wait runs it apart.
"""

import threading
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

import msgspec

from thzdaq_api import (
    approvals,
    catalog,
    custom,
    daemon,
    devices,
    measurements,
    present,
    station,
    ui,
    wire,
)
from thzdaq_api.events import Event, MeasurementProgress
from thzdaq_api.lab import Lab
from thzdaq_api.measurement_file import RUNNING
from thzdaq_api.operation import Operation, Rights

R = TypeVar("R")

# How a tool tells how far it is: (done, total, message); called in the
# thread of the events
Progress = Callable[[float, Optional[float], Optional[str]], None]
Listener = Callable[[Event], None]  # runs in the thread of the events


class Reach:
    """The bench as an agent reaches it: its calls, and its events heard
    through one subscription by every tool that listens. While it lives the
    daemon lists the agent among its clients (the kind its lab listens as)
    and stays while the agent works."""

    def __init__(self, lab: Lab):
        self.lab = lab
        self._listeners: List[Listener] = []
        self._lock = threading.Lock()
        self._stop = lab.subscribe(self._heard)

    def _heard(self, event: Event) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            listener(event)

    def listen(self, listener: Listener) -> Callable[[], None]:
        """Hear the events from now on; returns what stops it."""
        with self._lock:
            self._listeners.append(listener)

        def stop() -> None:
            with self._lock:
                self._listeners.remove(listener)

        return stop

    def call(self, operation: Operation[R]) -> R:
        return self.lab.call(operation)

    def close(self) -> None:
        self._stop()


class Tool:
    """An operation as a tool: called with its arguments, answered in text."""

    def __init__(self, operation: Type[Operation]):
        self.operation = operation

    @property
    def name(self) -> str:
        return self.operation.name

    def description(self) -> str:
        return catalog.description(self.operation)

    def schema(self) -> Dict[str, Any]:
        return catalog.tool_schema(self.operation)

    @property
    def reads(self) -> bool:
        """It changes nothing."""
        return self.operation.rights is Rights.READ

    def arguments(self, given: Mapping[str, Any]) -> Operation:
        """The arguments as a model or an agent gave them, checked; LabError
        INVALID_ARGUMENTS says what is wrong."""
        return wire.decode_arguments(self.name, wire.encode(dict(given)))

    def call(self, reach: Reach, args: Operation, progress: Optional[Progress]) -> str:
        raise NotImplementedError


class Plain(Tool):
    """Called once, its result told by text()."""

    def __init__(self, operation: Type[Operation], text: Callable[..., str]):
        super().__init__(operation)
        self.text = text

    def call(self, reach, args, progress):
        return self.text(reach.call(args))


class Values(Tool):
    """A read or a set, answered with the units of the device's quantities."""

    def call(self, reach, args, progress):
        result = reach.call(args)
        described = reach.call(devices.DescribeDevice(ref=result.ref))
        found = (
            result.values
            if isinstance(result, devices.Reading)
            else {result.key: result.value}
        )
        return present.values(result.ref, found, described)


class Procedure(Tool):
    """A procedure with the devices of the bench that suit each slot."""

    def call(self, reach, args, progress):
        info = reach.call(args)
        return present.procedure(info, reach.call(devices.ListDevices()))


class Start(Plain):
    """A start goes to the agent's workspace unless it names another: the file
    lands in its data/, next to the agent's work (with none, in the
    program's). workspace() is asked at each start: a window's may change."""

    def __init__(self, workspace: Callable[[], Optional[Path]]):
        super().__init__(measurements.StartMeasurement, present.run)
        self.workspace = workspace

    def call(self, reach, args, progress):
        folder = self.workspace()
        if args.workspace is None and folder is not None:
            args = msgspec.structs.replace(args, workspace=str(folder))
        return super().call(reach, args, progress)


class Wait(Tool):
    """Waits for a measurement to end; tells its progress meanwhile when asked
    to, and answers with the summary of what it holds once it ended."""

    def call(self, reach, args, progress):
        now = reach.call(msgspec.structs.replace(args, timeout=0.0))
        if now.status == RUNNING:
            if progress is None:
                now = reach.call(args)
            else:
                progress(now.done, now.total, None)
                now = self._following(reach, args, progress)
        if now.status == RUNNING:
            return present.run(now)
        return present.summary(reach.call(measurements.SummarizeMeasurement(id=now.id)))

    @staticmethod
    def _following(
        reach: Reach, args: measurements.WaitMeasurement, progress: Progress
    ) -> measurements.RunInfo:
        def heard(event: Event) -> None:
            body = event.body
            if isinstance(body, MeasurementProgress) and body.id == args.id:
                progress(body.done, body.total, None)

        stop = reach.listen(heard)
        try:
            return reach.call(args)
        finally:
            stop()


class Shown(Tool):
    """Asks a window of the person (thzdaq_api.ui). The assistant of a window
    always asks its own (window() gives its id) and its model sees no window
    to choose; an agent beside the window asks the one it names, else the
    one the person was at last. text(args, result) tells what was done."""

    def __init__(
        self,
        operation: Type[Operation],
        text: Callable[[Operation, Any], str],
        window: Callable[[], Optional[str]],
    ):
        super().__init__(operation)
        self.text = text
        self.window = window

    def schema(self):
        found = super().schema()
        if self.window() is not None:
            properties = dict(found["properties"])
            properties.pop("window")
            found = {**found, "properties": properties}
        return found

    def call(self, reach, args, progress):
        own = self.window()
        if own is not None:
            args = msgspec.structs.replace(args, window=own)
        return self.text(args, reach.call(args))


def tools(
    workspace: Callable[[], Optional[Path]],
    window: Callable[[], Optional[str]] = lambda: None,
) -> Tuple[Tool, ...]:
    """The tools; a measurement goes to workspace() unless named, what is
    shown in a window to window() when it gives one (the assistant's own)."""
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
        Plain(custom.ListCustom, present.library),
        Plain(custom.ReadCustom, present.custom_text),
        Plain(custom.CheckCustom, present.check),
        Plain(custom.WriteCustom, present.check),
        Plain(approvals.AskUser, present.answer),
        Plain(approvals.WaitAnswer, present.answer),
        Shown(ui.UiState, lambda args, found: present.window(found), window),
        Shown(ui.UiOpen, lambda args, _: present.opened(args.place), window),
        Shown(ui.UiFillMeasurement, lambda args, found: present.form(found), window),
        Shown(ui.UiHighlight, lambda args, _: present.highlighted(args.anchor), window),
        Plain(daemon.GetDaemonStatus, present.status),
    )


def by_name(found: Tuple[Tool, ...]) -> Dict[str, Tool]:
    return {tool.name: tool for tool in found}
