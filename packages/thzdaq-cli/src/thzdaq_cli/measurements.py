"""thzdaq procedures, describe, run, status, measurements, cancel, watch, plot:
the procedures of the bench and the measurements in its daemon. Parameters
are typed as describe shows them, in their display units: --set
voltage=0:7:351 is a sweep from 0 to 7 mV in 351 points. A run is followed
until it ends; Ctrl+C asks whether to cancel it, and without a terminal
leaves it running. plot opens the plots of a measurement in a window of
their own, apart from this terminal."""

import queue
import sys
from typing import Any, Callable, Dict, Iterator

from thzdaq_api import events, windows
from thzdaq_api.devices import ListDevices
from thzdaq_api.lab import Lab
from thzdaq_api.measurement_file import (
    COMPLETED,
    RUNNING,
    Measurement,
    read_measurement,
)
from thzdaq_api.measurements import (
    AbortMeasurement,
    CancelMeasurement,
    DescribeProcedure,
    ListProcedures,
    ListRuns,
    ProcedureInfo,
    RunInfo,
    StartMeasurement,
    fill_slots,
)

from thzdaq_cli import show
from thzdaq_cli.client import FAILED, HERE, OK, Client, Mistyped
from thzdaq_cli.devices import assignments


def add(commands) -> None:
    commands.add_parser("procedures", help="what the bench measures").set_defaults(
        run=list_procedures
    )
    describe = commands.add_parser(
        "describe", help="a procedure: parameters, devices, plots"
    )
    describe.add_argument("procedure")
    given(describe)
    describe.set_defaults(run=describe_procedure)
    run = commands.add_parser("run", help="run a procedure and follow it")
    run.add_argument("procedure")
    given(run)
    run.add_argument("--comment", default="")
    run.add_argument(
        "--share", action="store_true", help="also on devices others sweep"
    )
    run.add_argument("--workspace", help=f"its file goes to data/ there ({HERE})")
    run.add_argument("--dry-run", action="store_true", help="check, start nothing")
    run.add_argument("--detach", action="store_true", help="start it, do not follow")
    run.set_defaults(run=run_procedure)
    commands.add_parser("status", help="measurements running now").set_defaults(
        run=running
    )
    commands.add_parser(
        "measurements", help="measurements of the daemon, running and lately ended"
    ).set_defaults(run=list_runs)
    cancel = commands.add_parser("cancel", help="stop a measurement (it restores)")
    cancel.add_argument("id", type=int)
    cancel.add_argument("--abort", action="store_true", help="break reads that hang")
    cancel.set_defaults(run=cancel_run)
    watch = commands.add_parser("watch", help="follow a measurement, or every event")
    watch.add_argument("id", type=int, nargs="?")
    watch.set_defaults(run=watch_events)
    plot = commands.add_parser(
        "plot", help="the plots of a measurement in a window of their own"
    )
    plot.add_argument(
        "measurement", type=windows.which, metavar=windows.WHICH,
        help=windows.WHICH_HELP,
    )  # fmt: skip
    windows.add_options(plot)
    plot.set_defaults(run=plot_measurement)
    file = commands.add_parser("show", help="what a measurement file holds")
    file.add_argument("path")
    file.set_defaults(run=show_file)


def given(command) -> None:
    command.add_argument(
        "--set", action="append", default=[], metavar="NAME=VALUE",
        help="a parameter as describe shows it (display units; a sweep start:stop:points)",
    )  # fmt: skip
    command.add_argument(
        "--device", action="append", default=[], metavar="SLOT=DEVICE",
        help="the device of a slot (default: the device named as the slot)",
    )  # fmt: skip


def broken(error: str) -> str:
    """Why a procedure cannot run, in a line: the last of its error."""
    lines = error.strip().splitlines()
    return f"not described: {lines[-1]}" if lines else ""


def list_procedures(args, client: Client) -> int:
    found = client.call(ListProcedures())
    client.out(
        found,
        lambda p: show.table(
            ("procedure", "title", ""), [(i.name, i.title, broken(i.error)) for i in p]
        ),
    )
    return OK


def procedure_text(info: ProcedureInfo) -> str:
    steps = f"{info.steps} steps" if info.steps else "no step count"
    lines = [f"{info.title} ({info.name}): {steps}", info.description, ""]
    lines.append(
        show.table(
            ("parameter", "label", "default", "unit", "used when"),
            [(p.name, p.label, p.typed(p.default), p.display_unit, p.used_when())
             for p in info.parameters],
        )
    )  # fmt: skip
    slots = show.table(
        ("slot", "device of", "kind"),
        [(s.name, " + ".join(s.capabilities) or "any", s.kind or "")
         for s in info.slots],
    )  # fmt: skip
    if slots:
        lines += ["", slots]
    if info.plots:
        lines += ["", "plots: " + ", ".join(p.title for p in info.plots)]
    return "\n".join(lines)


def describe_procedure(args, client: Client) -> int:
    info = client.call(
        DescribeProcedure(
            procedure=args.procedure,
            typed=assignments(args.set),
            devices=assignments(args.device),
        )
    )
    client.out(info, procedure_text)
    return OK


def run_text(run: RunInfo) -> str:
    """How a run stands, or how it ended."""
    done = f"{run.done}/{run.total}" if run.total else f"{run.done}"
    text = f"#{run.id} {run.title}: {run.status} ({done} steps)"
    if run.error:
        text += f"\n{run.error}"
    if run.path:
        text += f"\nfile {run.path}"
    return text


def chosen_devices(args, client: Client) -> Dict[str, str]:
    """The devices given, and for a slot without one the device that alone
    suits it (said on stderr); several that suit are named for --device."""
    typed, given = assignments(args.set), assignments(args.device)
    info = client.call(DescribeProcedure(procedure=args.procedure, typed=typed))
    devices, choices = fill_slots(info.slots, client.call(ListDevices()), given)
    if choices:
        slot, refs = next(iter(choices.items()))
        raise Mistyped(f"--device {slot}=… one of {', '.join(refs)}")
    for slot in devices.keys() - given.keys():
        print(f"{slot}: {devices[slot]}", file=sys.stderr)
    return devices


def run_procedure(args, client: Client) -> int:
    workspace = client.folder()
    devices = chosen_devices(args, client)

    def start(share: bool) -> RunInfo:
        return client.call(
            StartMeasurement(
                procedure=args.procedure,
                typed=assignments(args.set),
                devices=devices,
                comment=args.comment,
                share=share or args.share,
                workspace=workspace,
                dry_run=args.dry_run,
            )
        )

    if args.dry_run or args.detach:
        planned = client.shared(start)
        if planned is None:
            return FAILED
        client.out(planned, run_text)
        return OK
    heard = Heard(client.lab)  # before the start: none of its events is missed
    try:
        started = client.shared(start)
        if started is None:
            return FAILED
        if not client.json:
            print(f"#{started.id} {started.title} started", file=sys.stderr)
        return follow(client, heard, started.id)
    finally:
        heard.stop()


class Heard:
    """Events of the lab: the stream's thread hands them over, a command takes
    them in its own."""

    def __init__(self, lab: Lab):
        self.queue: "queue.Queue[events.Event]" = queue.Queue()
        self.stop = lab.subscribe(self.queue.put)

    def bodies(self) -> Iterator[Any]:
        while True:
            try:
                yield self.queue.get(timeout=0.2).body
            except queue.Empty:
                continue  # a moment to hear Ctrl+C


def follow(client: Client, heard: Heard, run_id: int) -> int:
    """Until the measurement ends: its progress, its log, how it ended."""
    while True:
        try:
            for body in heard.bodies():
                if events.run_id(body) != run_id or isinstance(
                    body, events.MeasurementRecords
                ):
                    continue
                if client.json:
                    print(show.as_json(body), flush=True)
                elif isinstance(body, events.MeasurementProgress):
                    progress(body)
                elif isinstance(body, events.MeasurementLog):
                    print(body.message)
                if isinstance(body, events.MeasurementFinished):
                    if not client.json:
                        print(run_text(body.run))
                    return OK if body.run.status == COMPLETED else FAILED
        except KeyboardInterrupt:
            print(file=sys.stderr)
            if not client.ask(f"Cancel #{run_id}?"):
                print(f"#{run_id} goes on: thzdaq watch {run_id}", file=sys.stderr)
                return OK
            client.call(CancelMeasurement(id=run_id))


def progress(body: events.MeasurementProgress) -> None:
    """On one line of a terminal; a log file gets no progress lines."""
    if not sys.stderr.isatty():
        return
    total = (
        f"/{body.total} ({round(100 * body.done / body.total)} %)" if body.total else ""
    )
    sys.stderr.write(f"\r#{body.id} {body.done}{total}  ")
    sys.stderr.flush()


def running(args, client: Client) -> int:
    found = [run for run in client.call(ListRuns()) if run.status == RUNNING]
    client.out(found, lambda r: runs_table(r) or "no measurement runs")
    return OK


def runs_table(runs) -> str:
    return show.table(
        ("id", "title", "status", "done", "origin", "file"),
        [(r.id, r.title, r.status, f"{r.done}/{r.total or '?'}", r.origin, r.path or "")
         for r in runs],
    )  # fmt: skip


def list_runs(args, client: Client) -> int:
    found = client.call(ListRuns())
    client.out(found, lambda r: runs_table(r) or "no measurement")
    return OK


def cancel_run(args, client: Client) -> int:
    operation = AbortMeasurement if args.abort else CancelMeasurement
    client.out(client.call(operation(id=args.id)), run_text)
    return OK


# One line for each kind of event when every event is watched
LINES: Dict[type, Callable[[Any], str]] = {
    events.QuantitySet: lambda b: f"{b.ref} {b.key} = {show.value(b.value)} ({b.origin})",
    events.ActionDone: lambda b: f"{b.ref} {b.action} {b.arguments or ''} ({b.origin})",
    events.Values: lambda b: f"{b.ref} "
    + " ".join(f"{k}={show.value(v)}" for k, v in b.values.items()),
    events.ReadFailed: lambda b: f"{b.ref} failed: {b.message}",
    events.MeasurementStarted: lambda b: f"#{b.run.id} {b.run.title} started ({b.run.origin})",
    events.MeasurementProgress: lambda b: f"#{b.id} {b.done}/{b.total or '?'}",
    events.MeasurementLog: lambda b: f"#{b.id} {b.message}",
    events.MeasurementPlotted: lambda b: f"#{b.id} plots {b.plot.title}",
    events.MeasurementFinished: lambda b: run_text(b.run),
    events.RawSent: lambda b: f"{b.instrument} {b.command!r}"
    + ("" if b.answer is None else f" -> {b.answer!r}")
    + f" ({b.origin})",
    events.ScriptStarted: lambda b: f"{show.script(b.script)} ({b.script.by})",
    events.ScriptOutput: lambda b: show.output(b.id, b.text),
    events.ScriptEnded: lambda b: show.script(b.script),
    events.ProceduresChanged: lambda b: f"procedures: {len(b.procedures)}",
    events.StationChanged: lambda b: f"profile {show.profile(b.name, b.path)}",
    events.LeasesChanged: lambda b: "in use: "
    + (", ".join(f"{l.device} {l.mode} by #{l.run}" for l in b.leases) or "nothing"),
    events.ApprovalRequested: lambda b: show.approval(b.approval),
    events.ApprovalAnswered: lambda b: show.answer(b.id, b.answer),
    events.UiRequested: lambda b: f"window {b.window}: {b.operation} "
    + " ".join(f"{k}={v}" for k, v in b.arguments.items() if v not in (None, {}, ""))
    + f" ({b.origin})",
    events.Resync: lambda b: "events were lost (the daemon restarted)",
}


def watch_events(args, client: Client) -> int:
    heard = Heard(client.lab)
    try:
        if args.id is not None:
            found = next((r for r in client.call(ListRuns()) if r.id == args.id), None)
            if found is None or found.status != RUNNING:
                client.out(
                    found, lambda r: run_text(r) if r else f"no measurement #{args.id}"
                )
                return OK if found is not None else FAILED
            return follow(client, heard, args.id)
        try:
            for body in heard.bodies():
                if isinstance(body, events.MeasurementRecords):
                    continue
                print(
                    show.as_json(body) if client.json else LINES[type(body)](body),
                    flush=True,
                )
        except KeyboardInterrupt:
            return OK
    finally:
        heard.stop()


def plot_measurement(args, client: Client) -> int:
    which = args.measurement
    command = windows.open_plots(
        client.call, which, client.simulate, windows.OwnPlot.of(args)
    )
    shown = f"#{which}" if isinstance(which, int) else which
    client.out(
        {"measurement": which, "command": command},
        lambda told: f"the plots of {shown} open in a window",
    )
    return OK


def file_text(measurement: Measurement) -> str:
    lines = [
        f"#{measurement.id} {measurement.title or measurement.procedure}: "
        f"{measurement.status}",
        f"{measurement.started} .. {measurement.finished or ''}".rstrip(" ."),
    ]
    if measurement.comment:
        lines.append(measurement.comment)
    if measurement.error:
        lines.append(measurement.error)
    lines.append(
        show.table(
            ("table", "records", "columns"),
            [(name, len(measurement.records(name)), ", ".join(table.data))
             for name, table in measurement.tables.items()],
        )
        or "no records"
    )  # fmt: skip
    return "\n".join(lines)


def show_file(args, client: Client) -> int:
    """No daemon needed: the file is read here."""
    found = read_measurement(args.path)
    client.out(found.to_dict() if client.json else found, file_text)
    return OK
