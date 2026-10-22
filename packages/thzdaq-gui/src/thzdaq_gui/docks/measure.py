"""Measurement docks: a procedure configured and run from one widget.

Devices are chosen per slot from the station, only those with the needed
capabilities are offered. The same ProcedureBox runs quick scans inside
device docks with the device fixed (I-V of this SIS bias).
"""

import json
from typing import Dict, Mapping, Optional, Type

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.procedure import Procedure

from thzdaq_gui import theme
from thzdaq_gui.forms import DeviceSlotsForm, ParameterForm
from thzdaq_gui.prefs import prefs



class ProcedureBox(QWidget):
    """Parameters, devices, Start/Stop and progress of one procedure."""

    def __init__(
        self,
        session,
        hub,
        procedure_class: Type[Procedure],
        fixed: Optional[Mapping[str, str]] = None,
        compact: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.procedure_class = procedure_class
        self.fixed = dict(fixed or {})
        self.runner = session.runner()
        self.measurement = None
        self.settings_key = f"procedures/{procedure_class.name}"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.devices_box = QGroupBox("Devices")
        self.devices = DeviceSlotsForm()
        QVBoxLayout(self.devices_box).addWidget(self.devices)
        self.parameters_box = QGroupBox("Parameters")
        self.form = ParameterForm()
        self.form.set_procedure(procedure_class)
        QVBoxLayout(self.parameters_box).addWidget(self.form)
        layout.addWidget(self.devices_box)
        layout.addWidget(self.parameters_box)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Comment")
        layout.addWidget(self.comment)
        row = QHBoxLayout()
        self.btnStart = QPushButton(theme.icon("play", "#111111"), "Start")
        self.btnStart.setProperty("accent", True)
        self.btnStart.clicked.connect(self.start)
        self.btnStop = QPushButton(theme.icon("stop"), "Stop")
        self.btnStop.setEnabled(False)
        self.btnStop.clicked.connect(self.runner.cancel)
        row.addWidget(self.btnStart)
        row.addWidget(self.btnStop)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMaximumHeight(70 if compact else 110)
        layout.addWidget(self.log)
        self.runner.started.connect(self.on_started)
        self.runner.record.connect(self.on_record)
        self.runner.progress.connect(self.on_progress)
        self.runner.log.connect(self.log.appendPlainText)
        self.runner.failed.connect(self.on_failed)
        self.runner.finished.connect(self.on_finished)
        self.runner.running_changed.connect(self.on_running)
        session.station_changed.connect(self.refresh_devices)
        session.config_changed.connect(self.refresh_devices)
        self.form.changed.connect(self.refresh_devices)
        self.restore()
        self.refresh_devices()

    # Devices
    def slots(self) -> Dict[str, object]:
        """Slots for the parameters in the form (a hot/cold P-V also needs a load)."""
        try:
            slots = self.procedure_class(**self.form.values()).slots()
        except ProcedureError:
            slots = dict(self.procedure_class.requires)
        return {s: c for s, c in slots.items() if s not in self.fixed}

    def refresh_devices(self, *_) -> None:
        slots = self.slots()
        self.devices.set_slots(
            slots,
            self.session.station,
            self.procedure_class.slot_title,
            self.saved_devices,
            self.procedure_class.slot_kinds,
        )
        self.devices_box.setVisible(bool(slots))

    def mapping(self) -> Dict[str, str]:
        return {**self.devices.mapping(), **self.fixed}

    # Persistence of the last values
    def restore(self) -> None:
        settings = prefs()
        self.saved_devices: Dict[str, str] = {}
        raw = settings.value(self.settings_key)
        if not raw:
            return
        try:
            data = json.loads(raw)
            procedure = self.procedure_class.from_json(data.get("parameters", {}))
            self.form.set_values(procedure.values())
            self.saved_devices = dict(data.get("devices", {}))
        except (ValueError, ProcedureError, TypeError, AttributeError):
            pass

    def remember(self, procedure: Procedure) -> None:
        data = {"parameters": procedure.to_json(), "devices": self.devices.mapping()}
        prefs().setValue(self.settings_key, json.dumps(data))
        self.saved_devices = data["devices"]

    # Running
    def start(self) -> None:
        if self.session.station is None:
            QMessageBox.warning(self, "Measurement", "Open a station profile first")
            return
        missing = self.devices.unmapped()
        if missing:
            titles = ", ".join(self.procedure_class.slot_title(s) for s in missing)
            QMessageBox.warning(self, "Measurement", f"Choose devices for: {titles}")
            return
        try:
            procedure = self.form.procedure()
        except ProcedureError as e:
            QMessageBox.warning(self, "Invalid parameters", str(e))
            return
        self.remember(procedure)
        self.log.clear()
        self.progress.setRange(0, procedure.estimate_steps() or 0)
        self.progress.setValue(0)
        self.runner.start(
            self.session.station,
            self.session.store,
            procedure,
            self.mapping(),
            self.comment.text(),
        )

    def on_started(self, measurement) -> None:
        self.measurement = measurement
        self.log.appendPlainText(f"started {measurement.id}")
        for spec in self.procedure_class.plots:
            self.hub.raise_graph(spec.title)

    def on_record(self, table: str, record) -> None:
        if self.measurement is not None:
            self.hub.feed(self.measurement, self.procedure_class.plots, table, record)

    def on_progress(self, done: int, total) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)

    def on_failed(self, message: str) -> None:
        self.log.appendPlainText(message)
        QMessageBox.warning(self, self.procedure_class.title, message)

    def on_finished(self, measurement) -> None:
        text = f"{measurement.status}"
        if measurement.error:
            text += f": {measurement.error}"
        if measurement.metadata.get("path"):
            text += f"\nsaved {measurement.metadata['path']}"
        self.log.appendPlainText(text)
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)

    def on_running(self, running: bool) -> None:
        self.btnStart.setEnabled(not running)
        self.btnStop.setEnabled(running)
        self.parameters_box.setEnabled(not running)
        self.devices_box.setEnabled(not running)


class MeasureWidget(QScrollArea):
    """Dock content: title, description and the procedure box."""

    def __init__(self, session, hub, procedure_class: Type[Procedure], parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        title = QLabel(procedure_class.title or procedure_class.name)
        title.setProperty("role", "title")
        layout.addWidget(title)
        if procedure_class.description:
            text = QLabel(procedure_class.description)
            text.setWordWrap(True)
            text.setProperty("role", "muted")
            layout.addWidget(text)
        self.box = self.make_box(session, hub, procedure_class)
        layout.addWidget(self.box)
        layout.addStretch()
        self.setWidget(inner)

    def make_box(self, session, hub, procedure_class):
        return ProcedureBox(session, hub, procedure_class)


class MonitorBox(ProcedureBox):
    """Monitor over time: devices are ticked in a list instead of slot combos."""

    def __init__(self, session, hub, procedure_class, parent=None):
        super().__init__(session, hub, procedure_class, parent=parent)
        self.watch = QListWidget()
        self.devices_box.setTitle("Devices to watch")
        self.devices_box.layout().addWidget(self.watch)
        self.devices.hide()
        editor = self.form.editors.get("watch")
        if editor is not None:
            self.form.layout_.setRowVisible(editor.widget, False)
        self.refresh_devices()

    def refresh_devices(self, *_) -> None:
        if not hasattr(self, "watch"):
            return
        station = self.session.station
        checked = set(self.checked()) or set(self.saved_devices.get("watch", "").split(","))
        self.watch.clear()
        if station is None:
            return
        for info in station.devices():
            if not station.quantities(info.ref):
                continue
            item = QListWidgetItem(theme.device_icon(info.kind, info.instrument), info.title)
            item.setData(Qt.UserRole, info.ref)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if info.ref in checked else Qt.Unchecked)
            self.watch.addItem(item)
        self.devices_box.setVisible(True)

    def checked(self):
        return [
            self.watch.item(i).data(Qt.UserRole)
            for i in range(self.watch.count())
            if self.watch.item(i).checkState() == Qt.Checked
        ]

    def mapping(self) -> Dict[str, str]:
        return {ref: ref for ref in self.checked()}

    def start(self) -> None:
        refs = self.checked()
        if not refs:
            QMessageBox.warning(self, "Monitor", "Tick the devices to watch")
            return
        self.form.editors["watch"].set(tuple(refs))
        self.devices.combos.clear()
        super().start()

    def remember(self, procedure) -> None:
        super().remember(procedure)
        self.saved_devices = {"watch": ",".join(self.checked())}
        data = {"parameters": procedure.to_json(), "devices": self.saved_devices}
        prefs().setValue(self.settings_key, json.dumps(data))


class MonitorWidget(MeasureWidget):
    def make_box(self, session, hub, procedure_class):
        return MonitorBox(session, hub, procedure_class)


# Docks with their own widget class by procedure name
SPECIAL = {"monitor.time": MonitorWidget}


def measure_widget(session, hub, procedure_class) -> MeasureWidget:
    cls = SPECIAL.get(procedure_class.name, MeasureWidget)
    return cls(session, hub, procedure_class)

