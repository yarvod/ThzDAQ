"""Main window: Qt Advanced Docking System docks and perspectives, as in the old app.

Every part of the application is a dock the user places anywhere: Setup,
Data and Log (base), one dock per instrument and configured device, one per
measurement and one per graph. Perspectives are named dock layouts (what a
task needs now: SIS tuning, 2SB noise, ...), kept in settings.ini.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

import PySide6QtAds as QtAds
from PySide6.QtCore import QSettings, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QToolButton,
    QWidget,
    QWidgetAction,
)
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.registry import get_procedure, list_procedures
from thzdaq_instruments import InstrumentError

from thzdaq_gui import theme
from thzdaq_gui.docks.body import DockBody
from thzdaq_gui.docks.data import DataWidget
from thzdaq_gui.docks.devices import DeviceWidget, has_content
from thzdaq_gui.docks.log import LogWidget
from thzdaq_gui.docks.measure import measure_widget
from thzdaq_gui.docks.setup import SetupWidget, ask_profile_path
from thzdaq_gui.exit_dialog import ExitDialog, dump_measurements
from thzdaq_gui.graphs import (
    AddCurveDialog,
    GraphHub,
    MapGraphWidget,
    close_plots,
    close_views,
)
from thzdaq_gui.navigator import (
    BEHIND,
    CLOSED,
    FRONT,
    DockEntry,
    DockNavigator,
    Flash,
    QuickFind,
    instrument_type,
    type_title,
)
from thzdaq_gui.update_dialog import Background, UpdateDialog, fetch_job
from thzdaq_gui.updates import can_self_update, latest_update, launch_updater
from thzdaq_gui.settings import location
from thzdaq_gui.settings import settings as app_settings
from thzdaq_gui.version import __version__

logger = logging.getLogger(__name__)

DEFAULT_PERSPECTIVE = "Default"
AUTO_HIDE_SIZES = {"setup": 460, "data": 640, "log": 260}
DEVICE_HANG_S = 5.0
FIT_SHARE = 0.4  # a dock opened on its side takes at most this part of the window
# Where a dock of each kind opens when no dock of its kind is on screen
HOME_AREAS = {
    "graph": QtAds.CenterDockWidgetArea,
    "measure": QtAds.RightDockWidgetArea,
    "device": QtAds.BottomDockWidgetArea,
}
CUSTOM_GRAPHS = "graphs/custom"
STATE_VERSION = 3

PROCEDURE_ICONS = {
    "sis": "alpha-s-box-outline",
    "if": "waveform",
    "two_sb": "chart-bell-curve-cumulative",
    "monitor": "monitor-eye",
    "grid": "rotate-3d-variant",
}
PROCEDURE_GROUPS = {"sis": "SIS", "if": "IF", "two_sb": "2SB"}
SECTIONS = ("Base", "Devices", "Measures", "Graphs")


def configure_docking() -> None:
    """Global ADS flags; must run before the first CDockManager exists."""
    manager = QtAds.CDockManager
    manager.setConfigFlag(manager.FocusHighlighting, True)
    manager.setConfigFlag(manager.OpaqueSplitterResize, True)
    manager.setConfigFlag(manager.DockAreaHasTabsMenuButton, True)
    manager.setConfigFlag(manager.FloatingContainerHasWidgetIcon, True)
    manager.setConfigFlag(manager.AllTabsHaveCloseButton, True)
    # The close button of a tab group closes its current tab, not the whole group
    manager.setConfigFlag(manager.DockAreaCloseButtonClosesTab, True)
    manager.setAutoHideConfigFlags(QtAds.CDockManager.DefaultAutoHideConfig)
    provider = manager.iconProvider()
    for which, name in (
        (QtAds.TabCloseIcon, "close"),
        (QtAds.DockAreaCloseIcon, "close"),
        (QtAds.DockAreaMenuIcon, "chevron-down"),
        (QtAds.DockAreaUndockIcon, "dock-window"),
        (QtAds.DockAreaMinimizeIcon, "window-minimize"),
        (QtAds.AutoHideIcon, "pin-outline"),
    ):
        provider.registerCustomIcon(which, theme.icon(name))


class MainWindow(QMainWindow):
    def __init__(
        self,
        session,
        settings_file: Optional[str] = None,
        restore_layout: bool = True,
        check_updates: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        # The registry of this build (or of runs from sources), or an INI file
        self.settings = (
            QSettings(str(settings_file), QSettings.IniFormat)
            if settings_file
            else app_settings()
        )
        self.updateDialog = None
        self.pending_update: Optional[Path] = None  # a downloaded build to install
        self.perspective: Optional[str] = None
        # Ask on exit (layout, dump); off for smoke runs that close on a timer
        self.confirm_exit = True
        self.setWindowTitle(f"ThzDAQ {__version__}")
        self.setWindowIcon(theme.app_icon())
        self.resize(1500, 900)
        configure_docking()
        self.dock_manager = QtAds.CDockManager(self)
        self.dock_manager.setStyleSheet(theme.dock_style_sheet())
        self.docks: Dict[str, QtAds.CDockWidget] = {}
        self.entries: Dict[str, DockEntry] = {}
        self.dock_signatures: Dict[str, tuple] = {}
        # Docks are added open and then arranged: build contents only after that
        self._building = True
        self.hub = GraphHub(self)
        self.hub.add_curve_request = self.add_curve
        self.hub.graph_created.connect(self.add_graph_dock)
        self.hub.raise_requested.connect(self.raise_graph)
        self.hub.show_requested.connect(
            lambda widget: self.open_dock(graph_dock_name(widget), activate=False)
        )
        self.hub.graph_renamed.connect(self.rename_graph_dock)
        self.hub.graph_removed.connect(self.delete_graph)

        self.build_menus()
        self.build_toolbar()
        self.stationLabel = QLabel()
        self.statusBar().addPermanentWidget(self.stationLabel)
        session.worker.error.connect(lambda m: self.statusBar().showMessage(m, 10000))
        # Manual control runs in one thread: tell when a device keeps it waiting
        self._hang_reported: Optional[float] = None
        self.hangWatch = QTimer(self)
        self.hangWatch.timeout.connect(self.check_device_worker)
        self.hangWatch.start(2000)

        self.add_base_docks()
        for cls in list_procedures():
            self.add_measure_dock(cls)
        for title in self.hub.titles():
            self.hub.graph(title)
        self.load_custom_graphs()
        self.hub.custom_changed.connect(self.save_custom_graphs)
        self.sync_device_docks()
        session.station_changed.connect(self.on_station_changed)
        session.config_changed.connect(self.sync_device_docks)
        self.dataWidget.plot_requested.connect(self.plot_measurement)
        self.show_station()

        restored = restore_layout and self.restore_state()
        if not restored:
            self.apply_default_layout()
        self._building = False
        self.sync_bodies()
        self.refresh_perspectives()
        if check_updates and can_self_update():
            self.updateCheck = Background(fetch_job, self)
            self.updateCheck.done.connect(self.offer_update)
            self.updateCheck.start()

    # Menus and toolbar
    def build_menus(self) -> None:
        bar = self.menuBar()
        file = bar.addMenu("&File")
        for text, icon_name, shortcut, slot in (
            (
                "Open station…",
                "folder-open-outline",
                QKeySequence.Open,
                self.open_profile,
            ),
            ("New station…", "file-plus-outline", QKeySequence.New, self.new_profile),
            ("Reload station", "refresh", None, lambda: self.session.reload()),
        ):
            action = QAction(theme.icon(icon_name), text, self)
            if shortcut is not None:
                action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file.addAction(action)
        self.simulateAction = QAction(
            theme.icon("test-tube"), "Simulate instruments", self
        )
        self.simulateAction.setCheckable(True)
        self.simulateAction.toggled.connect(self.set_simulate)
        file.addAction(self.simulateAction)
        file.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file.addAction(quit_action)
        self.menuBase = bar.addMenu("&Base")
        self.menuDevices = bar.addMenu("&Devices")
        self.menuMeasures = bar.addMenu("&Measures")
        self.menuGraphs = bar.addMenu("&Graphs")
        new_graph = QAction(theme.icon("plus"), "New graph…", self)
        new_graph.triggered.connect(self.new_graph)
        self.menuGraphs.addAction(new_graph)
        self.menuGraphs.addSeparator()
        # Each menu is a search field over the tree of its docks
        self.navigators: Dict[str, DockNavigator] = {}
        for section, menu in zip(
            SECTIONS,
            (self.menuBase, self.menuDevices, self.menuMeasures, self.menuGraphs),
        ):
            navigator = self.navigator((section,))
            action = QWidgetAction(menu)
            action.setDefaultWidget(navigator)
            menu.addAction(action)
            menu.aboutToShow.connect(navigator.prepare)
            navigator.activated.connect(lambda _, m=menu: m.close())
            self.navigators[section] = navigator
        help_menu = bar.addMenu("&Help")
        updates = QAction(theme.icon("update"), "Check for updates…", self)
        updates.triggered.connect(self.show_updates)
        help_menu.addAction(updates)
        about = QAction(theme.icon("information-outline"), "About ThzDAQ", self)
        about.triggered.connect(self.about)
        help_menu.addAction(about)

    def navigator(self, sections=None) -> DockNavigator:
        return DockNavigator(
            self.dock_entries,
            self.dock_state,
            self.show_dock,
            self.toggle_dock,
            sections,
            self.settings,
        )

    def about(self) -> None:
        where = (
            self.settings.fileName()
            if self.settings.format() == QSettings.IniFormat
            else location()
        )
        QMessageBox.about(
            self,
            "About ThzDAQ",
            f"ThzDAQ {__version__}<br>SIS mixer control and measurements<br><br>"
            f"Settings: {where}<br>Data: {Path(self.session.store.root).resolve()}",
        )

    def build_toolbar(self) -> None:
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        self.toolbar = toolbar
        self.perspectives = QComboBox()
        self.perspectives.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.perspectives.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.perspectives.setToolTip("Perspective: a saved layout of docks")
        self.perspectives.textActivated.connect(self.open_perspective)
        label = QLabel(" Perspective ")
        label.setProperty("role", "muted")
        toolbar.addWidget(label)
        toolbar.addWidget(self.perspectives)
        for icon_name, tip, slot in (
            ("view-grid-plus-outline", "Create perspective", self.create_perspective),
            (
                "content-save-outline",
                "Update current perspective",
                self.update_perspective,
            ),
            ("delete-outline", "Delete current perspective", self.delete_perspective),
            ("restore", "Restore the default layout", self.restore_defaults),
        ):
            action = toolbar.addAction(theme.icon(icon_name), tip)
            action.triggered.connect(slot)
        toolbar.addSeparator()
        # Ctrl+K (Cmd+K on macOS) finds any dock, from any window of the app
        self.quickFind = QuickFind(self.navigator(), self)
        find = QAction(theme.icon("magnify"), "Find…", self)
        find.setToolTip("Find a device, measurement or graph (Ctrl+K)")
        find.triggered.connect(self.quickFind.popup)
        self.findShortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.findShortcut.setContext(Qt.ApplicationShortcut)
        self.findShortcut.activated.connect(self.quickFind.popup)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbarSpacer = toolbar.addWidget(spacer)
        button = QToolButton()
        button.setDefaultAction(find)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setText("Find…  Ctrl+K")
        toolbar.addWidget(button)

    # Docks
    def add_dock(
        self,
        name: str,
        title: str,
        widget,
        section: str,
        icon=None,
        area=None,
        auto_hide=None,
        group: str = "",
        hint: str = "",
    ):
        dock = QtAds.CDockWidget(name)
        dock.setWindowTitle(title)
        dock.setWidget(widget)
        if icon is not None:
            dock.setIcon(icon)
        dock.setFeature(QtAds.CDockWidget.DockWidgetDeleteOnClose, False)
        dock.toggleViewAction().setText(title)
        self.entries[name] = DockEntry(
            name, title, section, icon or theme.icon("dock-window"), group, hint
        )
        if isinstance(widget, DockBody):
            dock.viewToggled.connect(
                lambda on, body=widget: self._building or body.set_open(on)
            )
        if auto_hide is not None:
            container = self.dock_manager.addAutoHideDockWidget(auto_hide, dock)
            container.setSize(AUTO_HIDE_SIZES.get(name, 420))
        else:
            self.dock_manager.addDockWidgetTab(area or QtAds.CenterDockWidgetArea, dock)
        self.docks[name] = dock
        if isinstance(widget, DockBody) and not self._building:
            widget.set_open(not dock.isClosed())
        return dock

    def sync_bodies(self) -> None:
        """Content only in open docks (after a layout or perspective is restored)."""
        for dock in self.docks.values():
            body = dock.widget()
            if isinstance(body, DockBody):
                body.set_open(not dock.isClosed())

    # Finding docks (menus, Ctrl+K)
    def dock_entries(self):
        entries = [self.entries[name] for name in self.docks if name in self.entries]
        return sorted(entries, key=lambda e: SECTIONS.index(e.section))

    def dock_state(self, name: str) -> str:
        dock = self.docks.get(name)
        if dock is None or dock.isClosed():
            return CLOSED
        if dock.isAutoHide():
            container = dock.autoHideDockContainer()
            return FRONT if container is not None and container.isVisible() else BEHIND
        return FRONT if dock.isCurrentTab() else BEHIND

    def show_dock(self, name: str) -> None:
        """Wherever the dock is, bring it in front of the user and flash it."""
        dock = self.docks.get(name)
        if dock is None:
            return
        self.open_dock(name)
        window = dock.window()
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()
        self.dock_manager.setDockWidgetFocused(dock)
        Flash(dock)

    def toggle_dock(self, name: str) -> None:
        dock = self.docks.get(name)
        if dock is None:
            return
        if dock.isClosed():
            self.open_dock(name)
        else:
            dock.toggleView(False)
            self.sync_bodies()

    def open_dock(self, name: str, activate: bool = True) -> None:
        """Show a dock where its kind is: a closed one joins the tab group of
        an open dock of the same kind (graphs with graphs, devices with
        devices), or opens on its side; activate brings it to the front."""
        dock = self.docks.get(name)
        if dock is None:
            return
        if dock.isClosed():
            own = dock.dockAreaWidget()
            move = own is None or own.openDockWidgetsCount() == 0
            # Open before moving: ADS keeps the tab of a closed dock it moves
            # into a new area hidden, and the content is built by now
            dock.toggleView(True)
            if move:
                kind = name.split(":", 1)[0]
                area = self.open_area_of(kind, dock)
                if area is not None:
                    self.dock_manager.addDockWidgetTabToArea(dock, area)
                elif kind in HOME_AREAS:
                    area = self.dock_manager.addDockWidget(HOME_AREAS[kind], dock)
                    self.fit_area(area, dock)
            activate = True  # a dock just opened is the one to see
        if activate:
            dock.setAsCurrentTab()
            dock.raise_()
            if dock.isAutoHide() and dock.autoHideDockContainer() is not None:
                dock.autoHideDockContainer().collapseView(False)
        self.sync_bodies()

    def fit_area(self, area, dock) -> None:
        """A new area on a side as wide (or tall) as its dock wants, up to
        FIT_SHARE of the window: ADS sizes it before the content exists."""
        splitter = area.parentWidget() if area is not None else None
        if not isinstance(splitter, QSplitter):
            return
        index, sizes = splitter.indexOf(area), splitter.sizes()
        if index < 0 or len(sizes) < 2:
            return
        horizontal = splitter.orientation() == Qt.Horizontal
        hint = dock.widget().sizeHint()
        wanted = (
            hint.width() if horizontal else hint.height()
        ) + self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        wanted = min(wanted, int(sum(sizes) * FIT_SHARE))
        if sizes[index] >= wanted:
            return
        # Taken from the largest neighbour (the graphs)
        other = max((i for i in range(len(sizes)) if i != index), key=sizes.__getitem__)
        sizes[other] -= wanted - sizes[index]
        sizes[index] = wanted
        splitter.setSizes(sizes)

    def open_area_of(self, kind: str, besides):
        """The tab group holding the most open docks of this kind (not floating)."""
        counts = {}
        for name, dock in self.docks.items():
            if dock is besides or dock.isClosed() or not name.startswith(kind + ":"):
                continue
            area = dock.dockAreaWidget()
            if area is None or dock.isFloating() or dock.isAutoHide():
                continue
            counts[area] = counts.get(area, 0) + 1
        return max(counts, key=counts.get) if counts else None

    def remove_dock(self, name: str) -> None:
        dock = self.docks.pop(name, None)
        if dock is None:
            return
        widget = dock.widget()
        if isinstance(widget, DockBody):
            widget.dispose()
        elif hasattr(widget, "stop"):
            widget.stop()
        if widget is not None:
            close_views(widget)
        self.entries.pop(name, None)
        self.dock_manager.removeDockWidget(dock)
        dock.deleteLater()

    def add_base_docks(self) -> None:
        self.setupWidget = SetupWidget(self.session)
        self.setupWidget.open_profile_requested.connect(self.open_profile)
        self.setupWidget.new_profile_requested.connect(self.new_profile)
        self.dataWidget = DataWidget(self.session)
        self.logWidget = LogWidget()
        for name, title, widget, icon_name, side in (
            ("setup", "Setup", self.setupWidget, "tune-vertical", QtAds.SideBarLeft),
            ("data", "Data", self.dataWidget, "database-outline", QtAds.SideBarLeft),
            (
                "log",
                "Event log",
                self.logWidget,
                "text-box-outline",
                QtAds.SideBarBottom,
            ),
        ):
            dock = self.add_dock(
                name, title, widget, "Base", theme.icon(icon_name), auto_hide=side
            )
            self.toolbar.insertAction(self.toolbarSpacer, dock.toggleViewAction())

    def add_measure_dock(self, cls) -> None:
        group = cls.name.split(".")[0]
        icon = theme.icon(PROCEDURE_ICONS.get(group, "play-circle-outline"))
        # Built when the dock is first opened (DockBody)
        body = DockBody(lambda: measure_widget(self.session, self.hub, cls))
        self.add_dock(
            f"measure:{cls.name}", cls.title or cls.name, body, "Measures",
            icon, QtAds.RightDockWidgetArea,
            group=PROCEDURE_GROUPS.get(group, type_title(group)), hint=cls.name,
        )  # fmt: skip

    def add_graph_dock(self, widget) -> None:
        name = graph_dock_name(widget)
        if name in self.docks:
            return
        icon = theme.icon(
            "grid" if isinstance(widget, MapGraphWidget) else "chart-line"
        )
        dock = self.add_dock(
            name,
            widget.title,
            widget,
            "Graphs",
            icon,
            QtAds.CenterDockWidgetArea,
            group="Custom" if getattr(widget, "custom", False) else "",
            hint=name,
        )
        if not self._building:
            # Made later (New graph…, a monitor's new unit): opens with the graphs
            dock.toggleView(False)

    def raise_graph(self, widget) -> None:
        self.open_dock(graph_dock_name(widget))

    def rename_graph_dock(self, widget) -> None:
        name = graph_dock_name(widget)
        dock = self.docks.get(name)
        if dock is not None:
            dock.setWindowTitle(widget.title)
            dock.toggleViewAction().setText(widget.title)
            self.entries[name].title = widget.title

    def delete_graph(self, widget) -> None:
        answer = QMessageBox.question(
            self, "Delete graph", f"Delete the graph {widget.title!r} and its curves?"
        )
        if answer != QMessageBox.Yes:
            return
        self.hub.remove(widget)
        self.remove_dock(graph_dock_name(widget))

    def load_custom_graphs(self) -> None:
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

    def save_custom_graphs(self) -> None:
        self.settings.setValue(CUSTOM_GRAPHS, json.dumps(self.hub.custom_graphs()))

    def device_refs(self):
        station = self.session.station
        if station is None:
            return []
        # Fixed channels live inside their instrument's dock; an instrument with
        # nothing to show (a SIS block: its parts are devices) gets no dock
        return [
            info
            for info in station.devices()
            if info.kind != "channel" and has_content(station, info)
        ]

    def dock_signature(self, info) -> tuple:
        """What a device dock is built from; it is rebuilt only when this changes.

        Instrument settings (multiplier, OEM head) are left out: the dock writes
        them itself and must survive saving them.
        """
        station = self.session.station
        spec = station.config.instruments[info.instrument]
        found = station.config.find_device(info.ref)
        device = found[1] if found else None
        return (
            info,
            spec.driver,
            spec.title,
            spec.simulate or self.session.simulate,
            repr(device),
        )

    def sync_device_docks(self, *_) -> None:
        wanted = {f"device:{info.ref}": info for info in self.device_refs()}
        for name in [
            n for n in self.docks if n.startswith("device:") and n not in wanted
        ]:
            self.remove_dock(name)
            self.dock_signatures.pop(name, None)
        for name, info in wanted.items():
            signature = self.dock_signature(info)
            dock = self.docks.get(name)
            if dock is not None and self.dock_signatures.get(name) == signature:
                continue
            factory = lambda ref=info.ref: self.device_widget(ref)  # noqa: E731
            self.dock_signatures[name] = signature
            icon = theme.device_icon(info.kind, info.instrument)
            group, hint = self.device_group(info)
            if dock is None:
                dock = self.add_dock(
                    name,
                    info.title,
                    DockBody(factory),
                    "Devices",
                    icon,
                    QtAds.BottomDockWidgetArea,
                    group=group,
                    hint=hint,
                )
                if not getattr(self, "_restoring", False):
                    dock.toggleView(False)
            else:
                dock.widget().replace(factory)
                dock.setWindowTitle(info.title)
                dock.toggleViewAction().setText(info.title)
                entry = self.entries[name]
                entry.title, entry.icon, entry.group, entry.hint = (
                    info.title, icon, group, hint,
                )  # fmt: skip

    def device_group(self, info):
        """Branch of the menu (the type: SIS bias, Power supply) and words to search."""
        spec = self.session.station.config.instruments[info.instrument]
        key = (
            info.kind if info.kind != "instrument" else instrument_type(info.instrument)
        )
        return type_title(key), f"{info.ref} {info.instrument} {spec.driver}"

    def device_widget(self, ref: str) -> QWidget:
        try:
            return DeviceWidget(self.session, self.hub, ref)
        except (InstrumentError, KeyError) as e:
            logger.error(f"Device dock {ref}: {e}")
            label = QLabel(f"{ref}: {e}")
            label.setWordWrap(True)
            return label

    def check_device_worker(self) -> None:
        worker = self.session.worker
        waiting = worker.busy_for()
        if waiting <= DEVICE_HANG_S:
            self._hang_reported = None
            return
        device = worker.current or "A device"
        self.statusBar().showMessage(
            f"{device} has not answered for {waiting:.0f} s; manual control waits. "
            "Reset its connection in Setup → Connections.",
            2500,
        )
        # Once per hang in the event log
        if self._hang_reported != worker.started_at:
            self._hang_reported = worker.started_at
            logger.warning(
                f"{device} does not answer: manual control and monitors wait for it"
            )

    # Station
    def show_station(self) -> None:
        station = self.session.station
        if station is None:
            self.stationLabel.setText("No station")
            return
        mode = "  SIMULATION" if self.session.simulate else ""
        self.stationLabel.setText(f"Station: {station.name}{mode}")
        with QSignalBlocker(self.simulateAction):
            self.simulateAction.setChecked(self.session.simulate)

    def on_station_changed(self, station) -> None:
        self.dock_signatures.clear()  # another Station: every dock is rebuilt
        self.sync_device_docks()
        self.show_station()
        if self.session.path is not None:
            self.settings.setValue("station/path", str(self.session.path))

    def open_profile(self) -> None:
        path = ask_profile_path(self, save=False)
        if path:
            self.load_profile(path, self.session.simulate)

    def new_profile(self) -> None:
        path = ask_profile_path(self, save=True)
        if path:
            try:
                self.session.new_station(path, Path(path).stem)
            except (InstrumentError, OSError) as e:
                QMessageBox.critical(self, "Station profile", str(e))

    def load_profile(self, path, simulate: bool) -> None:
        if self.session.busy():
            QMessageBox.warning(self, "Station", "Stop the running measurements first")
            return
        try:
            self.session.load_station(path, simulate)
        except (InstrumentError, OSError) as e:
            QMessageBox.critical(self, "Station profile", str(e))

    def set_simulate(self, on: bool) -> None:
        if self.session.path is not None and on != self.session.simulate:
            self.load_profile(self.session.path, on)
            self.show_station()

    # Graphs and data
    def add_curve(self, graph) -> None:
        AddCurveDialog(self.session.measurements.items, graph, self).exec()

    def new_graph(self) -> None:
        title, ok = QInputDialog.getText(self, "New graph", "Title")
        if ok and title.strip():
            try:
                widget = self.hub.new_graph(title.strip())
            except ValueError as e:
                QMessageBox.warning(self, "New graph", str(e))
                return
            self.raise_graph(widget)

    def plot_measurement(self, measurement) -> None:
        try:
            specs = get_procedure(measurement.procedure).plots
        except ProcedureError:
            specs = ()
        for title in self.hub.show_measurement(measurement, specs):
            self.hub.raise_graph(title)

    # Perspectives
    def refresh_perspectives(self) -> None:
        with QSignalBlocker(self.perspectives):
            self.perspectives.clear()
            self.perspectives.addItems(self.dock_manager.perspectiveNames())
            if self.perspective:
                self.perspectives.setCurrentText(self.perspective)

    def open_perspective(self, name: str) -> None:
        if not name:
            return
        # One repaint for the new layout instead of every step of the rebuild
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.setUpdatesEnabled(False)
        try:
            self.dock_manager.openPerspective(name)
            self.sync_bodies()
        finally:
            self.setUpdatesEnabled(True)
            QApplication.restoreOverrideCursor()
        self.perspective = name

    def create_perspective(self) -> None:
        name, ok = QInputDialog.getText(self, "Create perspective", "Unique name")
        if ok and name.strip():
            self.dock_manager.addPerspective(name.strip())
            self.perspective = name.strip()
            self.refresh_perspectives()
            self.save_perspectives()

    def update_perspective(self) -> None:
        name = self.perspectives.currentText()
        if name:
            self.dock_manager.addPerspective(name)
            self.save_perspectives()

    def delete_perspective(self) -> None:
        name = self.perspectives.currentText()
        if not name:
            return
        answer = QMessageBox.question(
            self, "Delete perspective", f"Delete perspective {name!r}?"
        )
        if answer == QMessageBox.Yes:
            self.dock_manager.removePerspective(name)
            self.perspective = None
            self.refresh_perspectives()
            self.save_perspectives()

    def restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Default layout",
            "Arrange the docks as by default? Perspectives stay.",
        )
        if answer == QMessageBox.Yes:
            self.apply_default_layout()

    def apply_default_layout(self) -> None:
        """Graphs in the centre, measurements on the right, devices below."""
        for name, dock in self.docks.items():
            if name.startswith(("graph:", "measure:", "device:")):
                dock.toggleView(False)
        center = None
        for title in ("I-V", "P-V", "Y-V", "P-IF"):
            dock = self.docks.get(f"graph:{title}")
            if dock is None:
                continue
            if center is None:
                center = self.dock_manager.addDockWidget(
                    QtAds.CenterDockWidgetArea, dock
                )
            else:
                self.dock_manager.addDockWidgetTabToArea(dock, center)
            dock.toggleView(True)
        right = None
        for name in (
            "measure:sis.iv_curve",
            "measure:sis.pv_curve",
            "measure:monitor.time",
        ):
            dock = self.docks.get(name)
            if dock is None:
                continue
            if right is None:
                right = self.dock_manager.addDockWidget(QtAds.RightDockWidgetArea, dock)
            else:
                self.dock_manager.addDockWidgetTabToArea(dock, right)
            dock.toggleView(True)
        bottom = None
        for info in self.device_refs():
            if info.kind not in ("sis_bias", "sis_coil"):
                continue
            dock = self.docks[f"device:{info.ref}"]
            if bottom is None:
                bottom = self.dock_manager.addDockWidget(
                    QtAds.BottomDockWidgetArea, dock, center
                )
            else:
                self.dock_manager.addDockWidgetTabToArea(dock, bottom)
            dock.toggleView(True)
        if DEFAULT_PERSPECTIVE not in self.dock_manager.perspectiveNames():
            self.dock_manager.addPerspective(DEFAULT_PERSPECTIVE)
            self.perspective = DEFAULT_PERSPECTIVE

    def save_perspectives(self) -> None:
        self.settings.remove("Perspectives")
        self.dock_manager.savePerspectives(self.settings)
        self.settings.sync()

    def restore_state(self) -> bool:
        self._restoring = True
        try:
            self.dock_manager.loadPerspectives(self.settings)
            self.perspective = self.settings.value("perspective") or None
            geometry = self.settings.value("window/geometry")
            if geometry is not None:
                self.restoreGeometry(geometry)
            state = self.settings.value("window/docks")
            if state is None:
                return False
            return bool(self.dock_manager.restoreState(state, STATE_VERSION))
        finally:
            self.sync_bodies()
            self._restoring = False

    def save_state(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue(
            "window/docks", self.dock_manager.saveState(STATE_VERSION)
        )
        self.settings.setValue("perspective", self.perspective or "")
        self.save_perspectives()

    # Updates
    def show_updates(self) -> None:
        if self.updateDialog is None:
            self.updateDialog = UpdateDialog(
                quit_app=self.quit_for_update, busy=self.session.busy, parent=self
            )
        self.updateDialog.check()
        self.updateDialog.show()
        self.updateDialog.raise_()

    def offer_update(self, releases) -> None:
        release = latest_update(releases)
        if release is None:
            return
        button = QPushButton(theme.icon("update"), f"Update to {release.tag}")
        button.setFlat(True)
        button.clicked.connect(self.show_updates)
        self.statusBar().addPermanentWidget(button)

    # Closing
    def quit_for_update(self, build: Path) -> None:
        """Close and install the downloaded build; if closing is cancelled, the
        build stays ready and installs when the window is closed later."""
        self.pending_update = build
        if not self.close():
            QMessageBox.information(
                self,
                "Update",
                "The update is downloaded: it installs when you close ThzDAQ.",
            )

    def start_pending_update(self) -> None:
        if self.pending_update is None:
            return
        try:
            launch_updater(self.pending_update)
        except Exception as e:
            logger.error(f"Update not started: {e}")
            QMessageBox.critical(self, "Update", f"The update did not start: {e}")

    def closeEvent(self, event) -> None:
        store_state, dump = True, False
        if self.confirm_exit:
            running = sum(runner.running for runner in self.session.runners)
            dialog = ExitDialog(running, self.session.measurements.rowCount(), self)
            if dialog.exec() != QDialog.Accepted:
                event.ignore()
                return
            store_state = dialog.storeState.isChecked()
            dump = dialog.dumpData.isChecked()
        for dock in self.docks.values():
            widget = dock.widget()
            if hasattr(widget, "stop"):
                widget.stop()
        if store_state:
            self.save_state()
        self.logWidget.detach()
        self.session.shutdown()
        if dump and self.session.measurements.items:
            try:
                path = dump_measurements(
                    self.session.measurements.items, self.session.store.root
                )
                logger.info(f"Measurements dumped to {path}")
            except OSError as e:
                QMessageBox.warning(self, "Dump", f"Could not dump measurements: {e}")
        close_plots()
        self.dock_manager.deleteLater()
        # Last: the updater waits for this process to end, then replaces the files
        self.start_pending_update()
        event.accept()


def graph_dock_name(widget) -> str:
    return f"graph:{getattr(widget, 'key', widget.title)}"
