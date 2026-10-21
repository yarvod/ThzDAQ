from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QMessageBox
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.registry import get_procedure

from thzdaq_gui.panels.control_panel import ControlPanel
from thzdaq_gui.panels.data_panel import DataPanel
from thzdaq_gui.panels.measure_panel import MeasurePanel
from thzdaq_gui.panels.monitor_panel import MonitorPanel
from thzdaq_gui.panels.sis_panel import SisPanel
from thzdaq_gui.panels.station_panel import StationPanel
from thzdaq_gui.plots import PlotPanel

SETTINGS = ("ThzDAQ", "thzdaq-gui")
LAYOUT_VERSION = 2


class MainWindow(QMainWindow):
    def __init__(self, session, parent=None, restore_layout: bool = True):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("ThzDAQ")
        self.resize(1400, 850)

        self.plots = PlotPanel()
        self.setCentralWidget(self.plots)

        self.stationPanel = StationPanel(session)
        self.measurePanel = MeasurePanel(session)
        self.dataPanel = DataPanel(session)
        self.controlPanel = ControlPanel(session)
        self.sisPanel = SisPanel(session)
        self.monitorPanel = MonitorPanel(session)
        self.docks = {}
        for name, title, widget, area in (
            ("station", "Station", self.stationPanel, Qt.LeftDockWidgetArea),
            ("measure", "Measurement", self.measurePanel, Qt.LeftDockWidgetArea),
            ("control", "Manual control", self.controlPanel, Qt.RightDockWidgetArea),
            ("sis", "SIS tools", self.sisPanel, Qt.RightDockWidgetArea),
            ("monitor", "Monitor", self.monitorPanel, Qt.RightDockWidgetArea),
            ("data", "Data", self.dataPanel, Qt.BottomDockWidgetArea),
        ):
            dock = QDockWidget(title, self)
            dock.setObjectName(f"dock_{name}")
            dock.setWidget(widget)
            self.addDockWidget(area, dock)
            self.docks[name] = dock
        self.tabifyDockWidget(self.docks["station"], self.docks["measure"])
        self.tabifyDockWidget(self.docks["control"], self.docks["sis"])
        self.tabifyDockWidget(self.docks["control"], self.docks["monitor"])
        self.docks["measure"].raise_()
        self.docks["control"].raise_()

        self.stationLabel = QLabel()
        self.statusBar().addPermanentWidget(self.stationLabel)
        self.build_menu()

        self.measurePanel.run_started.connect(self.on_run_started)
        session.runner.record.connect(self.plots.add_record)
        session.worker.error.connect(
            lambda message: self.statusBar().showMessage(message, 10000)
        )
        session.station_changed.connect(self.show_station)
        self.dataPanel.dataset_opened.connect(self.show_dataset)
        self.show_station(session.station)
        if restore_layout:
            self.restore_layout()

    def build_menu(self) -> None:
        file = self.menuBar().addMenu("&File")
        open_action = QAction("Open station…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.stationPanel.open_profile)
        file.addAction(open_action)
        reload_action = QAction("Reload station", self)
        reload_action.triggered.connect(lambda: self.session.reload())
        file.addAction(reload_action)
        file.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file.addAction(quit_action)

        view = self.menuBar().addMenu("&View")
        for dock in self.docks.values():
            view.addAction(dock.toggleViewAction())

    def show_station(self, station) -> None:
        if station is None:
            self.stationLabel.setText("No station")
            return
        mode = "  SIMULATION" if self.session.simulate else ""
        self.stationLabel.setText(f"Station: {station.name}{mode}")

    def on_run_started(self, procedure) -> None:
        self.plots.set_specs(procedure.plots)

    def show_dataset(self, dataset) -> None:
        try:
            specs = get_procedure(dataset.procedure).plots
        except ProcedureError:
            specs = ()
        self.plots.show_dataset(dataset, specs)
        self.statusBar().showMessage(
            f"{dataset.procedure} {dataset.started} {dataset.status}"
        )

    # Layout
    def restore_layout(self) -> None:
        settings = QSettings(*SETTINGS)
        geometry = settings.value("geometry")
        state = settings.value("state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state, LAYOUT_VERSION)

    def save_layout(self) -> None:
        settings = QSettings(*SETTINGS)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("state", self.saveState(LAYOUT_VERSION))

    def closeEvent(self, event) -> None:
        if self.session.runner.running:
            answer = QMessageBox.question(
                self, "Measurement running", "Stop the measurement and quit?"
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.controlPanel.timer.stop()
        self.save_layout()
        self.session.shutdown()
        event.accept()
