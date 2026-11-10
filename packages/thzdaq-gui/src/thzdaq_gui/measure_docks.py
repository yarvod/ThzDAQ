"""Measurement docks: one per procedure the bench runs, the built-in ones and
its own (custom.<name>).

They follow the catalog (the window syncs them when it changes): a
measurement of the bench's own comes and goes with its script, and a dock is
retitled when its script is described anew (its content reloads its form
itself). The content of a dock is built when it
first opens (DockBody): the monitor and the bench's own measurements have
widgets of their own.
"""

from typing import Callable, Dict

import PySide6QtAds as QtAds
from thzdaq_api.custom import file_name
from thzdaq_api.measurements import ProcedureSummary
from thzdaq_api.procedures import MONITOR_TIME

from thzdaq_gui import procedure_groups, theme
from thzdaq_gui.dock_names import MEASURE, dock_name, key_of
from thzdaq_gui.docking import DockSpace
from thzdaq_gui.docks.body import DockBody
from thzdaq_gui.docks.custom import CustomMeasureWidget, OpenCode
from thzdaq_gui.docks.measure import MeasureWidget, MonitorWidget
from thzdaq_gui.graphs import GraphHub

# Docks with their own widget class by procedure name
SPECIAL = {MONITOR_TIME: MonitorWidget}
SECTION = "Measures"


class MeasureDocks:
    def __init__(
        self,
        session,
        hub: GraphHub,
        docks: DockSpace,
        open_code: OpenCode,
    ):
        """open_code(procedure, line): the script of one of the bench's own."""
        self.session = session
        self.hub = hub
        self.docks = docks
        self.open_code = open_code
        self.titles: Dict[str, str] = {}  # dock name -> its title now

    def widget(self, procedure: str) -> MeasureWidget:
        if file_name(procedure) is not None:
            return CustomMeasureWidget(
                self.session, self.hub, procedure, self.open_code
            )
        return SPECIAL.get(procedure, MeasureWidget)(self.session, self.hub, procedure)

    def factory(self, procedure: str) -> Callable[[], MeasureWidget]:
        return lambda: self.widget(procedure)

    def sync(self, *_) -> None:
        """A dock for every procedure of the catalog, none for others."""
        wanted = {
            dock_name(MEASURE, procedure.name): procedure
            for procedure in self.session.procedures()
        }
        for name in [n for n in self.docks if key_of(n, MEASURE) and n not in wanted]:
            self.docks.remove(name)
            self.titles.pop(name, None)
        for name, procedure in wanted.items():
            title = procedure.title or procedure.name
            if name not in self.docks:
                self.add(name, procedure, title)
            elif self.titles.get(name) != title:
                self.docks.retitle(name, title)
                self.titles[name] = title
        self.hub.set_procedures(self.session.procedures())

    def add(self, name: str, procedure: ProcedureSummary, title: str) -> None:
        group = procedure_groups.group(procedure.name)
        dock = self.docks.add(
            name, title, DockBody(self.factory(procedure.name)), SECTION,
            theme.icon(group.icon), QtAds.RightDockWidgetArea,
            group=group.title, hint=procedure.name,
        )  # fmt: skip
        self.titles[name] = title
        if not self.docks.building:
            dock.toggleView(False)  # added later: opens when asked for
