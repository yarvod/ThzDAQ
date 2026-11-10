"""Main window: Qt Advanced Docking System docks and perspectives, as in the old app.

Every part of the application is a dock the user places anywhere: Setup,
Data and Log (base), one dock per instrument and configured device, one per
measurement and one per graph. The window builds them, its menus and its
toolbar, and keeps the layout of each mode; the parts live apart:

- docking.py: the docks by name and where they open (DockSpace);
- graph_docks.py, device_docks.py: docks that follow the graphs and the station;
- perspectives.py: saved layouts of Pro;
- modes.py: what differs in Lite and Pro;
- workspace_menu.py: the workspace in the File menu;
- update_dialog.py (Updates), workers.py (HangWatch).
"""

import logging
from pathlib import Path
from typing import Callable, Dict, Optional

import PySide6QtAds as QtAds
from PySide6.QtCore import QMetaObject, QSettings, QSignalBlocker, Qt, Slot
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
    QWidgetAction,
)
from thzdaq_api import examples
from thzdaq_api.daemon import StopMode
from thzdaq_api.errors import LabError

from thzdaq_gui import theme
from thzdaq_gui.device_docks import DeviceDocks
from thzdaq_gui.dock_names import (
    DAEMON,
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
from thzdaq_gui.docks.data import DataWidget
from thzdaq_gui.docks.log import LogWidget
from thzdaq_gui.docks.processes import ProcessesWidget
from thzdaq_gui.docks.setup import SetupWidget
from thzdaq_gui.docks.daemon import DaemonIndicator, DaemonWidget, LostBanner
from thzdaq_gui.approval_dialog import ApprovalPrompts
from thzdaq_gui.exit_dialog import (
    ExitDialog,
    dump_measurements,
    stop_by_default,
    stop_mode,
)
from thzdaq_gui.folders import PROFILES
from thzdaq_gui.code_docks import CodeDocks
from thzdaq_gui.graph_docks import GraphDocks
from thzdaq_gui.measure_docks import MeasureDocks
from thzdaq_gui.graphs import GraphHub, close_plots
from thzdaq_gui.run_graphs import RunGraphs
from thzdaq_gui.models.approvals import ApprovalsModel
from thzdaq_gui.models.daemon import LOST, DaemonModel
from thzdaq_gui.modes import Lite, Pro
from thzdaq_gui.navigator import DockNavigator, QuickFind
from thzdaq_gui.perspectives import Perspectives
from thzdaq_gui.safe_state import SafeStateAction
from thzdaq_gui.runbar import MeasurementHost, RunBar
from thzdaq_gui.settings import MODE, STATION_PATH, WINDOW_GEOMETRY, location
from thzdaq_gui.settings import settings as app_settings
from thzdaq_gui.update_dialog import Updates
from thzdaq_gui.version import __version__
from thzdaq_gui.wording import NEW_PROFILE, OPEN_PROFILE, STATION_PROFILE
from thzdaq_gui.workers import HangWatch
from thzdaq_gui.workspace_menu import WorkspaceMenu

logger = logging.getLogger(__name__)

DEVICE_HANG_S = 5.0
STATE_VERSION = 3


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
        # Closed, it is deleted with its docks, graphs and timers
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.session = session
        # The registry of this build (or of runs from sources), or an INI file
        self.settings = (
            QSettings(str(settings_file), QSettings.IniFormat)
            if settings_file
            else app_settings()
        )
        # Ask on exit (layout, dump); off for smoke runs that close on a timer
        self.confirm_exit = True
        self.show_workspace()
        session.workspace.changed.connect(self.show_workspace)
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
        self.runBar = RunBar(session.procedures())
        self.runBar.parameters_requested.connect(lambda: self.show_dock(MEASUREMENT))
        self.measurementHost = MeasurementHost()
        lite = Lite(self.runBar, self.measurementHost, self.docks, self.settings)
        self.modes = {m.key: m for m in (lite, Pro())}
        self.mode = self.modes.get(mode or self.settings.value(MODE), lite)
        self.hub = GraphHub(session.procedures(), session.call, self)
        self.graphs = GraphDocks(session, self.hub, self.docks, self.settings, self)
        self.devices = DeviceDocks(session, self.hub, self.docks)
        self.code = CodeDocks(session, self.docks, self, self.start_measurement)
        self.measures = MeasureDocks(
            session, self.hub, self.docks, self.code.open_custom
        )

        self.daemon = DaemonModel(session, self)
        self.approvals = ApprovalsModel(session, self)
        self.approvalPrompts = ApprovalPrompts(self.approvals, self)
        self.workspaceMenu = WorkspaceMenu(session, self.load_profile, self)
        self.build_menus()
        self.build_toolbar()
        self.stationLabel = QLabel()
        self.statusBar().addPermanentWidget(self.stationLabel)
        self.daemonIndicator = DaemonIndicator(self.daemon)
        self.daemonIndicator.clicked.connect(lambda: self.show_dock(DAEMON))
        self.statusBar().addPermanentWidget(self.daemonIndicator)
        # A row of its own over the docks while the daemon does not answer
        self.lostBanner = LostBanner(self.daemon)
        self.lostBanner.daemon_requested.connect(lambda: self.show_dock(DAEMON))
        self.bannerBar = QToolBar("Daemon connection")
        self.bannerBar.setObjectName("daemon_banner")
        self.bannerBar.setMovable(False)
        self.bannerBar.addWidget(self.lostBanner)
        self.addToolBarBreak()
        self.addToolBar(Qt.TopToolBarArea, self.bannerBar)
        self.daemon.changed.connect(self.show_daemon)
        session.calls.error.connect(lambda m: self.statusBar().showMessage(m, 10000))
        # Calls of a device wait for it in the daemon: tell when one keeps them waiting
        self.hangWatch = HangWatch(session.calls, DEVICE_HANG_S, self)
        self.hangWatch.message.connect(lambda m: self.statusBar().showMessage(m, 2500))

        self.add_base_docks()
        self.measures.sync()
        self.docks.add(
            MEASUREMENT, "Measurement", self.measurementHost, "Measures",
            theme.icon("play-circle-outline"), QtAds.RightDockWidgetArea,
            listed=False,
        )  # fmt: skip
        self.graphs.add_all()
        self.devices.sync()
        session.station_changed.connect(self.on_station_changed)
        self.dataWidget.plot_requested.connect(self.graphs.plot)
        self.dataWidget.script_requested.connect(self.code.open_text)
        session.procedures_changed.connect(self.on_procedures_changed)
        self.show_station()

        restored = restore_layout and self.restore_state()
        if not restored:
            self.apply_default_layout()
        self.docks.hide_empty_splitters()  # the window is not shown yet
        self.docks.building = False
        self.apply_mode()
        self.enter_mode()
        self.show_daemon()  # the banner as the daemon is, not as a layout saved it
        # A default layout gets its widths once the window has a size
        self._fit_on_show = not restored
        self.perspectives.refresh()
        self.runGraphs = RunGraphs(self.hub, parent=self)
        self.runGraphs.follow_all(session.run_events)
        if check_updates:
            self.updates.check_in_background()

    # Menus and toolbar
    def build_menus(self) -> None:
        bar = self.menuBar()
        file = bar.addMenu("&File")
        self.workspaceMenu.add_to(file)
        file.addSeparator()
        for text, icon_name, shortcut, slot in (
            (
                "Open station…",
                "folder-open-outline",
                QKeySequence.Open,
                self.open_profile,
            ),
            ("New station…", "file-plus-outline", QKeySequence.New, self.new_profile),
            ("Reload station", "refresh", None, self.reload_profile),
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
        new_measurement = QAction(theme.icon("plus"), "New measurement…", self)
        new_measurement.setToolTip("A measurement of the bench's own: a script")
        new_measurement.triggered.connect(self.code.new_measurement)
        self.menuMeasures.addAction(new_measurement)
        from_example = self.menuMeasures.addMenu(
            theme.icon("book-open-outline"), "From an example"
        )
        for example in examples.examples():
            action = from_example.addAction(example.title)
            action.setToolTip(example.about)
            action.triggered.connect(
                lambda _=False, name=example.name: self.code.from_example(name)
            )
        self.menuMeasures.addSeparator()
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
            f"Settings: {where}<br>Data: {self.session.data_root.resolve()}",
        )

    def build_toolbar(self) -> None:
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        self.toolbar = toolbar
        self.runBarAction = toolbar.addWidget(self.runBar)
        self.perspectives.add_to(toolbar)
        toolbar.addSeparator()
        self.safeState = SafeStateAction(self.session, self)
        safe = QToolButton()
        safe.setDefaultAction(self.safeState)
        safe.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.addWidget(safe)
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
        self.daemonWidget = DaemonWidget(self.daemon)
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
            (DAEMON, "Daemon", self.daemonWidget, "server", QtAds.SideBarBottom),
        ):
            dock = self.docks.add(
                name, title, widget, "Base", theme.icon(icon_name), auto_hide=side
            )
            self.toolbar.insertAction(self.toolbarSpacer, dock.toggleViewAction())
        self.processesWidget.count_changed.connect(self.show_process_count)

    def show_process_count(self, count: int) -> None:
        """How many run, on the Processes tab and toolbar button."""
        self.docks.retitle(PROCESSES, f"Processes ({count})" if count else "Processes")

    def on_procedures_changed(self) -> None:
        """The bench's own measurements changed: the mode lets go of one that
        goes, then the docks, the bar and the graphs follow."""
        procedures = self.session.procedures()
        self.mode.procedures_changed([p.name for p in procedures])
        self.measures.sync()
        self.runBar.set_procedures(procedures)

    def start_measurement(self, procedure: str) -> None:
        """Start a measurement as its dock does, with the values of its form
        (Run in the dock of its script)."""
        name = dock_name(MEASURE, procedure)
        if name not in self.docks:
            return
        self.show_dock(name)
        self.docks[name].widget().content().box.start()

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
        """Devices on the left, graphs in the centre, measurements on the
        right (Lite: the chosen one)."""
        self.docks.close_kinds(GRAPH, MEASURE, DEVICE, MEASUREMENT)
        self.docks.tab_group(QtAds.CenterDockWidgetArea, self.graphs.default_docks())
        self.docks.tab_group(QtAds.RightDockWidgetArea, self.mode.measure_column)
        self.docks.tab_group(QtAds.LeftDockWidgetArea, self.devices.default_docks())
        if self.mode.perspectives:
            self.perspectives.add_default()

    def show_workspace(self) -> None:
        """The title names the workspace: windows in several are told apart."""
        self.setWindowTitle(f"{self.session.workspace.name} — ThzDAQ {__version__}")

    # Station: the profile of the lab the window works with
    def show_station(self) -> None:
        profile = self.session.profile()
        if profile.path is None:
            self.stationLabel.setText("No station")
        else:
            mode = "  SIMULATION" if self.session.simulate else ""
            self.stationLabel.setText(f"Station: {profile.name}{mode}")
        with QSignalBlocker(self.simulateAction):
            self.simulateAction.setChecked(self.session.simulate)

    def on_station_changed(self) -> None:
        self.show_station()
        path = self.session.profile().path
        if path is not None:
            self.settings.setValue(STATION_PATH, path)

    def open_profile(self) -> None:
        path = self.session.folders.open_path(
            self, PROFILES, OPEN_PROFILE, "YAML (*.yaml *.yml)"
        )
        if path:
            self.load_profile(path)

    def new_profile(self) -> None:
        path = self.session.folders.save_path(
            self, PROFILES, NEW_PROFILE, "", "YAML (*.yaml)"
        )
        if path:
            self.told(lambda: self.session.new_profile(path, Path(path).stem))

    def load_profile(self, path) -> None:
        self.told(lambda: self.session.load_profile(path))

    def reload_profile(self) -> None:
        self.told(self.session.reload)

    def told(self, change) -> None:
        """A change of the profile; a refusal of the lab (measurements run, a
        broken file) is told."""
        try:
            change()
        except LabError as e:
            QMessageBox.critical(self, STATION_PROFILE, str(e))

    def set_simulate(self, on: bool) -> None:
        """Work with the simulator's daemon (or the instruments' again), on the
        same profile."""
        if on == self.session.simulate:
            return
        path = self.session.profile().path
        try:
            self.session.open(on)
        except LabError as e:
            QMessageBox.critical(self, "Daemon", str(e))
            self.show_station()
            return
        if path is not None and self.session.profile().path != path:
            self.load_profile(path)

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
            # Queued to the window, dropped with it: PySide's QTimer.singleShot
            # holds the method in a timer of its own, keeping a window closed
            # before the timer fires alive
            QMetaObject.invokeMethod(self, "fit_columns", Qt.QueuedConnection)

    @Slot()
    def fit_columns(self) -> None:
        """After a default layout: the device and measurement columns as wide
        as their docks want, the graphs the rest; the layout was made before
        the docks had their content."""
        self.docks.fit_columns()

    def set_mode(self, key: str) -> None:
        """Switch modes, each with its own layout; running measurements go on."""
        mode = self.modes[key]
        if mode is self.mode:
            self.apply_mode()
            return
        self.save_layout()
        self.mode.leave()
        self.mode = mode
        self.settings.setValue(MODE, mode.key)
        self.apply_mode()
        with one_repaint(self):
            restored = self.load_layout()
            if not restored:
                self.apply_default_layout()
            self.enter_mode()
            if not restored:
                self.fit_columns()
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
            geometry = self.settings.value(WINDOW_GEOMETRY)
            if geometry is not None:
                self.restoreGeometry(geometry)
            return self.load_layout()
        finally:
            self.docks.sync_bodies()

    def save_state(self) -> None:
        self.settings.setValue(WINDOW_GEOMETRY, self.saveGeometry())
        self.save_layout()
        self.settings.setValue(MODE, self.mode.key)
        self.perspectives.save()

    # Closing
    def show_daemon(self) -> None:
        self.bannerBar.setVisible(self.daemon.state == LOST)

    def stop_daemon(self, stop: Callable[[StopMode], None], running: int) -> None:
        """With the window, as chosen; a daemon that refuses is left running."""
        try:
            stop(stop_mode(running))
        except LabError as e:
            logger.warning(f"The daemon was not stopped: {e}")

    def closeEvent(self, event) -> None:
        if self.confirm_exit and self.code.unsaved():
            answer = QMessageBox.question(
                self, "Quit", "Scripts have changes not saved: quit without them?"
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        store_state, dump = True, False
        status = self.daemon.ask()
        running = len(status.runs) if status is not None else 0
        others = self.daemon.others()
        # An update replaces the files of the daemons: they stop with the window
        updating = self.updates.pending is not None
        stop = status is not None and (updating or stop_by_default(running, others))
        left = self.daemon.ask_left()
        stop_left = left is not None and (
            updating or stop_by_default(left.running, left.others)
        )
        if self.confirm_exit:
            dialog = ExitDialog(
                running,
                len(self.session.measurements.measured()),
                others,
                status is not None,
                left,
                updating,
                self,
            )
            if dialog.exec() != QDialog.Accepted:
                event.ignore()
                return
            store_state = dialog.storeState.isChecked()
            dump = dialog.dumpData.isChecked()
            if not updating:  # an update stops them whatever the boxes say
                stop = dialog.stopDaemon.isChecked()
                stop_left = dialog.stopLeft is not None and dialog.stopLeft.isChecked()
        if store_state:
            self.save_state()
        # Before the session stops calling the lab: monitors cancel their polls
        self.docks.close()
        self.daemon.close()
        self.logWidget.detach()
        if stop:
            self.stop_daemon(self.daemon.stop_now, running)
        if stop_left:
            self.stop_daemon(self.daemon.stop_left, left.running)
        self.session.shutdown()
        if dump and self.session.measurements.measured():
            try:
                path = dump_measurements(
                    self.session.measurements.measured(), self.session.data_root
                )
                logger.info(f"Measurements dumped to {path}")
            except OSError as e:
                QMessageBox.warning(self, "Dump", f"Could not dump measurements: {e}")
        close_plots()
        # Last: the updater waits for this process to end, then replaces the files
        self.updates.install_pending()
        event.accept()
