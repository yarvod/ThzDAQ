"""Graph docks: one per graph of the GraphHub.

A graph made later (New graph…, a new unit of a monitor) opens with the
graphs; the graphs of a starting run all come on screen, as a 2 x 2 grid at
most; custom graphs are kept in the settings.
"""

import json
from typing import List

import PySide6QtAds as QtAds
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.registry import get_procedure

from thzdaq_gui import theme
from thzdaq_gui.dock_names import GRAPH, dock_name
from thzdaq_gui.docking import DockSpace
from thzdaq_gui.graphs import AddCurveDialog, GraphHub, MapGraphWidget

DEFAULT_GRAPHS = ("I-V", "P-V", "Y-V", "P-IF")  # the centre of a default layout
CUSTOM_GRAPHS = "graphs/custom"
# Splits that grow the graph groups of a run to 2 x 2, by groups in use:
# right of the first, below the first, below the second
GRID_SPLITS = {
    1: (QtAds.RightDockWidgetArea, 0),
    2: (QtAds.BottomDockWidgetArea, 0),
    3: (QtAds.BottomDockWidgetArea, 1),
}


def graph_dock(widget) -> str:
    return dock_name(GRAPH, getattr(widget, "key", widget.title))


class GraphDocks:
    def __init__(
        self,
        session,
        hub: GraphHub,
        docks: DockSpace,
        settings: QSettings,
        window: QWidget,
    ):
        self.session = session
        self.hub = hub
        self.docks = docks
        self.settings = settings
        self.window = window  # parent of the dialogs
        hub.add_curve_request = self.add_curve
        hub.graph_created.connect(self.add)
        hub.raise_requested.connect(self.show)
        hub.show_requested.connect(
            lambda widget: docks.open(graph_dock(widget), activate=False)
        )
        hub.run_requested.connect(self.show_run)
        hub.graph_renamed.connect(self.rename)
        hub.graph_removed.connect(self.delete)

    def add_all(self) -> None:
        """Docks of the graphs of the procedures and of the custom ones."""
        for title in self.hub.titles():
            self.hub.graph(title)
        self.load_custom()
        self.hub.custom_changed.connect(self.save_custom)

    def add(self, widget) -> None:
        name = graph_dock(widget)
        if name in self.docks:
            return
        icon = theme.icon(
            "grid" if isinstance(widget, MapGraphWidget) else "chart-line"
        )
        dock = self.docks.add(
            name,
            widget.title,
            widget,
            "Graphs",
            icon,
            QtAds.CenterDockWidgetArea,
            group="Custom" if getattr(widget, "custom", False) else "",
            hint=name,
        )
        if not self.docks.building:
            # Made later (New graph…, a monitor's new unit): opens with the graphs
            dock.toggleView(False)

    def show(self, widget) -> None:
        self.docks.open(graph_dock(widget))

    def show_run(self, widgets) -> None:
        """Graphs of a starting run all on screen, each in front of its tab
        group and no two in one group: a graph that would share one moves to
        a graph group showing nothing of this run, else a group splits
        towards a 2 x 2 grid. Past four groups the rest wait behind tabs."""
        manager = self.docks.manager
        used, placed = [], []
        for widget in widgets:
            name = graph_dock(widget)
            dock = self.docks.get(name)
            if dock is None:
                continue
            if dock.isClosed():
                self.docks.open(name, activate=False)
            area = dock.dockAreaWidget()
            if area is None or dock.isFloating() or dock.isAutoHide():
                dock.setAsCurrentTab()
                continue
            if area in used:
                free = [a for a in self.docks.areas_of(GRAPH) if a not in used]
                if free:
                    manager.addDockWidgetTabToArea(dock, free[0])
                elif len(used) in GRID_SPLITS:
                    side, index = GRID_SPLITS[len(used)]
                    manager.addDockWidget(side, dock, used[index])
                else:
                    continue  # stays behind a tab of a group in use
                area = dock.dockAreaWidget()
            used.append(area)
            placed.append(dock)
        # Last: a graph opened into a group and moved on leaves another in front
        for dock in placed:
            dock.setAsCurrentTab()
        self.docks.sync_bodies()

    def rename(self, widget) -> None:
        name = graph_dock(widget)
        if name in self.docks:
            self.docks.retitle(name, widget.title)

    def delete(self, widget) -> None:
        answer = QMessageBox.question(
            self.window,
            "Delete graph",
            f"Delete the graph {widget.title!r} and its curves?",
        )
        if answer != QMessageBox.Yes:
            return
        self.hub.remove(widget)
        self.docks.remove(graph_dock(widget))

    def new(self) -> None:
        title, ok = QInputDialog.getText(self.window, "New graph", "Title")
        if ok and title.strip():
            try:
                widget = self.hub.new_graph(title.strip())
            except ValueError as e:
                QMessageBox.warning(self.window, "New graph", str(e))
                return
            self.show(widget)

    def add_curve(self, graph) -> None:
        AddCurveDialog(self.session.measurements.items, graph, self.window).exec()

    def plot(self, measurement) -> None:
        """A saved measurement on the graphs of its procedure."""
        try:
            specs = get_procedure(measurement.procedure).plots
        except ProcedureError:
            specs = ()
        for title in self.hub.show_measurement(measurement, specs):
            self.hub.raise_graph(title)

    def default_docks(self) -> List[str]:
        return [dock_name(GRAPH, title) for title in DEFAULT_GRAPHS]

    def load_custom(self) -> None:
        try:
            saved = json.loads(self.settings.value(CUSTOM_GRAPHS) or "[]")
        except (TypeError, ValueError):
            saved = []
        for item in saved:
            try:
                self.hub.new_graph(
                    item["title"], item.get("key"), item.get("x", ""), item.get("y", "")
                )
            except (KeyError, ValueError, TypeError):
                continue

    def save_custom(self) -> None:
        self.settings.setValue(CUSTOM_GRAPHS, json.dumps(self.hub.custom_graphs()))
