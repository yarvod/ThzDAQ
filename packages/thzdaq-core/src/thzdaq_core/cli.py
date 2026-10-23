"""thzdaq: run measurements without the GUI."""

import argparse
import signal
import sys
from typing import List, Optional

from thzdaq_instruments import InstrumentError

from thzdaq_core.data.measurement import COMPLETED, Measurement
from thzdaq_core.data.store import MeasurementStore, read_json
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.registry import get_procedure, list_procedures
from thzdaq_core.measurements.runner import MeasurementRunner, RunObserver
from thzdaq_core.station.station import Station


def _requirements(cls) -> str:
    try:
        required = cls().slots()  # with default parameters
    except Exception:
        required = cls.requires
    parts = []
    for slot, capabilities in required.items():
        caps = capabilities if isinstance(capabilities, tuple) else (capabilities,)
        parts.append(f"{slot}({'+'.join(c.__name__ for c in caps)})")
    return ", ".join(parts)


def cmd_list(args) -> int:
    for cls in list_procedures():
        print(f"{cls.name:24} {cls.title}")
        print(f"{'':24} devices: {_requirements(cls)}")
    return 0


def cmd_describe(args) -> int:
    cls = get_procedure(args.procedure)
    print(f"{cls.name}: {cls.title}")
    if cls.description:
        print(cls.description)
    print(f"devices: {_requirements(cls)}")
    print("parameters (values in display units, --set name=value):")
    for name, parameter in cls.parameters().items():
        default = (
            "required"
            if parameter.describe()["required"]
            else parameter.format(parameter.default)
        )
        extra = (
            f" [{', '.join(map(str, parameter.choices))}]"
            if hasattr(parameter, "choices")
            else ""
        )
        print(f"  {name:20} {parameter.label}: {default}{extra}")
        if parameter.kind == "sweep":
            print(f"  {'':20} format start:stop:points in {parameter.display_unit}")
    return 0


class ConsoleObserver(RunObserver):
    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def on_progress(self, done, total):
        if self.quiet:
            return
        shown = f"{done}/{total}" if total else f"{done}"
        print(f"\r  {shown}", end="", file=sys.stderr, flush=True)

    def on_log(self, message):
        if not self.quiet:
            print(f"\n  {message}", file=sys.stderr)


def build_procedure(name: str, assignments: List[str]):
    cls = get_procedure(name)
    parameters = cls.parameters()
    values = {}
    for assignment in assignments:
        key, sep, text = assignment.partition("=")
        if not sep or key not in parameters:
            raise ProcedureError(
                f"--set {assignment!r}: expected name=value with one of {sorted(parameters)}"
            )
        values[key] = parameters[key].parse(text)
    return cls(**values)


def parse_devices(assignments: List[str]):
    devices = {}
    for assignment in assignments:
        slot, sep, ref = assignment.partition("=")
        if not sep or not slot or not ref:
            raise ProcedureError(f"--device {assignment!r}: expected slot=device")
        devices[slot] = ref
    return devices


def summarize(measurement: Measurement) -> str:
    counts = (
        ", ".join(f"{k}: {len(v)}" for k, v in measurement.tables.items())
        or "no records"
    )
    line = f"{measurement.status} {measurement.procedure} [{counts}]"
    if measurement.error:
        line += f"\n  error: {measurement.error}"
    if measurement.metadata.get("path"):
        line += f"\n  saved {measurement.metadata['path']}"
    return line


def cmd_run(args) -> int:
    procedure = build_procedure(args.procedure, args.set or [])
    store = None if args.no_save else MeasurementStore(args.data)
    with Station.load(args.station, simulate=args.simulate, lively=True) as station:
        runner = MeasurementRunner(station, store, [ConsoleObserver(args.quiet)])
        previous = signal.signal(signal.SIGINT, lambda *_: runner.cancel())
        try:
            measurement = runner.run(
                procedure,
                comment=args.comment,
                devices=parse_devices(args.device or []),
            )
        finally:
            signal.signal(signal.SIGINT, previous)
    print(file=sys.stderr)
    print(summarize(measurement))
    return 0 if measurement.status == COMPLETED else 1


def cmd_show(args) -> int:
    measurement = read_json(args.path)
    print(
        f"{measurement.id} {measurement.title or measurement.procedure} "
        f"{measurement.started}"
    )
    print(summarize(measurement))
    for key, value in measurement.parameters.items():
        print(f"  {key} = {value}")
    for slot, use in measurement.devices.items():
        print(f"  {slot}: {use.title} ({use.ref})")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="thzdaq", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="available procedures").set_defaults(func=cmd_list)

    describe = commands.add_parser("describe", help="procedure parameters and devices")
    describe.add_argument("procedure")
    describe.set_defaults(func=cmd_describe)

    run = commands.add_parser("run", help="run a procedure on a station")
    run.add_argument("procedure")
    run.add_argument("--station", required=True, help="station profile (YAML)")
    run.add_argument("--simulate", action="store_true")
    run.add_argument("--set", action="append", metavar="NAME=VALUE")
    run.add_argument(
        "--device", action="append", metavar="SLOT=DEVICE", help="e.g. bias=sis_bias_1"
    )
    run.add_argument("--data", default="data", help="measurements folder")
    run.add_argument("--no-save", action="store_true")
    run.add_argument("--comment", default="")
    run.add_argument("--quiet", action="store_true")
    run.set_defaults(func=cmd_run)

    show = commands.add_parser("show", help="summary of a saved measurement")
    show.add_argument("path")
    show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (InstrumentError, ProcedureError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
