"""Graph docks: one per graph of the GraphHub.

A graph of the procedures is built when its dock first opens or it gets
data: most never do in a session. A graph made later (New graph…, a new
unit of a monitor) opens with the graphs; the graphs of a starting run all
come on screen, as a 2 x 2 grid at most; custom graphs are kept in the
settings.
"""

import json
import logging
from typing import List

import PySide6QtAds as QtAds
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget
from thzdaq_api.measurements import saved_plots

from thzdaq_gui import theme
from thzdaq_gui.dock_names import GRAPH, dock_name
from thzdaq_gui.docking import DockSpace, even_out
from thzdaq_gui.docks.body import DockBody
from thzdaq_gui.graphs import AddCurveDialog, GraphHub
from thzdaq_gui.settings import CUSTOM_GRAPHS

logger = logging.getLogger(__name__)

DEFAULT_GRAPHS = ("I-V", "P-V", "Y-V", "P-IF")  # the centre of a default layout
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
        hub.titles_added.connect(self.add_titles)

    def add_all(self) -> None:
        """Docks of the graphs of the procedures, not built yet, and of the
        custom ones."""
        self.add_titles(self.hub.titles())
        self.load_custom()
        self.hub.custom_changed.connect(self.save_custom)

    def add_titles(self, titles) -> None:
        """Docks of graphs of the procedures (the bench's own measurements
        add some), not built yet."""
        for title in titles:
            if dock_name(GRAPH, title) in self.docks:
                continue
            self.add_dock(
                dock_name(GRAPH, title),
                self.hub.shown_title(title),
                lambda title=title: self.hub.graph(title),
                self.hub.type_of(title).icon,
            )

    def add(self, widget) -> None:
        """A graph the hub built, held by its dock from then on: one of the
        procedures (its dock opened, or it got data), or one made later (New
        graph…, a monitor's new unit), whose dock is added now."""
        name = graph_dock(widget)
        if name not in self.docks:
            custom = getattr(widget, "custom", False)
            self.add_dock(
                name,
                widget.shown_title(),
                lambda: widget,
                widget.icon,
                group="Custom" if custom else "",
            )
        self.docks[name].widget().hold(widget)

    def add_dock(
        self, name: str, title: str, build, icon: str, group: str = ""
    ) -> None:
        dock = self.docks.add(
            name,
            title,
            DockBody(build),
            "Graphs",
            theme.icon(icon),
            QtAds.CenterDockWidgetArea,
            group=group,
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
        split = not self.docks.areas_of(GRAPH)  # the graphs come on screen now
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
                    split = True
                else:
                    continue  # stays behind a tab of a group in use
                area = dock.dockAreaWidget()
            used.append(area)
            placed.append(dock)
        # Last: a graph opened into a group and moved on leaves another in front
        for dock in placed:
            dock.setAsCurrentTab()
        if split:  # a layout the user sized keeps its sizes
            self.docks.fit_columns()
            even_out(used)
        self.docks.sync_bodies()

    def rename(self, widget) -> None:
        name = graph_dock(widget)
        if name in self.docks:
            self.docks.retitle(name, widget.shown_title())

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
        AddCurveDialog(self.session.measurements.measured(), graph, self.window).exec()

    def plot(self, measurement) -> None:
        """A saved measurement on the graphs of its procedure, and on those
        its script added while it ran (m.plot)."""
        specs = saved_plots(measurement, self.session.procedures())
        routed = self.hub.route(specs, logger.info)
        self.hub.register_plots(routed)
        for title in self.hub.show_measurement(measurement, routed):
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
