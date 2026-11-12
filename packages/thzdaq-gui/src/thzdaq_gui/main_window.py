"""Main window: Qt Advanced Docking System docks, as in the old app.

Setup and Data, Processes, Log, Daemon, Editor (a tab per script's file),
Console (a tab per Python console) and Assistant (the chat with a model that
uses the bench's tools) are docks pinned to the side bars (base); every instrument and configured
device has a dock, and every graph, placed where the user wants.
Measurements are chosen, set and run from the bar on top: the drop-down under
its settings button shows the form of the chosen one. The window builds
them, its menus and its toolbar, and keeps one layout; the parts live apart:

- docking.py: the docks by name and where they open (DockSpace);
- graph_docks.py, device_docks.py: docks that follow the graphs and the
  station; code_docks.py: the files in Editor; console_docks.py: the
  consoles in Console;
- measure_forms.py: the forms of the measurements, following the catalog;
- runbar.py: the measurement chosen, set, started and stopped on top;
- navigator.py: the menus that find docks and Ctrl+K (Places: docks and
  measurements);
- guide.py: what agents ask of the window (WindowGuide: its state, places
  shown, a form filled, highlights drawn by overlay.py);
- workspace_menu.py: the workspace in the File menu;
- update_dialog.py (Updates), workers.py (HangWatch).
"""

import logging
from pathlib import Path
from typing import Callable, Dict, Optional

import PySide6QtAds as QtAds
from PySide6.QtCore import QMetaObject, QSettings, QSignalBlocker, Qt, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
    QToolButton,
    QWidgetAction,
)
from thzdaq_api.daemon import StopMode
from thzdaq_api.errors import LabError

from thzdaq_gui import theme
from thzdaq_gui.device_docks import DeviceDocks
from thzdaq_gui.dock_names import (
    ASSISTANT,
    CONSOLE,
    DAEMON,
    DATA,
    DEVICE,
    EDITOR,
    GRAPH,
    LOG,
    PROCESSES,
    SETUP,
)
from thzdaq_gui.docking import DockSpace, configure_docking
from thzdaq_gui.docks.assistant import AssistantWidget
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
from thzdaq_gui.console_docks import ConsoleDocks
from thzdaq_gui.graph_docks import GraphDocks
from thzdaq_gui.measure_forms import MeasureForms
from thzdaq_gui.graphs import GraphHub, close_plots
from thzdaq_gui.run_graphs import RunGraphs
from thzdaq_gui.models.approvals import ApprovalsModel
from thzdaq_gui.models.assistant import AssistantModel, ProvidersModel
from thzdaq_gui.models.daemon import LOST, DaemonModel
from thzdaq_gui.guide import WindowGuide
from thzdaq_gui.navigator import DockNavigator, Places, QuickFind
from thzdaq_gui.safe_state import SafeStateAction
from thzdaq_gui.runbar import RunBar
from thzdaq_gui.settings import LAYOUT, STATION_PATH, WINDOW_GEOMETRY, location
from thzdaq_gui.settings import settings as app_settings
from thzdaq_gui.update_dialog import Updates
from thzdaq_gui.version import __version__
from thzdaq_gui.wording import NEW_PROFILE, OPEN_PROFILE, STATION_PROFILE
from thzdaq_gui.workers import HangWatch
from thzdaq_gui.workspace_menu import WorkspaceMenu

logger = logging.getLogger(__name__)

DEVICE_HANG_S = 5.0
# 4: one layout, no modes; ADS refuses a layout of another version (the
# default layout is made instead)
STATE_VERSION = 4


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
        self.updates = Updates(self, session.busy)
        self.hub = GraphHub(session.procedures(), session.call, self)
        self.graphs = GraphDocks(session, self.hub, self.docks, self.settings, self)
        self.devices = DeviceDocks(session, self.hub, self.docks)
        self.consoles = ConsoleDocks(session, self.docks, self.open_place)
        self.code = CodeDocks(
            session, self.docks, self, self.start_measurement,
            self.choose_measurement, self.consoles.run,
        )  # fmt: skip
        self.measures = MeasureForms(session, self.hub, self.code.open_custom, self)
        # The chosen measurement is set and run from the bar on top
        self.runBar = RunBar(
            session.procedures(),
            self.measures,
            self.settings,
            self.code.new_measurement,
            self.code.from_example,
        )
        # What the menus, Ctrl+K and Processes show: docks, measurements, consoles
        self.places = Places(self.docks, self.runBar, self.consoles)
        # What agents ask of this window: its state, places shown, highlights
        self.guide = WindowGuide(session, self.places, self.runBar, self.docks, self)

        self.daemon = DaemonModel(session, self)
        self.approvals = ApprovalsModel(session, self)
        self.approvalPrompts = ApprovalPrompts(self.approvals, self)
        self.assistant = AssistantModel(session, ProvidersModel(self), self)
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
        self.docks.sync_bodies()
        self.runBar.show_chosen()
        self.show_daemon()  # the banner as the daemon is, not as a layout saved it
        # A default layout gets its widths once the window has a size
        self._fit_on_show = not restored
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
        open_script = QAction(theme.icon("language-python"), "Open script…", self)
        open_script.triggered.connect(self.code.open_script)
        file.addAction(open_script)
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
        self.menuDevices = bar.addMenu("&Devices")
        self.menuGraphs = bar.addMenu("&Graphs")
        new_graph = QAction(theme.icon("plus"), "New graph…", self)
        new_graph.triggered.connect(self.graphs.new)
        self.menuGraphs.addAction(new_graph)
        self.menuGraphs.addSeparator()
        # Each menu is a search field over the tree of its docks
        self.navigators: Dict[str, DockNavigator] = {}
        for section, menu in (
            ("Devices", self.menuDevices),
            ("Graphs", self.menuGraphs),
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
            self.places.listed,
            self.places.state,
            self.places.show,
            self.places.toggle,
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
        toolbar.addWidget(self.runBar)
        toolbar.addSeparator()
        self.safeState = SafeStateAction(self.session, self)
        safe = QToolButton()
        safe.setDefaultAction(self.safeState)
        safe.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.addWidget(safe)
        toolbar.addSeparator()
        self.quickFind = QuickFind(self.navigator(), self)
        button = QToolButton()
        button.setDefaultAction(self.quickFind.action)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.addWidget(button)

    # Docks
    def add_base_docks(self) -> None:
        self.setupWidget = SetupWidget(self.session)
        self.setupWidget.open_profile_requested.connect(self.open_profile)
        self.setupWidget.new_profile_requested.connect(self.new_profile)
        self.dataWidget = DataWidget(self.session)
        self.logWidget = LogWidget()
        self.processesWidget = ProcessesWidget(self.session.processes)
        self.processesWidget.show_requested.connect(self.places.show)
        self.daemonWidget = DaemonWidget(self.daemon)
        self.assistantWidget = AssistantWidget(self.assistant)
        # Pinned to their side bars: not in the menus, never closed
        for name, title, widget, icon_name, side in (
            (SETUP, "Setup", self.setupWidget, "tune-vertical", QtAds.SideBarLeft),
            (DATA, "Data", self.dataWidget, "database-outline", QtAds.SideBarLeft),
            (LOG, "Log", self.logWidget, "text-box-outline", QtAds.SideBarBottom),
            (
                PROCESSES,
                "Processes",
                self.processesWidget,
                "progress-clock",
                QtAds.SideBarBottom,
            ),
            (DAEMON, "Daemon", self.daemonWidget, "server", QtAds.SideBarBottom),
            (
                EDITOR,
                "Editor",
                self.code.tabs,
                "file-code-outline",
                QtAds.SideBarBottom,
            ),
            (CONSOLE, "Console", self.consoles.tabs, "console", QtAds.SideBarBottom),
            (
                ASSISTANT,
                "Assistant",
                self.assistantWidget,
                "robot-outline",
                QtAds.SideBarRight,
            ),
        ):
            self.docks.add(
                name, title, widget, "", theme.icon(icon_name), auto_hide=side,
                listed=False,
            )  # fmt: skip
        self.processesWidget.count_changed.connect(self.show_process_count)

    def show_process_count(self, count: int) -> None:
        """How many run, on the Processes tab."""
        self.docks.retitle(PROCESSES, f"Processes ({count})" if count else "Processes")

    def on_procedures_changed(self) -> None:
        """The bench's own measurements changed: their forms, the bar and
        the graphs follow."""
        self.measures.sync()
        self.runBar.set_procedures(self.session.procedures())

    def choose_measurement(self, procedure: str) -> None:
        """The bench's own measurement whose script is the current tab of
        Editor is the bar's (once it is listed)."""
        self.runBar.want(procedure)

    def start_measurement(self, procedure: str) -> None:
        """Start a measurement as the bar does, with the values of its form
        (Run in the dock of its script): it is the one chosen from now on."""
        run = self.measures.run(procedure)
        if run is None:
            return
        self.runBar.choose(procedure)
        run.start()

    def open_place(self, file: Path, line: int) -> None:
        """A place of a traceback in a console: its file in Editor."""
        self.code.open_place(file, line)

    def show_dock(self, name: str) -> None:
        """In front of the user, wherever it is."""
        self.docks.show(name)

    def apply_default_layout(self) -> None:
        """Devices on the left, graphs in the centre; the docks it leaves
        closed open floating when first asked for."""
        self.docks.close_kinds(GRAPH, DEVICE)
        self.docks.tab_group(QtAds.CenterDockWidgetArea, self.graphs.default_docks())
        self.docks.tab_group(QtAds.LeftDockWidgetArea, self.devices.default_docks())
        self.docks.unplace_closed()

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
        """After a default layout: the device column as wide as its docks
        want, the graphs the rest; the layout was made before the docks had
        their content."""
        self.docks.fit_columns()

    # State: geometry and the layout
    def restore_state(self) -> bool:
        """The geometry and layout saved; False: no layout (or one ADS refused)."""
        geometry = self.settings.value(WINDOW_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.settings.value(LAYOUT)
        restored = state is not None and bool(
            self.dock_manager.restoreState(state, STATE_VERSION)
        )
        if restored:
            self.docks.restored()
        return restored

    def save_state(self) -> None:
        self.settings.setValue(WINDOW_GEOMETRY, self.saveGeometry())
        self.settings.setValue(LAYOUT, self.dock_manager.saveState(STATE_VERSION))

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
        self.consoles.close()
        self.assistant.close()
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
