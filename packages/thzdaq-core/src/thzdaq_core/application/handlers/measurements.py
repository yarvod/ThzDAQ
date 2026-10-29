"""Operations on procedures and the measurements running in the daemon."""

from typing import Any, Mapping, Tuple

from thzdaq_api import measurements as api
from thzdaq_api.errors import ErrorCode, LabError

from thzdaq_core.application.describe import procedure_info, procedure_summary
from thzdaq_core.application.handlers import Handler
from thzdaq_core.application.runs import Runs
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.catalog import get_procedure, list_procedures
from thzdaq_core.domain.measurements.procedure import Procedure

MAX_WAIT_S = 60.0  # a client waits again rather than holding a request longer


def build(name: str, parameters: Mapping[str, Any]) -> Procedure:
    """A procedure with parameters as JSON gives them (SI, sweeps as dicts)."""
    try:
        cls = get_procedure(name)
    except ProcedureError as e:
        raise LabError(ErrorCode.NOT_FOUND, str(e)) from None
    try:
        return cls.from_json(parameters)
    except ProcedureError as e:
        raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None


class ListProcedures(Handler[api.ListProcedures, Tuple[api.ProcedureSummary, ...]]):
    operation = api.ListProcedures

    def handle(self, args, origin):
        return tuple(procedure_summary(cls) for cls in list_procedures())


class DescribeProcedure(Handler[api.DescribeProcedure, api.ProcedureInfo]):
    operation = api.DescribeProcedure

    def handle(self, args, origin):
        return procedure_info(build(args.procedure, args.parameters))


class StartMeasurement(Handler[api.StartMeasurement, api.RunInfo]):
    operation = api.StartMeasurement

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        procedure = build(args.procedure, args.parameters)
        return self.runs.start(procedure, args.devices, args.comment, origin)


class ListRuns(Handler[api.ListRuns, Tuple[api.RunInfo, ...]]):
    operation = api.ListRuns

    def __init__(self, runs: Runs):
        self.runs = runs

    def handle(self, args, origin):
        return self.runs.all()


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
