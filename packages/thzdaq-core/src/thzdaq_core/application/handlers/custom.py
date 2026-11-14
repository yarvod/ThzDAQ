"""Operations on the bench's own measurements (Custom): the scripts of the
library listed, read, checked and written; a declared value parsed as a run
takes it."""

import difflib

from thzdaq_api import custom as api
from thzdaq_api.errors import ErrorCode, LabError

from thzdaq_core.application.approvals import Ask
from thzdaq_core.application.check import Checks
from thzdaq_core.application.custom import CustomMeasurements
from thzdaq_core.application.handlers import Handler
from thzdaq_core.domain.errors import ProcedureError
from thzdaq_core.domain.measurements.custom import given, parameter


class ParseValue(Handler[api.ParseValue, api.Given]):
    operation = api.ParseValue

    def handle(self, args, origin):
        try:
            found = parameter(args.value)
        except ProcedureError as e:
            raise LabError(ErrorCode.INVALID_ARGUMENTS, str(e)) from None
        return given(found, found.default)


SHOWN = 80  # lines of a change a person reads before allowing it


class ListCustom(Handler[api.ListCustom, api.CustomLibrary]):
    operation = api.ListCustom

    def __init__(self, customs: CustomMeasurements):
        self.customs = customs

    def handle(self, args, origin):
        return self.customs.listed()


class ReadCustom(Handler[api.ReadCustom, api.CustomText]):
    operation = api.ReadCustom

    def __init__(self, customs: CustomMeasurements):
        self.customs = customs

    def handle(self, args, origin):
        return self.customs.text(args.script)


class CheckCustom(Handler[api.CheckCustom, api.CustomCheck]):
    operation = api.CheckCustom

    def __init__(self, checks: Checks):
        self.checks = checks

    def handle(self, args, origin):
        return self.checks.check(args.script, args.text)


def change(before: str, after: str, name: str) -> str:
    """What a write changes, as a person reads it: the lines that differ."""
    lines = list(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(), f"{name}.py", f"{name}.py",
            lineterm="", n=1,
        )
    )[2:]  # fmt: skip
    told = lines[:SHOWN]
    if len(lines) > SHOWN:
        told.append(f"… and {len(lines) - SHOWN} lines more")
    return "\n".join(told)


class WriteCustom(Handler[api.WriteCustom, api.CustomCheck]):
    operation = api.WriteCustom

    def __init__(self, customs: CustomMeasurements, checks: Checks):
        self.customs = customs
        self.checks = checks

    def handle(self, args, origin):
        self.customs.write(args.script, args.text)
        return self.checks.check(args.script)

    def approval(self, args, origin):
        """The change as the person reads it before it is written."""
        try:
            before = self.customs.text(args.script).text
        except LabError:
            before = ""
        title = f"{'Change' if before else 'New'} measurement {args.script}"
        return Ask(title, change(before, args.text, args.script) or "no change")
