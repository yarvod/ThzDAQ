"""Measurement docks: a procedure configured and run from one widget.

Devices are chosen per slot from the station, only those with the needed
capabilities are offered. The same ProcedureBox runs quick scans inside
device docks with the device fixed (I-V of this SIS bias). In a dock only the
devices and parameters scroll: comment, Start/Stop, state and progress stay
at the bottom, so they never scroll out of sight.
"""

import json
from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Type

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.errors import ProcedureError, StationError
from thzdaq_core.measurements.procedure import Procedure
from thzdaq_core.measurements.procedures.monitor import (
    KEY_SEPARATOR,
    default_quantities,
    monitor_quantities,
    split_entry,
)
from thzdaq_instruments import InstrumentError

from thzdaq_gui import theme
from thzdaq_gui.collapsible import Collapsible
from thzdaq_gui.forms import DeviceSlotsForm, ParameterForm
from thzdaq_gui.run_controls import (
    CONNECTING,
    IDLE,
    RUNNING,
    STOPPING,
    RunControls,
    RunStatus,
)
from thzdaq_gui.settings import settings

# A start or a stop that takes this long is treated as a hung device
STUCK_AFTER_MS = 5000


class ProcedureBox(QWidget):
    """Parameters, devices, Start/Stop and progress of one procedure.

    compact (a scan inside a device dock): one column, the dock scrolls it.
    Otherwise the devices and parameters (under the header) scroll and the
    controls are pinned below them. How the run goes is a RunStatus; the
    controls in the footer, and the bar on top in Lite, show it.
    """

    status_changed = Signal(str)  # its line: "Running 42 %", "completed #12"
    comment_changed = Signal(str)

    def __init__(
        self,
        session,
        hub,
        procedure_class: Type[Procedure],
        fixed: Optional[Mapping[str, str]] = None,
        compact: bool = False,
        header: Optional[QWidget] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.procedure_class = procedure_class
        self.fixed = dict(fixed or {})
        self.compact = compact
        self.process = None  # in the session's Processes while running
        self.reveal = None  # shows this box once its dock is in front (a folded scan)
        self.runner = session.runner()
        self.measurement = None
        self.window = None  # seconds of the live curves to show
        self.raised = False
        self.reached: List[str] = []  # graphs that got data before the first step
        self.expected: List[str] = []  # graphs put on screen at Start
        self.run_status = RunStatus()
        self.comment = ""  # of the next run
        self.settings_key = f"procedures/{procedure_class.name}"
        # Folded sections are remembered apart for scans in device docks
        sections = f"{'scan/' if compact else ''}{procedure_class.name}"
        self.devices_box = Collapsible("Devices", f"{sections}/devices")
        self.devices = DeviceSlotsForm()
        self.devices.changed.connect(self.show_devices_summary)
        self.devices_box.addWidget(self.devices)
        self.parameters_box = Collapsible("Parameters", f"{sections}/parameters")
        self.form = ParameterForm()
        self.form.set_procedure(procedure_class)
        self.parameters_box.addWidget(self.form)
        setup = QWidget()
        setup_layout = QVBoxLayout(setup)
        if header is not None:
            setup_layout.addWidget(header)
        setup_layout.addWidget(self.devices_box)
        setup_layout.addWidget(self.parameters_box)
        self.footer = QFrame()
        self.footer.setObjectName("procedureFooter")
        footer = QVBoxLayout(self.footer)
        # Hidden in Lite: the bar on top shows the chosen run
        self.controls = RunControls()
        self.controls.bind(self)
        footer.addWidget(self.controls)
        # Folded, the log shows its last line
        self.log_box = Collapsible("Log", f"{sections}/log", expanded=False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMaximumHeight(70 if compact else 110)
        self.log_box.addWidget(self.log)
        footer.addWidget(self.log_box)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if compact:
            setup_layout.setContentsMargins(0, 0, 0, 0)
            footer.setContentsMargins(0, 6, 0, 0)
            layout.addWidget(setup)
            layout.addWidget(self.footer)
        else:
            setup_layout.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(setup)
            self.scroll = scroll
            self.footer.setStyleSheet(
                f"#procedureFooter {{ border-top: 1px solid {theme.BORDER}; }}"
            )
            footer.setContentsMargins(9, 6, 9, 9)
            layout.addWidget(scroll, 1)
            layout.addWidget(self.footer)
        self.runner.started.connect(self.on_started)
        self.runner.record.connect(self.on_record)
        self.runner.progress.connect(self.on_progress)
        self.runner.log.connect(self.note)
        self.runner.failed.connect(self.on_failed)
        self.runner.finished.connect(self.on_finished)
        self.runner.running_changed.connect(self.on_running)
        self.status_changed.connect(self.show_process_status)
        # A device dock rebuilt during a scan: no process left behind
        self.destroyed.connect(lambda: session.processes.finish(self.process))
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
        self.show_devices_summary()

    def devices_summary(self) -> str:
        return self.devices.summary()

    def show_devices_summary(self, *_) -> None:
        self.devices_box.set_summary(self.devices_summary())

    def mapping(self) -> Dict[str, str]:
        return {**self.devices.mapping(), **self.fixed}

    def slot_quantities(self, slot: str):
        """What the device chosen for a slot reads (a monitor's graphs by unit)."""
        ref = self.mapping().get(slot)
        try:
            return self.session.station.quantities(ref) if ref else []
        except (StationError, InstrumentError):
            return []

    # Status for the folded log and for whoever shows this run elsewhere
    def note(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log_box.set_summary(text.splitlines()[-1] if text else "")

    def process_title(self) -> str:
        title = self.procedure_class.title or self.procedure_class.name
        if self.compact and self.fixed and self.session.station is not None:
            ref = next(iter(self.fixed.values()))
            return f"{title} · {self.session.station.title(ref)}"
        return title

    def dock_name(self) -> str:
        """The dock that shows this box: a scan is in its device's dock."""
        if self.compact and self.fixed:
            return f"device:{next(iter(self.fixed.values()))}"
        return f"measure:{self.procedure_class.name}"

    def show_process_status(self, text: str) -> None:
        if self.process is not None:
            self.process.update(status=text or self.run_status.state)

    # The run, as RunControls see it
    def status(self) -> RunStatus:
        return self.run_status

    def update_status(self, **changes) -> None:
        self.run_status = replace(self.run_status, **changes)
        self.status_changed.emit(self.run_status.line())

    def set_comment(self, text: str) -> None:
        if text != self.comment:
            self.comment = text
            self.comment_changed.emit(text)

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
            self.devices_box.set_expanded(True)
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
        self.expected = [p.title for p in procedure.active_plots(self.slot_quantities)]
        self.hub.show_run(self.expected)
        self.log.clear()
        self.log_box.set_summary("")
        self.update_status(
            state=CONNECTING, done=0, total=procedure.estimate_steps() or None
        )
        self.stuck.start()
        self.runner.start(
            self.session.station,
            self.session.store,
            procedure,
            self.mapping(),
            self.comment,
        )

    def stop(self) -> None:
        self.runner.cancel()
        self.update_status(state=STOPPING)
        self.stuck.start()

    def offer_abort(self) -> None:
        """Still waiting after a while: a device probably hangs."""
        status = self.run_status
        if status.running and status.state in (CONNECTING, STOPPING):
            self.update_status(
                state=f"{status.state} no answer, Abort breaks the connections",
                can_abort=True,
            )
            if self.process is not None:
                self.process.update(can_abort=True)

    def abort(self) -> None:
        self.runner.cancel()
        if self.session.station is not None:
            self.session.station.abort(self.mapping().values())
        self.note("aborted: connections of the devices were broken")

    def check_thread(self) -> None:
        if not self.run_status.running or self.runner.running:
            self.ended_unseen = 0
            return
        # The end signal may still be queued: act only on a second look
        self.ended_unseen += 1
        if self.ended_unseen > 1:
            self.note("the measurement thread has ended")
            self.on_running(False)

    def on_started(self, measurement) -> None:
        self.measurement = measurement
        self.update_status(state=RUNNING)
        self.note(f"started #{measurement.id}")

    def on_record(self, table: str, record) -> None:
        if self.measurement is None:
            return
        reached = self.hub.feed(
            self.measurement, self.procedure_class.plots, table, record, self.window
        )
        if not self.raised:
            self.reached.extend(t for t in reached if t not in self.reached)

    def raise_graph(self) -> None:
        """After the first step: graphs that got data without being expected
        at Start join the graphs of the run."""
        if self.raised or not self.reached:
            return
        self.raised = True
        extra = [title for title in self.reached if title not in self.expected]
        if extra:
            self.hub.show_run(self.expected + extra)

    def on_progress(self, done: int, total) -> None:
        self.raise_graph()
        if self.process is not None:
            self.process.update(progress=(done, total) if total else None)
        self.update_status(done=done, total=total or None)

    def on_failed(self, message: str) -> None:
        self.note(message)
        self.update_status(outcome="failed to start")
        QMessageBox.warning(self, self.procedure_class.title, message)

    def on_finished(self, measurement) -> None:
        self.raise_graph()
        text = f"{measurement.status}"
        if measurement.error:
            text += f": {measurement.error}"
        if measurement.metadata.get("path"):
            text += f"\nsaved {measurement.metadata['path']}"
        self.note(text)
        ended = {"outcome": f"{measurement.status} #{measurement.id}"}
        if self.run_status.total is None:  # a busy bar: full at the end
            ended.update(done=1, total=1)
        self.update_status(**ended)

    def on_running(self, running: bool) -> None:
        self.ended_unseen = 0
        if running and self.process is None:
            self.process = self.session.processes.start(
                self.process_title(),
                theme.procedure_icon_name(self.procedure_class.name),
                self.dock_name(),
                stop=self.stop,
                abort=self.abort,
                reveal=lambda: self.reveal() if self.reveal is not None else None,
            )
        elif not running:
            self.session.processes.finish(self.process)
            self.process = None
        if running:
            self.watchdog.start()
        else:
            self.watchdog.stop()
            self.stuck.stop()
        # Folding stays possible while running: only the fields are locked
        self.parameters_box.body.setEnabled(not running)
        self.devices_box.body.setEnabled(not running)
        if running:
            self.update_status(running=True)
        else:
            self.update_status(running=False, state=IDLE, can_abort=False)


class MeasureWidget(QWidget):
    """Dock content: the procedure box with title and description on top."""

    def __init__(self, session, hub, procedure_class: Type[Procedure], parent=None):
        super().__init__(parent)
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(procedure_class.title or procedure_class.name)
        title.setProperty("role", "title")
        header_layout.addWidget(title)
        if procedure_class.description:
            text = QLabel(procedure_class.description)
            text.setWordWrap(True)
            text.setProperty("role", "muted")
            header_layout.addWidget(text)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.box = self.make_box(session, hub, procedure_class, header)
        layout.addWidget(self.box)

    def make_box(self, session, hub, procedure_class, header):
        return ProcedureBox(session, hub, procedure_class, header=header)

    def show_controls(self, on: bool) -> None:
        """Off in Lite: the bar on top runs the chosen measurement."""
        self.box.controls.setVisible(on)


class MonitorBox(ProcedureBox):
    """Monitor over time: devices are ticked in a tree, each with the values to read.

    A device expands to its readable values; the measured ones are ticked when
    the device is ticked (power, voltage and current), setpoints can be added.
    """

    def __init__(self, session, hub, procedure_class, header=None, parent=None):
        super().__init__(session, hub, procedure_class, header=header, parent=parent)
        self.watch = QTreeWidget()
        self.watch.setHeaderHidden(True)
        self.watch.setMinimumHeight(160)
        self.watch.itemChanged.connect(self.show_devices_summary)
        self.devices_box.setTitle("Devices to watch")
        self.devices_box.addWidget(self.watch)
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
        self.show_devices_summary()

    def devices_summary(self) -> str:
        if not hasattr(self, "watch"):
            return ""
        values = len(self.entries())
        titles = [
            item.text(0)
            for item in self.device_items()
            if item.data(0, Qt.UserRole) in self.checked()
        ]
        return f"{values} values: {', '.join(titles)}" if values else "nothing ticked"

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
    def make_box(self, session, hub, procedure_class, header):
        return MonitorBox(session, hub, procedure_class, header=header)


# Docks with their own widget class by procedure name
SPECIAL = {"monitor.time": MonitorWidget}


def measure_widget(session, hub, procedure_class) -> MeasureWidget:
    cls = SPECIAL.get(procedure_class.name, MeasureWidget)
    return cls(session, hub, procedure_class)
