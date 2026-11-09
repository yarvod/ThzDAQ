"""Operations on the bench's own measurements (Custom): a declared value
parsed as a run takes it."""

from thzdaq_api import custom as api
from thzdaq_api.errors import ErrorCode, LabError

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
