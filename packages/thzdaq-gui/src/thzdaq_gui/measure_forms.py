"""The forms of the measurements the bench runs, the built-in ones and its
own (custom.<name>): one per procedure, built when first asked for (the bar
on top shows it in the popup under its settings button, or starts its run).

They follow the catalog (the window syncs them when it changes): a
measurement of the bench's own comes and goes with its script, and its form
reloads itself when its script is described anew. The monitor and the
bench's own measurements have forms of their own. Which of them run is told
as their runs tell it (RunStatus).
"""

from typing import Dict, Optional, Set

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget
from thzdaq_api.custom import file_name
from thzdaq_api.procedures import MONITOR_VALUES_VS_TIME

from thzdaq_gui.docks.custom import CustomMeasureForm, OpenCode
from thzdaq_gui.docks.measure import MeasureForm, MonitorForm
from thzdaq_gui.graphs import GraphHub
from thzdaq_gui.run_controls import Run

# Forms of their own class by procedure name
SPECIAL = {MONITOR_VALUES_VS_TIME: MonitorForm}


class MeasureForms(QObject):
    running_changed = Signal(str, bool)  # a procedure whose run started or ended

    def __init__(self, session, hub: GraphHub, open_code: OpenCode, host: QWidget):
        """open_code(procedure, line): the script of one of the bench's own;
        host: the widget the forms belong to until they are shown."""
        super().__init__(host)
        self.session = session
        self.hub = hub
        self.open_code = open_code
        self.host = host
        self.forms: Dict[str, MeasureForm] = {}
        self._running: Set[str] = set()

    def __contains__(self, procedure: str) -> bool:
        return self.session.procedure(procedure) is not None

    def make(self, procedure: str) -> MeasureForm:
        if file_name(procedure) is not None:
            return CustomMeasureForm(
                self.session, self.hub, procedure, self.open_code, self.host
            )
        return SPECIAL.get(procedure, MeasureForm)(
            self.session, self.hub, procedure, self.host
        )

    def form(self, procedure: str) -> Optional[MeasureForm]:
        """Built the first time; None for a procedure the bench does not run."""
        if procedure not in self:
            return None
        form = self.forms.get(procedure)
        if form is None:
            form = self.forms[procedure] = self.make(procedure)
            form.hide()
            box = form.box
            box.status_changed.connect(lambda _: self.tell(procedure, box))
        return form

    def run(self, procedure: str) -> Optional[Run]:
        """What the form of a procedure runs (its box); None: no such form."""
        form = self.form(procedure)
        return form.box if form is not None else None

    def running(self) -> Set[str]:
        """The procedures whose runs go on now."""
        return set(self._running)

    def tell(self, procedure: str, run: Run) -> None:
        running = run.status().running
        if running == (procedure in self._running):
            return
        (self._running.add if running else self._running.discard)(procedure)
        self.running_changed.emit(procedure, running)

    def sync(self, *_) -> None:
        """No form for a procedure the catalog has no more."""
        for procedure in [p for p in self.forms if p not in self]:
            self.forms.pop(procedure).deleteLater()
            if procedure in self._running:
                self._running.discard(procedure)
                self.running_changed.emit(procedure, False)
        self.hub.set_procedures(self.session.procedures())
