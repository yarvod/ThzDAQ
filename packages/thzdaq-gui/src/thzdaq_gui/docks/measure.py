"""Measurement docks: a procedure configured and run from one widget.

What a procedure takes and needs is its description by the lab
(describe_procedure). Devices are chosen per slot from the bench, only those
with the needed capabilities are offered. The same ProcedureBox runs quick
scans inside device docks with the device fixed (I-V of this SIS bias). In a
dock only the devices and parameters scroll: comment, Start/Stop, state and
progress stay at the bottom, so they never scroll out of sight.
"""

import json
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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
from thzdaq_api.devices import DeviceInfo, QuantityInfo
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import DescribeProcedure, ProcedureInfo
from thzdaq_api.procedures import (
    KEY_SEPARATOR,
    MONITOR_TIME,
    default_quantities,
    monitor_quantities,
    split_entry,
)

from thzdaq_gui import procedure_groups, theme
from thzdaq_gui.collapsible import Collapsible
from thzdaq_gui.dock_names import DEVICE, MEASURE, dock_name
from thzdaq_gui.forms import DeviceSlotsForm, ParameterForm
from thzdaq_gui.run_controls import (
    CONNECTING,
    IDLE,
    RUNNING,
    STOPPING,
    RunControls,
    RunStatus,
)
from thzdaq_gui.settings import procedure_key, sections_path, settings
from thzdaq_gui.wording import INVALID_PARAMETERS

# A start or a stop that takes this long is treated as a hung device
STUCK_AFTER_MS = 5000
CHECK = "Check"


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
        procedure: str,
        fixed: Optional[Mapping[str, str]] = None,
        compact: bool = False,
        header: Optional[QWidget] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.procedure = procedure  # its name
        # Records of a run go to every plot the procedure may fill
        self.plots = session.procedure(procedure).plots
        # As the parameters in the form describe it: their slots
        self.info: ProcedureInfo = session.call(DescribeProcedure(procedure=procedure))
        self.fixed = dict(fixed or {})
        self.compact = compact
        self.process = None  # in the session's Processes while running
        self.reveal = None  # shows this box once its dock is in front (a folded scan)
        self.runner = session.run_model()
        self.measurement = None
        self.window = None  # seconds of the live curves to show
        self.raised = False
        self.reached: List[str] = []  # graphs that got data before the first step
        self.expected: List[str] = []  # graphs put on screen at Start
        self.run_status = RunStatus()
        self.comment = ""  # of the next run
        self.settings_key = procedure_key(procedure)
        # Folded sections are remembered apart for scans in device docks
        sections = sections_path(procedure, scan=compact)
        self.devices_box = Collapsible("Devices", f"{sections}/devices")
        self.devices = self.make_devices()
        self.devices.changed.connect(self.show_devices_summary)
        self.devices_box.addWidget(self.devices)
        self.parameters_box = Collapsible("Parameters", f"{sections}/parameters")
        self.form = ParameterForm()
        self.form.set_parameters(self.info.parameters)
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
        self.runner.conflict.connect(self.on_conflict)
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
    def make_devices(self) -> DeviceSlotsForm:
        return DeviceSlotsForm()

    def refresh_devices(self, *_) -> None:
        """Slots of the parameters in the form (a hot/cold P-V also needs a
        load); while some are invalid, those of the last valid ones."""
        try:
            parameters = self.form.values()
            self.info = self.session.call(
                DescribeProcedure(procedure=self.procedure, parameters=parameters)
            )
        except ValueError:
            pass  # typed text that is not numbers
        except LabError as e:
            if e.code != ErrorCode.INVALID_ARGUMENTS:
                raise
        slots = [slot for slot in self.info.slots if slot.name not in self.fixed]
        self.devices.set_slots(slots, self.session.devices(), self.saved_devices)
        self.devices_box.setVisible(bool(slots))
        self.show_devices_summary()

    def show_devices_summary(self, *_) -> None:
        self.devices_box.set_summary(self.devices.summary())

    def mapping(self) -> Dict[str, str]:
        return {**self.devices.mapping(), **self.fixed}

    def devices_problem(self) -> Optional[str]:
        """Why the devices chosen cannot run it; None when they can."""
        missing = self.devices.unmapped()
        if missing:
            return f"Choose devices for: {', '.join(slot.title for slot in missing)}"
        return None

    def chosen_devices(self) -> Dict[str, str]:
        """The choice of devices as it is remembered for the next start."""
        return self.devices.mapping()

    # Status for the folded log and for whoever shows this run elsewhere
    def note(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log_box.set_summary(text.splitlines()[-1] if text else "")

    def process_title(self) -> str:
        title = self.info.title or self.procedure
        if self.compact and self.fixed:
            ref = next(iter(self.fixed.values()))
            return f"{title} · {self.session.title_of(ref)}"
        return title

    def dock_name(self) -> str:
        """The dock that shows this box: a scan is in its device's dock."""
        if self.compact and self.fixed:
            return dock_name(DEVICE, next(iter(self.fixed.values())))
        return dock_name(MEASURE, self.procedure)

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
            saved = data.get("parameters", {})
            self.form.set_values(
                {k: v for k, v in saved.items() if k in self.form.editors}
            )
            self.saved_devices = dict(data.get("devices", {}))
        except (ValueError, TypeError, AttributeError):
            pass

    def remember(self, parameters: Mapping[str, Any]) -> None:
        self.saved_devices = self.chosen_devices()
        data = {"parameters": dict(parameters), "devices": self.saved_devices}
        settings().setValue(self.settings_key, json.dumps(data))

    # Running
    def parameters(self) -> Dict[str, Any]:
        """Of the next run, SI as JSON carries them."""
        return self.form.values()

    def start(self) -> None:
        if self.runner.running:
            QMessageBox.warning(
                self,
                "Measurement",
                "It is still running: Stop it, or Abort if it hangs",
            )
            return
        problem = self.devices_problem()
        if problem:
            self.devices_box.set_expanded(True)
            QMessageBox.warning(self, "Measurement", problem)
            return
        try:
            parameters = self.parameters()
            run = self.session.call(
                DescribeProcedure(
                    procedure=self.procedure,
                    parameters=parameters,
                    devices=self.mapping(),
                )
            )
        except (ValueError, LabError) as e:
            QMessageBox.warning(self, INVALID_PARAMETERS, str(e))
            return
        self.remember(parameters)
        self.window = run.plot_window
        self.raised = False
        self.reached = []
        self.expected = [plot.title for plot in run.plots]
        self.hub.show_run(self.expected)
        self.log.clear()
        self.log_box.set_summary("")
        self.update_status(state=CONNECTING, done=0, total=run.steps or None)
        self.stuck.start()
        self.runner.start(self.procedure, parameters, self.mapping(), self.comment)

    def check(self) -> None:
        """Whether it would start now, asked of the lab without starting it."""
        problem = self.devices_problem()
        if problem:
            self.devices_box.set_expanded(True)
            QMessageBox.warning(self, CHECK, problem)
            return
        try:
            planned = self.runner.check(
                self.procedure, self.parameters(), self.mapping()
            )
        except (ValueError, LabError) as e:
            self.note(f"would not start: {e}")
            QMessageBox.warning(self, CHECK, str(e))
            return
        steps = f"{planned.total} steps" if planned.total else "until stopped"
        devices = ", ".join(self.session.title_of(r) for r in planned.devices.values())
        text = f"Ready to start: {steps} on {devices or 'no devices'}"
        self.note(text)
        QMessageBox.information(self, CHECK, text)

    def on_conflict(self, message: str) -> None:
        """A device it needs is swept by another measurement: one question for
        the whole run."""
        self.note(message)
        answer = QMessageBox.question(
            self,
            self.info.title,
            f"{message}.\n\nStart anyway? A measurement that sweeps a device "
            "others change may get spoiled data; both note the conflict.",
        )
        if answer == QMessageBox.Yes:
            self.update_status(state=CONNECTING, done=0)
            self.stuck.start()
            self.runner.share()
        else:
            self.update_status(outcome="not started: a device is in use")

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
        self.runner.abort()
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
            self.measurement, self.plots, table, record, self.window
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
        QMessageBox.warning(self, self.info.title, message)

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
                procedure_groups.group(self.procedure).icon,
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

    def __init__(self, session, hub, procedure: str, parent=None):
        super().__init__(parent)
        about = session.procedure(procedure)
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(about.title or about.name)
        title.setProperty("role", "title")
        header_layout.addWidget(title)
        if about.description:
            text = QLabel(about.description)
            text.setWordWrap(True)
            text.setProperty("role", "muted")
            header_layout.addWidget(text)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.box = self.make_box(session, hub, procedure, header)
        layout.addWidget(self.box)

    def make_box(self, session, hub, procedure, header):
        return ProcedureBox(session, hub, procedure, header=header)

    def show_controls(self, on: bool) -> None:
        """Off in Lite: the bar on top runs the chosen measurement."""
        self.box.controls.setVisible(on)


# The monitor's parameter of what it watches: "<ref>" or "<ref>/<quantity key>"
WATCH = "watch"


class WatchTree(QTreeWidget):
    """Devices ticked to watch, each with the values to read.

    A device expands to its readable values; the measured ones are ticked when
    the device is ticked (power, voltage and current), setpoints can be added.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setMinimumHeight(160)
        self.itemChanged.connect(self.changed)
        self.defaults: Dict[str, List[str]] = {}  # ticked with the device

    def set_devices(
        self,
        devices: Iterable[Tuple[DeviceInfo, Sequence[QuantityInfo]]],
        entries: Iterable[str],
    ) -> None:
        chosen: Dict[str, set] = {}
        for entry in entries:
            ref, key = split_entry(entry)
            chosen.setdefault(ref, set())
            if key:
                chosen[ref].add(key)
        self.clear()
        self.defaults = {}
        for info, described in devices:
            quantities = monitor_quantities(described)
            if not quantities:
                continue
            self.defaults[info.ref] = [q.key for q in default_quantities(quantities)]
            item = QTreeWidgetItem([info.title])
            item.setIcon(0, theme.device_icon(info.kind, info.instrument))
            item.setData(0, Qt.UserRole, info.ref)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            keys = chosen.get(info.ref)
            if keys is not None and not keys:  # the device without a choice
                keys = set(self.defaults[info.ref])
            for quantity in quantities:
                child = QTreeWidgetItem([quantity.label])
                child.setData(0, Qt.UserRole, quantity.key)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                ticked = keys is not None and quantity.key in keys
                child.setCheckState(0, Qt.Checked if ticked else Qt.Unchecked)
                item.addChild(child)
            self.addTopLevelItem(item)
        self.changed.emit()

    def device_items(self) -> List[QTreeWidgetItem]:
        return [self.topLevelItem(i) for i in range(self.topLevelItemCount())]

    def set_device(self, ref: str, checked: bool) -> None:
        """Tick a device with its measured values (or untick all of it)."""
        for item in self.device_items():
            if item.data(0, Qt.UserRole) != ref:
                continue
            for i in range(item.childCount()):
                child = item.child(i)
                on = checked and child.data(0, Qt.UserRole) in self.defaults[ref]
                child.setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def entries(self) -> List[str]:
        """ref/key of every ticked value."""
        found = []
        for item in self.device_items():
            ref = item.data(0, Qt.UserRole)
            for i in range(item.childCount()):
                child = item.child(i)
                if child.checkState(0) == Qt.Checked:
                    found.append(f"{ref}{KEY_SEPARATOR}{child.data(0, Qt.UserRole)}")
        return found

    def refs(self) -> List[str]:
        return list(dict.fromkeys(split_entry(entry)[0] for entry in self.entries()))

    def mapping(self) -> Dict[str, str]:
        """A monitor's slots are the devices it watches."""
        return {ref: ref for ref in self.refs()}

    def summary(self) -> str:
        values = len(self.entries())
        refs = self.refs()
        titles = [
            item.text(0)
            for item in self.device_items()
            if item.data(0, Qt.UserRole) in refs
        ]
        return f"{values} values: {', '.join(titles)}" if values else "nothing ticked"


class MonitorBox(ProcedureBox):
    """Monitor over time: devices are ticked in a tree, each with the values to read."""

    def __init__(self, session, hub, procedure, header=None, parent=None):
        super().__init__(session, hub, procedure, header=header, parent=parent)
        self.devices_box.setTitle("Devices to watch")
        self.form.layout_.setRowVisible(self.form.editors[WATCH].widget, False)

    def make_devices(self) -> WatchTree:
        return WatchTree()

    def refresh_devices(self, *_) -> None:
        session = self.session
        saved = [e for e in self.saved_devices.get(WATCH, "").split(",") if e]
        self.devices.set_devices(
            (
                (info, session.description(info.ref).quantities)
                for info in session.devices()
            ),
            self.devices.entries() or saved,
        )
        self.devices_box.setVisible(True)
        self.show_devices_summary()

    def devices_problem(self) -> Optional[str]:
        return None if self.devices.entries() else "Tick the values to watch"

    def chosen_devices(self) -> Dict[str, str]:
        return {WATCH: ",".join(self.devices.entries())}

    def parameters(self) -> Dict[str, Any]:
        return {**super().parameters(), WATCH: self.devices.entries()}


class MonitorWidget(MeasureWidget):
    def make_box(self, session, hub, procedure, header):
        return MonitorBox(session, hub, procedure, header=header)


# Docks with their own widget class by procedure name
SPECIAL = {MONITOR_TIME: MonitorWidget}


def measure_widget(session, hub, procedure: str) -> MeasureWidget:
    return SPECIAL.get(procedure, MeasureWidget)(session, hub, procedure)
