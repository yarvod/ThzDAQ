"""The procedures the bench runs, as one catalog: the built-in ones and the
bench's own measurements (custom.<name>, application.custom)."""

from typing import Tuple, Type

from thzdaq_api.custom import file_name
from thzdaq_api.events import ProceduresChanged
from thzdaq_api.measurements import ProcedureSummary

from thzdaq_core.application.custom import CustomMeasurements
from thzdaq_core.application.describe import procedure_summary
from thzdaq_core.application.events import EventBus
from thzdaq_core.domain.measurements.catalog import get_procedure, list_procedures
from thzdaq_core.domain.measurements.procedure import Procedure


class Procedures:
    """A change of the library is told to clients with the whole catalog
    (procedures_changed): they replace their list with it."""

    def __init__(self, customs: CustomMeasurements, events: EventBus):
        self.customs = customs
        self.events = events
        customs.changed.append(self.tell)

    def summaries(self) -> Tuple[ProcedureSummary, ...]:
        """The built-in ones, then the bench's own (those that cannot run
        with why)."""
        return self.built_in() + self.customs.summaries()

    def built_in(self) -> Tuple[ProcedureSummary, ...]:
        return tuple(procedure_summary(cls) for cls in list_procedures())

    def tell(self, customs: Tuple[ProcedureSummary, ...]) -> None:
        self.events.publish(ProceduresChanged(self.built_in() + customs))

    def get(self, name: str) -> Type[Procedure]:
        """ProcedureError for an unknown one, or a custom one whose script is
        not described."""
        if file_name(name) is not None:
            return self.customs.get(name)
        return get_procedure(name)
