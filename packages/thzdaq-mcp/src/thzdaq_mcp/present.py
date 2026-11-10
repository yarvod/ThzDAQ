"""What an agent reads back: short text, values with their units, no arrays.

Values travel in SI (power in dBm); each is shown with the prefix that keeps
it from 1 to 999 ("2.3 mV"), as the daemon reads it back when it is typed.
"""

from typing import Iterable, Mapping, Optional, Sequence, Tuple

from thzdaq_api.approvals import UserAnswer
from thzdaq_api.custom import CustomCheck, CustomLibrary, CustomText
from thzdaq_api.daemon import DaemonStatus
from thzdaq_api.devices import (
    ActionInfo,
    ActionResult,
    DeviceDescription,
    DeviceInfo,
    Prefix,
    QuantityInfo,
    RawReply,
    Trace,
    Value,
    shown,
)
from thzdaq_api.measurement_file import RUNNING
from thzdaq_api.measurements import (
    ColumnSummary,
    MeasurementSummary,
    ParameterInfo,
    ProcedureInfo,
    ProcedureSummary,
    RunInfo,
)
from thzdaq_api.station import ConnectionInfo

NOTHING = "none"


def lines(found: Iterable[str]) -> str:
    return "\n".join(found) or NOTHING


def devices(found: Sequence[DeviceInfo]) -> str:
    return lines(
        f"{d.ref}: {d.title} ({d.type} on {d.instrument}; {', '.join(d.capabilities)})"
        for d in found
    )


def span(
    low: Optional[float],
    high: Optional[float],
    unit: str,
    prefixes: Sequence[Prefix],
) -> str:
    """ "-30 mV..30 mV"; empty when neither end is known."""
    if low is None and high is None:
        return ""
    return f"{shown(low, unit, prefixes)}..{shown(high, unit, prefixes)}"


def quantity(q: QuantityInfo) -> str:
    def value(found: Optional[float]) -> str:
        return shown(found, q.unit, q.prefixes)

    text = f"{q.key}: {q.label}"
    if q.kind != "float":
        text += f" ({q.kind}{': ' + ', '.join(q.choices) if q.choices else ''})"
    if not q.settable:
        return text + "; read only"
    text += "; settable"
    taken = span(q.minimum, q.maximum, q.unit, q.prefixes)
    if taken:
        text += f" {taken}"
    usual = span(q.warn_minimum, q.warn_maximum, q.unit, q.prefixes)
    if usual:
        text += f", a person is asked beyond {usual}"
    if q.step is not None:
        rate = f" at {value(q.rate)}/s" if q.rate is not None else ""
        text += f", in steps of {value(q.step)}{rate}"
    if q.danger:
        text += f"; DANGER: {q.danger}"
    return text


def action(a: ActionInfo) -> str:
    arguments = ", ".join(
        f"{arg.key}{': ' + arg.unit if arg.unit else ''}"
        + (
            ""
            if arg.default is None
            else f" = {shown(arg.default, arg.unit, arg.prefixes)}"
        )
        for arg in a.arguments
    )
    text = f"{a.key}({arguments}): {a.title}"
    if a.help:
        text += f". {a.help}"
    if not a.changes:
        text += " (a read)"
    if a.danger:
        text += f"; DANGER: {a.danger}"
    return text


def description(d: DeviceDescription) -> str:
    device = d.device
    parts = [
        f"{device.ref}: {device.title} ({device.type} on {device.instrument})",
        "quantities (key: title, unit):",
        *(f"  {quantity(q)}" for q in d.quantities),
    ]
    if d.actions:
        parts += ["actions (call_action):", *(f"  {action(a)}" for a in d.actions)]
    if d.settings:
        parts += ["settings in the profile:", *(f"  {quantity(q)}" for q in d.settings)]
    return "\n".join(parts)


def values(ref: str, found: Mapping[str, Value], description: DeviceDescription) -> str:
    known = {q.key: q for q in description.quantities}

    def value(key: str, given: Value) -> str:
        q = known.get(key)
        return shown(given, q.unit, q.prefixes) if q else shown(given)

    return f"{ref}: " + ", ".join(f"{k} = {value(k, v)}" for k, v in found.items())


def trace(found: Trace) -> str:
    """A trace by its ends and its peak: the agent reads the file for more."""
    points = len(found.frequency)
    if not points:
        return "an empty trace"
    peak = max(range(points), key=lambda i: found.values[i])
    label = found.label()
    return (
        f"{found.parameter + ' ' if found.parameter else ''}trace of {points} points, "
        f"{shown(found.frequency[0], 'Hz')}..{shown(found.frequency[-1], 'Hz')}; "
        f"{label} from {min(found.values):.4g} to {found.values[peak]:.4g}, "
        f"peak at {shown(found.frequency[peak], 'Hz')}"
    )


def action_result(done: ActionResult) -> str:
    result = done.result
    told = trace(result) if isinstance(result, Trace) else shown(result)
    return f"{done.ref} {done.action}: {told}"


def raw(reply: RawReply) -> str:
    if reply.answer is not None:
        return f"{reply.instrument} {reply.command}: {reply.answer}"
    return f"{reply.instrument} {reply.command}: sent; read again"


def connections(found: Sequence[ConnectionInfo]) -> str:
    def state(c: ConnectionInfo) -> str:
        return "broken" if c.broken else "open" if c.open else "closed"

    return lines(
        f"{c.label}: {state(c)}, for {', '.join(c.instruments)}" for c in found
    )


def last_line(error: str) -> str:
    """An error with its traceback, in a line: its last."""
    told = error.strip().splitlines()
    return told[-1] if told else error


def procedures(found: Sequence[ProcedureSummary]) -> str:
    return lines(
        f"{p.name}: {p.title}. {p.description}"
        + (f" Not described: {last_line(p.error)}" if p.error else "")
        for p in found
    )


def library(found: CustomLibrary) -> str:
    """The bench's own measurements: run each as its procedure."""
    head = f"library {found.folder}:"
    if not found.measurements:
        return f"{head} no measurement of its own yet; write_custom adds one"
    return "\n".join(
        [head]
        + [
            f"  {m.name}: {m.procedure}, {m.title}"
            + (f"; not described: {last_line(m.error)}" if m.error else "")
            for m in found.measurements
        ]
    )


def custom_text(found: CustomText) -> str:
    return f"{found.info.path} ({found.info.procedure}):\n{found.text}"


def check(found: CustomCheck) -> str:
    """Its problems by line, then the form it describes."""
    parts = [
        f"line {p.line} ({p.kind}): {p.text}" if p.line else f"({p.kind}) {p.text}"
        for p in found.problems
    ] or ["no problems found"]
    info = found.procedure
    if info is not None:
        parts += [f"{info.name}: {info.title}", "parameters:"]
        parts += [f"  {parameter(p)}" for p in info.parameters] or ["  none"]
        slots = ", ".join(f"{s.name} ({s.title})" for s in info.slots)
        parts.append(f"slots: {slots or NOTHING}")
    return "\n".join(parts)


def parameter(p: ParameterInfo) -> str:
    unit = p.display_unit or p.unit
    text = f"{p.name}: {p.label}, {p.kind}{', ' + unit if unit else ''}"
    if p.required:
        text += ", required"
    elif p.default is not None:
        text += f"; default {p.typed(p.default)}"
    if p.minimum is not None or p.maximum is not None:
        text += f"; {p.typed(p.minimum)}..{p.typed(p.maximum)}"
    if p.choices:
        text += f"; one of {', '.join(str(c) for c in p.choices)}"
    if p.max_points:
        text += f"; at most {p.max_points} points"
    if p.help:
        text += f". {p.help}"
    return text


def procedure(info: ProcedureInfo, bench: Sequence[DeviceInfo]) -> str:
    steps = f"{info.steps} steps" if info.steps else "no end of its own: cancel it"
    parts = [
        f"{info.title} ({info.name}): {steps}",
        info.description,
        "parameters (pass them in typed, in the units shown; a sweep "
        "start:stop:points, a list comma separated):",
        *(f"  {parameter(p)}" for p in info.parameters),
        "devices (slot: the devices that suit it):",
        *(
            f"  {s.name}: {', '.join(d.ref for d in s.candidates(bench)) or NOTHING}"
            for s in info.slots
        ),
    ]
    if info.plots:
        parts.append(f"plots: {', '.join(p.title for p in info.plots)}")
    return "\n".join(parts)


def run(found: RunInfo) -> str:
    done = f"{found.done}/{found.total}" if found.total else f"{found.done}"
    used = ", ".join(f"{slot}={ref}" for slot, ref in found.devices.items())
    parts = [
        f"#{found.id} {found.title} ({found.procedure}): {found.status}, "
        f"{done} steps; {used}; by {found.origin}"
    ]
    if found.error:
        parts.append(f"error: {found.error}")
    if found.path:
        parts.append(f"file: {found.path}")
    if found.status == RUNNING and found.id:
        parts.append(f"still running: wait_measurement(id={found.id}) again")
    return "\n".join(parts)


def runs(found: Sequence[RunInfo]) -> str:
    return lines(run(r).splitlines()[0] for r in found)


def column(c: ColumnSummary) -> str:
    told = span(c.minimum, c.maximum, c.unit, c.prefixes)
    return f"{c.key} ({c.label}) {told}".rstrip() if told else f"{c.key} ({c.label})"


def summary(found: MeasurementSummary) -> str:
    parts = [run(found.run)]
    for table in found.tables:
        parts.append(f"table {table.name} ({table.title or table.name}): "
                     f"{table.records} records")  # fmt: skip
        parts += [f"  {column(c)}" for c in table.columns]
    if found.results:
        parts.append(
            "results: "
            + ", ".join(f"{k} = {shown(v)}" for k, v in found.results.items())
        )
    if found.series:
        parts.append(
            "in the file: "
            + ", ".join(f"{k} ({n} values)" for k, n in found.series.items())
        )
    return "\n".join(parts)


def answer(found: UserAnswer) -> str:
    if found.pending or found.answer is None:
        return f"question #{found.id} still waits: wait_answer(id={found.id})"
    given = found.answer
    parts: Tuple[str, ...] = (
        f"answered by {given.by}" if given.allowed else f"declined by {given.by}",
        f"choice: {given.choice}" if given.choice else "",
        f"words: {given.text}" if given.text else "",
    )
    return "; ".join(p for p in parts if p)


def status(found: DaemonStatus) -> str:
    process = found.process
    parts = [
        f"daemon {process.app_version} (pid {process.pid}"
        f"{', simulators' if process.simulate else ''}), profile {found.station}"
        + (f" ({found.path})" if found.path else ""),
        "open: " + (", ".join(found.opened) or NOTHING),
        "clients: " + (", ".join(c.origin for c in found.clients) or NOTHING),
        "running: " + (runs(found.runs) if found.runs else NOTHING),
    ]
    if found.problems:
        parts.append("problems: " + "; ".join(found.problems))
    return "\n".join(parts)
