"""Operations on procedures and the measurements running in the daemon."""

from typing import Any, Mapping, Tuple

from thzdaq_api import measurements as api
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.operation import Rights

from thzdaq_core.application.approvals import Ask
from thzdaq_core.application.describe import procedure_info, procedure_summary
from thzdaq_core.application.devices import DeviceAccess
from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.runs import Runs
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.catalog import get_procedure, list_procedures
from thzdaq_core.domain.measurements.procedure import Procedure

MAX_WAIT_S = 60.0  # a client waits again rather than holding a request longer


def build(
    name: str, parameters: Mapping[str, Any], typed: Mapping[str, str]
) -> Procedure:
    """A procedure with parameters as JSON gives them (SI, sweeps as dicts) and
    as people type them (display units, sweeps as start:stop:points)."""
    try:
        cls = get_procedure(name)
    except ProcedureError as e:
        raise LabError(ErrorCode.NOT_FOUND, str(e)) from None
    try:
        return cls.from_json(parameters, typed)
    except ProcedureError as e:
        raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None


class ListProcedures(Handler[api.ListProcedures, Tuple[api.ProcedureSummary, ...]]):
    operation = api.ListProcedures

    def handle(self, args, origin):
        return tuple(procedure_summary(cls) for cls in list_procedures())


class DescribeProcedure(Handler[api.DescribeProcedure, api.ProcedureInfo]):
    operation = api.DescribeProcedure

    def __init__(self, devices: DeviceAccess):
        self.devices = devices

    def handle(self, args, origin):
        procedure = build(args.procedure, args.parameters, args.typed)

        def quantities(slot: str):
            ref = args.devices.get(slot)
            return self.devices.quantities(ref) if ref else []

        return procedure_info(procedure, quantities if args.devices else None)


class StartMeasurement(Handler[api.StartMeasurement, api.RunInfo]):
    operation = api.StartMeasurement

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        procedure = build(args.procedure, args.parameters, args.typed)
        return self.runs.start(
            procedure,
            args.devices,
            args.comment,
            origin,
            args.share,
            args.workspace,
            args.dry_run,
        )

    def needs(self, args):
        """A dry run changes nothing."""
        return Rights.READ if args.dry_run else self.operation.rights

    def approval(self, args):
        """The run it would be, checked as a dry run: one that could not start
        is refused before anybody is asked."""
        procedure = build(args.procedure, args.parameters, args.typed)
        planned = self.runs.start(
            procedure, args.devices, args.comment, "", args.share, args.workspace,
            dry_run=True,
        )  # fmt: skip
        devices = ", ".join(f"{slot} {ref}" for slot, ref in planned.devices.items())
        given = args.typed or args.parameters
        parameters = ", ".join(f"{key} {value}" for key, value in given.items())
        steps = f"{planned.total} points" if planned.total else "runs until cancelled"
        text = "; ".join(filter(None, (devices, parameters, steps, args.comment)))
        return Ask(f"Start {planned.title}", text)


class SetComment(Handler[api.SetComment, None]):
    operation = api.SetComment

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        self.runs.set_comment(args.path, args.comment)


class ListRuns(Handler[api.ListRuns, Tuple[api.RunInfo, ...]]):
    operation = api.ListRuns

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        return self.runs.all()


class GetRunSnapshot(Handler[api.GetRunSnapshot, api.RunSnapshot]):
    operation = api.GetRunSnapshot

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        return self.runs.snapshot(args.id)


class WaitMeasurement(Handler[api.WaitMeasurement, api.RunInfo]):
    operation = api.WaitMeasurement

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        if not 0 <= args.timeout <= MAX_WAIT_S:
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"timeout must be 0..{MAX_WAIT_S:g} s",
                "wait again while the measurement runs",
            )
        return self.runs.wait(args.id, args.timeout)


class SummarizeMeasurement(Handler[api.SummarizeMeasurement, api.MeasurementSummary]):
    operation = api.SummarizeMeasurement

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        return self.runs.summary(args.id)


class CancelMeasurement(Handler[api.CancelMeasurement, api.RunInfo]):
    operation = api.CancelMeasurement

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        return self.runs.cancel(args.id)


class AbortMeasurement(Handler[api.AbortMeasurement, api.RunInfo]):
    operation = api.AbortMeasurement

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        return self.runs.abort(args.id)
