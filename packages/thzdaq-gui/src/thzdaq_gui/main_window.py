"""Main window: Qt Advanced Docking System docks and perspectives, as in the old app.

Every part of the application is a dock the user places anywhere: Setup,
Data and Log (base), one dock per instrument and configured device, one per
measurement and one per graph. The window builds them, its menus and its
toolbar, and keeps the layout of each mode; the parts live apart:

- docking.py: the docks by name and where they open (DockSpace);
- graph_docks.py, device_docks.py: docks that follow the graphs and the station;
- perspectives.py: saved layouts of Pro;
- modes.py: what differs in Lite and Pro;
- update_dialog.py (Updates), workers.py (HangWatch).
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import PySide6QtAds as QtAds
from PySide6.QtCore import QSettings, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QWidget,
    QWidgetAction,
)
from thzdaq_core.measurements.registry import list_procedures
from thzdaq_instruments import InstrumentError

from thzdaq_gui import theme
from thzdaq_gui.device_docks import DeviceDocks
from thzdaq_gui.dock_names import (
    DATA,
    DEVICE,
    GRAPH,
    LOG,
    MEASURE,
    MEASUREMENT,
    PROCESSES,
    SETUP,
    dock_name,
)
from thzdaq_gui.docking import SECTIONS, DockSpace, configure_docking, one_repaint
from thzdaq_gui.docks.body import DockBody
from thzdaq_gui.docks.data import DataWidget
from thzdaq_gui.docks.log import LogWidget
from thzdaq_gui.docks.measure import measure_widget
from thzdaq_gui.docks.processes import ProcessesWidget
from thzdaq_gui.docks.setup import SetupWidget
from thzdaq_gui.exit_dialog import ExitDialog, dump_measurements
from thzdaq_gui.folders import PROFILES
from thzdaq_gui.graph_docks import GraphDocks
from thzdaq_gui.graphs import GraphHub, close_plots
from thzdaq_gui.modes import MODE_KEY, Lite, Pro
from thzdaq_gui.navigator import DockNavigator, QuickFind, type_title
from thzdaq_gui.perspectives import Perspectives
from thzdaq_gui.runbar import MeasurementHost, RunBar
from thzdaq_gui.settings import location
from thzdaq_gui.settings import settings as app_settings
from thzdaq_gui.update_dialog import Updates
from thzdaq_gui.version import __version__
from thzdaq_gui.workers import HangWatch

logger = logging.getLogger(__name__)

DEVICE_HANG_S = 5.0
STATE_VERSION = 3
PROCEDURE_GROUPS = {"sis": "SIS", "if": "IF", "two_sb": "2SB"}


class MainWindow(QMainWindow):
    def __init__(
        self,
        session,
        settings_file: Optional[str] = None,
        restore_layout: bool = True,
        check_updates: bool = True,
        mode: Optional[str] = None,
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
        # Ask on exit (layout, dump); off for smoke runs that close on a timer
        self.confirm_exit = True
        self.setWindowTitle(f"ThzDAQ {__version__}")
        self.setWindowIcon(theme.app_icon())
        self.resize(1500, 900)
        configure_docking()
        self.dock_manager = QtAds.CDockManager(self)
        self.dock_manager.setStyleSheet(theme.dock_style_sheet())
        self.docks = DockSpace(self.dock_manager)
        # Docks are added open and then arranged: build contents only after that
        self.docks.building = True
        self.perspectives = Perspectives(self.docks, self.settings, self)
        self.updates = Updates(self, session.busy)
        # Lite runs the chosen measurement from the bar on top, its widget
        # borrowed into the Measurement dock
        self.runBar = RunBar(list_procedures())
        self.runBar.parameters_requested.connect(lambda: self.show_dock(MEASUREMENT))
        self.measurementHost = MeasurementHost()
        lite = Lite(self.runBar, self.measurementHost, self.docks, self.settings)
        self.modes = {m.key: m for m in (lite, Pro())}
        self.mode = self.modes.get(mode or self.settings.value(MODE_KEY), lite)
        self.hub = GraphHub(self)
        self.graphs = GraphDocks(session, self.hub, self.docks, self.settings, self)
        self.devices = DeviceDocks(session, self.hub, self.docks)

        self.build_menus()
        self.build_toolbar()
        self.stationLabel = QLabel()
        self.statusBar().addPermanentWidget(self.stationLabel)
        session.worker.error.connect(lambda m: self.statusBar().showMessage(m, 10000))
        # Manual control runs in one thread: tell when a device keeps it waiting
        self.hangWatch = HangWatch(session.worker, DEVICE_HANG_S, self)
        self.hangWatch.message.connect(lambda m: self.statusBar().showMessage(m, 2500))

        self.add_base_docks()
        for cls in list_procedures():
            self.add_measure_dock(cls)
        self.docks.add(
            MEASUREMENT, "Measurement", self.measurementHost, "Measures",
            theme.icon("play-circle-outline"), QtAds.RightDockWidgetArea,
            listed=False,
        )  # fmt: skip
        self.graphs.add_all()
        self.devices.sync()
        session.station_changed.connect(self.on_station_changed)
        self.dataWidget.plot_requested.connect(self.graphs.plot)
        self.show_station()

        restored = restore_layout and self.restore_state()
        if not restored:
            self.apply_default_layout()
        self.docks.building = False
        self.apply_mode()
        self.enter_mode()
        # A default layout gets its widths once the window has a size
        self._fit_on_show = not restored
        self.perspectives.refresh()
        if check_updates:
            self.updates.check_in_background()

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
        new_graph.triggered.connect(self.graphs.new)
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
        check = QAction(theme.icon("update"), "Check for updates…", self)
        check.triggered.connect(self.updates.show)
        help_menu.addAction(check)
        about = QAction(theme.icon("information-outline"), "About ThzDAQ", self)
        about.triggered.connect(self.about)
        help_menu.addAction(about)

    def navigator(self, sections=None) -> DockNavigator:
        return DockNavigator(
            self.docks.listed,
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
        self.runBarAction = toolbar.addWidget(self.runBar)
        self.perspectives.add_to(toolbar)
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
        self.modeActions: Dict[str, QAction] = {}
        group = QActionGroup(self)
        for mode in self.modes.values():
            action = QAction(mode.title, self)
            action.setCheckable(True)
            action.setToolTip(mode.tip)
            action.triggered.connect(lambda _=False, key=mode.key: self.set_mode(key))
            group.addAction(action)
            toolbar.addAction(action)
            self.modeActions[mode.key] = action
        toolbar.addSeparator()
        button = QToolButton()
        button.setDefaultAction(find)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setText("Find…  Ctrl+K")
        toolbar.addWidget(button)

    # Docks
    def add_base_docks(self) -> None:
        self.setupWidget = SetupWidget(self.session)
        self.setupWidget.open_profile_requested.connect(self.open_profile)
        self.setupWidget.new_profile_requested.connect(self.new_profile)
        self.dataWidget = DataWidget(self.session)
        self.logWidget = LogWidget()
        self.processesWidget = ProcessesWidget(self.session.processes)
        self.processesWidget.show_requested.connect(self.show_dock)
        for name, title, widget, icon_name, side in (
            (SETUP, "Setup", self.setupWidget, "tune-vertical", QtAds.SideBarLeft),
            (DATA, "Data", self.dataWidget, "database-outline", QtAds.SideBarLeft),
            (LOG, "Event log", self.logWidget, "text-box-outline", QtAds.SideBarBottom),
            (
                PROCESSES,
                "Processes",
                self.processesWidget,
                "progress-clock",
                QtAds.SideBarBottom,
            ),
        ):
            dock = self.docks.add(
                name, title, widget, "Base", theme.icon(icon_name), auto_hide=side
            )
            self.toolbar.insertAction(self.toolbarSpacer, dock.toggleViewAction())
        self.processesWidget.count_changed.connect(self.show_process_count)

    def show_process_count(self, count: int) -> None:
        """How many run, on the Processes tab and toolbar button."""
        self.docks.retitle(PROCESSES, f"Processes ({count})" if count else "Processes")

    def add_measure_dock(self, cls) -> None:
        group = cls.name.split(".")[0]
        icon = theme.icon(theme.procedure_icon_name(cls.name))
        # Built when the dock is first opened (DockBody)
        body = DockBody(lambda: measure_widget(self.session, self.hub, cls))
        self.docks.add(
            dock_name(MEASURE, cls.name), cls.title or cls.name, body, "Measures",
            icon, QtAds.RightDockWidgetArea,
            group=PROCEDURE_GROUPS.get(group, type_title(group)), hint=cls.name,
        )  # fmt: skip

    # Docks as the mode shows them (menus, Ctrl+K, Processes)
    def dock_state(self, name: str) -> str:
        return self.docks.state(self.mode.dock_of(name))

    def show_dock(self, name: str) -> None:
        self.docks.show(self.mode.reveal(name))

    def toggle_dock(self, name: str) -> None:
        if self.mode.dock_of(name) != name:  # shown in another dock: choose it
            self.show_dock(name)
        else:
            self.docks.toggle(name)

    def apply_default_layout(self) -> None:
        """Graphs in the centre, measurements on the right (Lite: the chosen
        one), devices below."""
        self.docks.close_kinds(GRAPH, MEASURE, DEVICE, MEASUREMENT)
        center = self.docks.tab_group(
            QtAds.CenterDockWidgetArea, self.graphs.default_docks()
        )
        self.docks.tab_group(QtAds.RightDockWidgetArea, self.mode.measure_column)
        self.docks.tab_group(
            QtAds.BottomDockWidgetArea, self.devices.default_docks(), center
        )
        if self.mode.perspectives:
            self.perspectives.add_default()

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
        self.show_station()
        if self.session.path is not None:
            self.settings.setValue("station/path", str(self.session.path))

    def open_profile(self) -> None:
        path = self.session.folders.open_path(
            self, PROFILES, "Open station profile", "YAML (*.yaml *.yml)"
        )
        if path:
            self.load_profile(path, self.session.simulate)

    def new_profile(self) -> None:
        path = self.session.folders.save_path(
            self, PROFILES, "New station profile", "", "YAML (*.yaml)"
        )
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

    # Modes
    def apply_mode(self) -> None:
        """The toolbar of the mode: the run bar or perspectives."""
        self.runBarAction.setVisible(self.mode.run_bar)
        self.perspectives.set_visible(self.mode.perspectives)
        self.modeActions[self.mode.key].setChecked(True)

    def enter_mode(self) -> None:
        """After the layout of the mode is restored or made."""
        self.mode.enter()
        self.docks.sync_bodies()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._fit_on_show:
            self._fit_on_show = False
            QTimer.singleShot(0, self.fit_measurements)

    def fit_measurements(self) -> None:
        """After a default layout: the measurement column as wide as its dock
        wants; the layout was made before the dock had its content."""
        dock = self.docks.get(self.mode.measure_column[0])
        area = dock.dockAreaWidget() if dock is not None else None
        if area is None or dock.isClosed():
            return
        self.docks.fit(area, area.currentDockWidget() or dock)

    def set_mode(self, key: str) -> None:
        """Switch modes, each with its own layout; running measurements go on."""
        mode = self.modes[key]
        if mode is self.mode:
            self.apply_mode()
            return
        self.save_layout()
        self.mode.leave()
        self.mode = mode
        self.settings.setValue(MODE_KEY, mode.key)
        self.apply_mode()
        with one_repaint(self):
            restored = self.load_layout()
            if not restored:
                self.apply_default_layout()
            self.enter_mode()
            if not restored:
                self.fit_measurements()
        self.perspectives.refresh()

    # State: geometry, the layout of each mode, perspectives
    def save_layout(self) -> None:
        self.settings.setValue(
            self.mode.state_key, self.dock_manager.saveState(STATE_VERSION)
        )

    def load_layout(self) -> bool:
        """The layout saved for the mode; False: none (or one ADS refused)."""
        state = self.settings.value(self.mode.state_key)
        return state is not None and bool(
            self.dock_manager.restoreState(state, STATE_VERSION)
        )

    def restore_state(self) -> bool:
        try:
            self.perspectives.load()
            geometry = self.settings.value("window/geometry")
            if geometry is not None:
                self.restoreGeometry(geometry)
            return self.load_layout()
        finally:
            self.docks.sync_bodies()

    def save_state(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.save_layout()
        self.settings.setValue(MODE_KEY, self.mode.key)
        self.perspectives.save()

    # Closing
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
        self.updates.install_pending()
        event.accept()
