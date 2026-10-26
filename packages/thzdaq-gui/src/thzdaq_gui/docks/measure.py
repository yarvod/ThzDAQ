"""Measurement docks: a procedure configured and run from one widget.

Devices are chosen per slot from the station, only those with the needed
capabilities are offered. The same ProcedureBox runs quick scans inside
device docks with the device fixed (I-V of this SIS bias).
"""

import json
from typing import Dict, List, Mapping, Optional, Type

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.errors import ProcedureError
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.procedures.monitor import (
    KEY_SEPARATOR,
    default_quantities,
    monitor_quantities,
    split_entry,
)

from thzdaq_gui import theme
from thzdaq_gui.forms import DeviceSlotsForm, ParameterForm
from thzdaq_gui.settings import settings

# A start or a stop that takes this long is treated as a hung device
STUCK_AFTER_MS = 5000


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
        self.window = None  # seconds of the live curves to show
        self.raised = False
        self.reached: List[str] = []  # graphs that got data before the first step
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
        self.btnStop.clicked.connect(self.stop)
        self.btnAbort = QPushButton(theme.icon("lan-disconnect"), "Abort")
        self.btnAbort.setToolTip(
            "The measurement waits for a device that does not answer: break the "
            "connections of its devices (they reconnect on the next command)"
        )
        self.btnAbort.clicked.connect(self.abort)
        row.addWidget(self.btnStart)
        row.addWidget(self.btnStop)
        row.addWidget(self.btnAbort)
        layout.addLayout(row)
        self.state = QLabel("Idle")
        self.state.setProperty("role", "muted")
        layout.addWidget(self.state)
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
        self.btnAbort.hide()
        self.ui_running = False
        # One timer for "starting" and "stopping": a timer of an earlier run
        # never fires into the next one
        self.stuck = QTimer(self)
        self.stuck.setSingleShot(True)
        self.stuck.setInterval(STUCK_AFTER_MS)
        self.stuck.timeout.connect(self.offer_abort)
        # The thread may end without telling (it should not); the dock checks
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(1000)
        self.watchdog.timeout.connect(self.check_thread)
        self.ended_unseen = 0
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
        self.saved_devices: Dict[str, str] = {}
        raw = settings().value(self.settings_key)
        if not raw:
            return
        try:
            data = json.loads(raw)
            # A parameter dropped in a newer version must not lose the others
            known = self.procedure_class.parameters()
            saved = {k: v for k, v in data.get("parameters", {}).items() if k in known}
            procedure = self.procedure_class.from_json(saved)
            self.form.set_values(procedure.values())
            self.saved_devices = dict(data.get("devices", {}))
        except (ValueError, ProcedureError, TypeError, AttributeError):
            pass

    def remember(self, procedure: Procedure) -> None:
        data = {"parameters": procedure.to_json(), "devices": self.devices.mapping()}
        settings().setValue(self.settings_key, json.dumps(data))
        self.saved_devices = data["devices"]

    # Running
    def start(self) -> None:
        if self.runner.running:
            QMessageBox.warning(
                self,
                "Measurement",
                "It is still running: Stop it, or Abort if it hangs",
            )
            return
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
        self.window = procedure.plot_window()
        self.raised = False
        self.reached = []
        self.log.clear()
        self.state.setText("Connecting to devices...")
        self.stuck.start()
        self.progress.setRange(0, procedure.estimate_steps() or 0)
        self.progress.setValue(0)
        self.runner.start(
            self.session.station,
            self.session.store,
            procedure,
            self.mapping(),
            self.comment.text(),
        )

    def stop(self) -> None:
        self.runner.cancel()
        self.state.setText("Stopping...")
        self.stuck.start()

    def offer_abort(self) -> None:
        """Still waiting after a while: a device probably hangs."""
        if self.ui_running and self.state.text() in (
            "Connecting to devices...",
            "Stopping...",
        ):
            self.state.setText(
                f"{self.state.text()} no answer, Abort breaks the connections"
            )
            self.btnAbort.show()

    def abort(self) -> None:
        self.runner.cancel()
        if self.session.station is not None:
            self.session.station.abort(self.mapping().values())
        self.log.appendPlainText("aborted: connections of the devices were broken")

    def check_thread(self) -> None:
        if not self.ui_running or self.runner.running:
            self.ended_unseen = 0
            return
        # The end signal may still be queued: act only on a second look
        self.ended_unseen += 1
        if self.ended_unseen > 1:
            self.log.appendPlainText("the measurement thread has ended")
            self.on_running(False)

    def on_started(self, measurement) -> None:
        self.measurement = measurement
        self.state.setText("Running")
        self.log.appendPlainText(f"started #{measurement.id}")

    def on_record(self, table: str, record) -> None:
        if self.measurement is None:
            return
        reached = self.hub.feed(
            self.measurement, self.procedure_class.plots, table, record, self.window
        )
        if not self.raised:
            self.reached.extend(t for t in reached if t not in self.reached)

    def raise_graph(self) -> None:
        """One graph comes to the front per run, after its first step: of the
        graphs that got data, the first in the procedure's plots (P-t before
        T-t and V-t), whatever device was read first."""
        if self.raised or not self.reached:
            return
        self.raised = True
        order = [spec.title for spec in self.procedure_class.plots]
        self.hub.raise_graph(min(self.reached, key=order.index))

    def on_progress(self, done: int, total) -> None:
        self.raise_graph()
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)

    def on_failed(self, message: str) -> None:
        self.log.appendPlainText(message)
        QMessageBox.warning(self, self.procedure_class.title, message)

    def on_finished(self, measurement) -> None:
        self.raise_graph()
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
        self.ui_running = running
        self.ended_unseen = 0
        if running:
            self.watchdog.start()
        else:
            self.watchdog.stop()
            self.stuck.stop()
            self.btnAbort.hide()
            self.state.setText("Idle")
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
    """Monitor over time: devices are ticked in a tree, each with the values to read.

    A device expands to its readable values; the measured ones are ticked when
    the device is ticked (power, voltage and current), setpoints can be added.
    """

    def __init__(self, session, hub, procedure_class, parent=None):
        super().__init__(session, hub, procedure_class, parent=parent)
        self.watch = QTreeWidget()
        self.watch.setHeaderHidden(True)
        self.watch.setMinimumHeight(160)
        self.devices_box.setTitle("Devices to watch")
        self.devices_box.layout().addWidget(self.watch)
        self.devices.hide()
        editor = self.form.editors.get("watch")
        if editor is not None:
            self.form.layout_.setRowVisible(editor.widget, False)
        self.refresh_devices()

    def device_items(self):
        return [
            self.watch.topLevelItem(i) for i in range(self.watch.topLevelItemCount())
        ]

    def refresh_devices(self, *_) -> None:
        if not hasattr(self, "watch"):
            return
        station = self.session.station
        entries = self.entries() or [
            e for e in self.saved_devices.get("watch", "").split(",") if e
        ]
        chosen: Dict[str, set] = {}
        for entry in entries:
            ref, key = split_entry(entry)
            chosen.setdefault(ref, set())
            if key:
                chosen[ref].add(key)
        self.watch.clear()
        if station is None:
            return
        for info in station.devices():
            quantities = monitor_quantities(station.quantities(info.ref))
            if not quantities:
                continue
            item = QTreeWidgetItem([info.title])
            item.setIcon(0, theme.device_icon(info.kind, info.instrument))
            item.setData(0, Qt.UserRole, info.ref)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            keys = chosen.get(info.ref)
            if keys is not None and not keys:  # the device without a choice
                keys = {q.key for q in default_quantities(quantities)}
            for quantity in quantities:
                child = QTreeWidgetItem([quantity.label])
                child.setData(0, Qt.UserRole, quantity.key)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                ticked = keys is not None and quantity.key in keys
                child.setCheckState(0, Qt.Checked if ticked else Qt.Unchecked)
                item.addChild(child)
            self.watch.addTopLevelItem(item)
        self.devices_box.setVisible(True)

    def set_device(self, ref: str, checked: bool) -> None:
        """Tick a device with its measured values (or untick all of it)."""
        for item in self.device_items():
            if item.data(0, Qt.UserRole) != ref:
                continue
            quantities = [
                item.child(i).data(0, Qt.UserRole) for i in range(item.childCount())
            ]
            station = self.session.station
            defaults = {
                q.key
                for q in default_quantities(monitor_quantities(station.quantities(ref)))
            }
            for i, key in enumerate(quantities):
                on = checked and key in defaults
                item.child(i).setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def entries(self):
        """ref/key of every ticked value."""
        if not hasattr(self, "watch"):
            return []
        found = []
        for item in self.device_items():
            ref = item.data(0, Qt.UserRole)
            for i in range(item.childCount()):
                child = item.child(i)
                if child.checkState(0) == Qt.Checked:
                    found.append(f"{ref}{KEY_SEPARATOR}{child.data(0, Qt.UserRole)}")
        return found

    def checked(self):
        refs = []
        for entry in self.entries():
            ref, _ = split_entry(entry)
            if ref not in refs:
                refs.append(ref)
        return refs

    def mapping(self) -> Dict[str, str]:
        return {ref: ref for ref in self.checked()}

    def start(self) -> None:
        entries = self.entries()
        if not entries:
            QMessageBox.warning(self, "Monitor", "Tick the values to watch")
            return
        self.form.editors["watch"].set(tuple(entries))
        self.devices.combos.clear()
        super().start()

    def remember(self, procedure) -> None:
        super().remember(procedure)
        self.saved_devices = {"watch": ",".join(self.entries())}
        data = {"parameters": procedure.to_json(), "devices": self.saved_devices}
        settings().setValue(self.settings_key, json.dumps(data))


class MonitorWidget(MeasureWidget):
    def make_box(self, session, hub, procedure_class):
        return MonitorBox(session, hub, procedure_class)


# Docks with their own widget class by procedure name
SPECIAL = {"monitor.time": MonitorWidget}


def measure_widget(session, hub, procedure_class) -> MeasureWidget:
    cls = SPECIAL.get(procedure_class.name, MeasureWidget)
    return cls(session, hub, procedure_class)
