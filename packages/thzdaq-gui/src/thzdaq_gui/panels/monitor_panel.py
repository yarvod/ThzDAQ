"""Readings over time (P-t, T-t, bias, vacuum) with its own runner.

It runs the monitor.time procedure, so it can go on while a measurement runs
and, when recording, its data land in the data folder like any dataset.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.measurements.procedures import Monitor

from thzdaq_gui.plots import PlotPanel
from thzdaq_gui.workers import QtRunner


class MonitorPanel(QWidget):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.runner = QtRunner(self)
        session.extra_runners.append(self.runner)

        settings = QWidget()
        form = QFormLayout(settings)
        self.roles = QListWidget()
        self.roles.setMaximumHeight(140)
        form.addRow("Roles", self.roles)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.05, 3600)
        self.interval.setValue(1.0)
        self.interval.setSuffix(" s")
        form.addRow("Interval", self.interval)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0, 7 * 24 * 3600)
        self.duration.setSpecialValueText("until stopped")
        self.duration.setSuffix(" s")
        form.addRow("Duration", self.duration)
        self.record = QCheckBox("Save to the data folder")
        form.addRow(self.record)
        row = QHBoxLayout()
        self.btnStart = QPushButton("Start")
        self.btnStart.clicked.connect(self.start)
        self.btnStop = QPushButton("Stop")
        self.btnStop.clicked.connect(self.runner.cancel)
        self.btnStop.setEnabled(False)
        row.addWidget(self.btnStart)
        row.addWidget(self.btnStop)
        form.addRow(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        form.addRow(self.status)

        self.plots = PlotPanel()
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(settings)
        splitter.addWidget(self.plots)
        splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.runner.record.connect(self.plots.add_record)
        self.runner.running_changed.connect(self.on_running)
        self.runner.failed.connect(lambda message: self.status.setText(f"✖ {message}"))
        self.runner.finished.connect(self.on_finished)
        session.station_changed.connect(self.show_station)
        self.show_station(session.station)

    def show_station(self, station) -> None:
        checked = set(self.selected())
        self.roles.clear()
        if station is None:
            return
        for role in station.config.roles:
            item = QListWidgetItem(role)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if role in checked else Qt.Unchecked)
            self.roles.addItem(item)

    def selected(self):
        return [
            self.roles.item(i).text()
            for i in range(self.roles.count())
            if self.roles.item(i).checkState() == Qt.Checked
        ]

    def start(self) -> None:
        roles = self.selected()
        if self.session.station is None or not roles:
            QMessageBox.information(self, "Monitor", "Tick the roles to monitor")
            return
        procedure = Monitor(
            watch=roles, interval=self.interval.value(), duration=self.duration.value()
        )
        self.plots.set_specs(procedure.plots)
        store = self.session.store if self.record.isChecked() else None
        self.status.setText(f"Monitoring {', '.join(roles)}")
        self.runner.start(self.session.station, store, procedure, comment="monitor")

    def on_running(self, running: bool) -> None:
        self.btnStart.setEnabled(not running)
        self.btnStop.setEnabled(running)
        self.roles.setEnabled(not running)

    def on_finished(self, dataset) -> None:
        text = f"■ {dataset.status}"
        if dataset.error:
            text += f": {dataset.error}"
        if dataset.metadata.get("path"):
            text += f" — saved {dataset.metadata['path']}"
        self.status.setText(text)
