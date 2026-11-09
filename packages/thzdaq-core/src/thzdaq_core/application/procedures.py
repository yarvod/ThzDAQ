"""The procedures the bench runs, as one catalog: the built-in ones and the
bench's own measurements (custom.<name>, application.custom)."""

from typing import Tuple, Type

from thzdaq_api.custom import file_name
from thzdaq_api.measurements import ProcedureSummary

from thzdaq_core.application.custom import CustomMeasurements
from thzdaq_core.application.describe import procedure_summary
from thzdaq_core.domain.measurements.catalog import get_procedure, list_procedures
from thzdaq_core.domain.measurements.procedure import Procedure


class Procedures:
    def __init__(self, customs: CustomMeasurements):
        self.customs = customs

    def summaries(self) -> Tuple[ProcedureSummary, ...]:
        """The built-in ones, then the bench's own (those that cannot run
        with why)."""
        built_in = tuple(procedure_summary(cls) for cls in list_procedures())
        return built_in + self.customs.summaries()

    def get(self, name: str) -> Type[Procedure]:
        """ProcedureError for an unknown one, or a custom one whose script is
        not described."""
        if file_name(name) is not None:
            return self.customs.get(name)
        return get_procedure(name)
