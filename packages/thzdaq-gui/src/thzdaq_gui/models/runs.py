"""Route each daemon run to one model, including runs from other clients.

A GUI start may publish before its call returns the id. Unclaimed events wait
while such calls are pending; their answers claim ids before the rest are
adopted. Origin alone cannot identify a run from this window.
"""

from typing import Dict, List

from PySide6.QtCore import QObject, Signal
from thzdaq_api import events
from thzdaq_api.measurement_file import RUNNING
from thzdaq_api.measurements import GetRunSnapshot, ListRuns

from thzdaq_gui import procedure_groups
from thzdaq_gui.dock_names import DATA
from thzdaq_gui.models.run import RunModel


class RunEvents(QObject):
    observed = Signal(object)  # RunModel: a run without a local procedure box
    remembered = Signal(object)  # RunInfo: a run that ended before it was followed

    def __init__(self, session):
        super().__init__(session)
        self.session = session
        self.models: Dict[int, RunModel] = {}
        self.external: List[RunModel] = []
        self._waiting: List[events.Event] = []
        session.bridge.measurement_event.connect(self.hear)

    def hear(self, event: events.Event) -> None:
        number = events.run_id(event.body)
        model = self.models.get(number)
        if model is not None:
            model.hear(event)
        elif isinstance(event.body, events.MeasurementStarted) and (
            event.body.run.origin != self.session.lab.origin or not self._pending()
        ):
            self._observe(number).hear(event)
        elif self._pending():
            self._waiting.append(event)
        else:
            # The start predates the subscription or was lost in a resync.
            model = self._observe(number)
            model.restore(self.session.call(GetRunSnapshot(id=number)))
            model.hear(event)

    def _pending(self) -> bool:
        return any(m.running and m.run is None for m in self.session.runs)

    def claim(self, model: RunModel) -> None:
        for number, previous in list(self.models.items()):
            if previous is model:
                del self.models[number]
        self.models[model.run.id] = model
        self.release()

    def release(self) -> None:
        waiting, self._waiting = self._waiting, []
        for event in waiting:
            self.hear(event)

    def _observe(self, number: int) -> RunModel:
        model = self.session.run_model()
        self.models[number] = model
        self.external.append(model)
        ObservedProcess(self.session.processes, model)
        self.observed.emit(model)
        return model

    def refresh(self) -> None:
        """Catch up after connecting or losing events, including an unseen end;
        runs that ended unseen are told as the daemon remembers them."""
        runs = self.session.call(ListRuns())
        identities = {(run.id, run.started, run.path) for run in runs}
        for number, model in list(self.models.items()):
            run = model.run
            if (run.id, run.started, run.path) not in identities:
                model.lost()
                del self.models[number]
        for run in runs:
            model = self.models.get(run.id)
            if run.status == RUNNING or (model is not None and model.running):
                if model is None:
                    model = self._observe(run.id)
                model.restore(self.session.call(GetRunSnapshot(id=run.id)))
            elif model is None:
                self.remembered.emit(run)

    def detach(self) -> None:
        for model in self.session.runs:
            model.detach()
        self.models.clear()
        self._waiting.clear()
        self.external.clear()


class ObservedProcess(QObject):
    """Processes view of a run that has no procedure box in this window."""

    def __init__(self, processes, model: RunModel):
        super().__init__(model)
        self.processes = processes
        self.model = model
        self.process = None
        model.started.connect(self.start)
        model.progress.connect(self.progress)
        model.running_changed.connect(self.running)

    def start(self, measurement) -> None:
        run = self.model.run
        self.process = self.processes.start(
            f"#{run.id} {run.title} · {run.origin}",
            procedure_groups.group(run.procedure).icon,
            DATA,
            stop=self.model.cancel,
        )
        self.process.update(status=run.status)

    def progress(self, done: int, total) -> None:
        if self.process is not None:
            self.process.update(progress=(done, total) if total else None)

    def running(self, running: bool) -> None:
        if not running:
            self.processes.finish(self.process)
            self.process = None
