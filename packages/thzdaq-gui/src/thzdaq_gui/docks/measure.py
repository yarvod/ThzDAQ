"""Measurements configured and run: the form of a procedure and its run.

What a procedure takes and needs is its description by the lab
(describe_procedure). Devices are chosen per slot from the bench, only those
with the needed capabilities are offered. A measurement's form (MeasureForm)
is what the popup under the run bar's settings button shows: its devices and
parameters; the bar starts and stops its run and the Log tab tells how it
goes. A ScanBox runs a quick scan inside a device dock with the device fixed
(I-V of this SIS bias), with its controls and log under it.
"""

import json
import logging
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.devices import DeviceInfo, QuantityInfo
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurements import DescribeProcedure, ProcedureInfo
from thzdaq_api import ui
from thzdaq_api.ui import FieldState
from thzdaq_api.procedures import (
    KEY_SEPARATOR,
    default_quantities,
    monitor_quantities,
    split_entry,
)

from thzdaq_gui import procedure_groups, theme
from thzdaq_gui.collapsible import Collapsible
from thzdaq_gui.dock_names import DEVICE, MEASURE, dock_name, field_name
from thzdaq_gui.docks.log import tell
from thzdaq_gui.forms import DeviceSlotsForm, ParameterForm
from thzdaq_gui.run_controls import (
    CONNECTING,
    IDLE,
    RUNNING,
    STOPPING,
    RunControls,
    RunStatus,
)
from thzdaq_gui.settings import (
    procedure_key,
    saved_procedure,
    sections_path,
    settings,
)
from thzdaq_gui.wording import INVALID_PARAMETERS

# A start or a stop that takes this long is treated as a hung device
STUCK_AFTER_MS = 5000
CHECK = "Check"
DEVICES_SECTION, PARAMETERS_SECTION = "devices", "parameters"  # as agents read them


class ProcedureBox(QWidget):
    """Devices and parameters of one procedure, and its run.

    One column under its header; whoever shows it scrolls it (the popup of
    the run bar). How the run goes is a RunStatus: the bar on top shows it
    for the chosen measurement; what the run tells goes to the Log tab,
    marked with the measurement.
    """

    scan = False  # a scan in a device dock (ScanBox)

    status_changed = Signal(str)  # its line: "Running 42 %", "completed #12"
    comment_changed = Signal(str)

    def __init__(
        self,
        session,
        hub,
        procedure: str,
        fixed: Optional[Mapping[str, str]] = None,
        header: Optional[QWidget] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.procedure = procedure  # its name
        # Records of a run go to every plot the procedure may fill
        self.plots = self.known_plots()
        # As the parameters in the form describe it: their slots
        self.info: ProcedureInfo = self.described()
        self.fixed = dict(fixed or {})
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
        sections = sections_path(procedure, scan=self.scan)
        self.devices_box = Collapsible("Devices", f"{sections}/devices")
        self.devices = self.make_devices()
        self.devices.changed.connect(self.show_devices_summary)
        self.devices_box.addWidget(self.devices)
        self.parameters_box = Collapsible("Parameters", f"{sections}/parameters")
        self.form = ParameterForm()
        self.form.set_parameters(self.info.parameters)
        self.parameters_box.addWidget(self.form)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if header is not None:
            layout.addWidget(header)
        layout.addWidget(self.devices_box)
        layout.addWidget(self.parameters_box)
        self.runner.started.connect(self.on_started)
        self.runner.resetting.connect(self.hub.clear_measurement)
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

    def known_plots(self):
        about = self.session.procedure(self.procedure)
        return about.plots if about is not None else ()

    def described(self) -> ProcedureInfo:
        """The procedure as its parameters' defaults describe it."""
        return self.session.call(DescribeProcedure(procedure=self.procedure))

    def reload(self) -> None:
        """The procedure described anew (its script saved): its form and
        devices, the values typed kept where their parameters stay."""
        try:
            typed = self.form.values()
        except ValueError:
            typed = {}
        self.plots = self.known_plots()
        self.info = self.described()
        self.form.set_parameters(self.info.parameters)
        self.form.set_values(typed)
        self.parameters_box.setVisible(bool(self.info.parameters))
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

    # The form as agents see and fill it (thzdaq_api.ui)
    def fields(self) -> List[FieldState]:
        return self.device_fields() + self.parameter_fields()

    def device_fields(self) -> List[FieldState]:
        chosen = self.devices.mapping()
        return [
            FieldState(
                field_name(self.procedure, slot.name),
                slot.name,
                ui.DEVICE,
                slot.title,
                chosen.get(slot.name, ""),
                choices=self.devices.choices(slot.name),
            )  # fmt: skip
            for slot in self.devices.slots.values()
        ]

    def parameter_fields(self) -> List[FieldState]:
        return [
            FieldState(
                field_name(self.procedure, p.name),
                p.name,
                ui.PARAMETER,
                p.label,
                self.form.typed(p.name),
                p.display_unit,
                tuple(f"{choice}" for choice in p.choices),
                self.form.shown(p.name),
            )  # fmt: skip
            for p in self.form.parameters.values()
        ]

    def folded(self) -> Tuple[str, ...]:
        """Its sections shown folded: devices, parameters."""
        sections = (
            (DEVICES_SECTION, self.devices_box),
            (PARAMETERS_SECTION, self.parameters_box),
        )
        return tuple(
            name for name, box in sections if not box.isHidden() and not box.expanded()
        )

    def field(self, key: str) -> QWidget:
        """The editor of a slot or a parameter, its section unfolded; LabError
        for a field it has not, or one the run does not use with these values."""
        widget = self.devices.widget(key)
        if widget is not None:
            self.devices_box.set_expanded(True, remember=False)
            return widget
        widget = self.form.widget(key)
        if widget is None:
            raise LabError(
                ErrorCode.NOT_FOUND,
                f"{self.info.title} has no field {key}",
                "ui_state lists the fields of its form",
            )
        parameter = self.form.parameters[key]
        if not self.form.shown(key):
            raise LabError(
                ErrorCode.NOT_ALLOWED,
                f"{parameter.label} is not used with these values",
                f"it is used when {parameter.used_when()}",
            )
        self.parameters_box.set_expanded(True, remember=False)
        return widget

    def fill(self, parameters: Mapping[str, Any], devices: Mapping[str, str]) -> None:
        """Parameters as JSON carries them (the daemon checked them), then
        devices by slot among those that suit it; LabError naming a device
        that does not suit its slot (the parameters stay filled), or while
        it runs (its fields are locked)."""
        if self.runner.running:
            raise LabError(
                ErrorCode.CONFLICT,
                f"{self.info.title} runs now: its form is locked",
                "fill it once it ended",
            )
        self.form.set_values(parameters)
        self.refresh_devices()
        wrong = [
            f"{slot}: {ref}" for slot, ref in devices.items()
            if not self.devices.choose(slot, ref)
        ]  # fmt: skip
        if wrong:
            suit = "; ".join(
                f"{slot}: {', '.join(self.devices.choices(slot)) or 'none'}"
                for slot in self.devices.slots
            )
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                f"Not for this measurement: {', '.join(wrong)}",
                f"devices that suit each slot: {suit or 'it takes none'}",
            )

    # What the run tells, and for whoever shows this run elsewhere
    def note(self, text: str, level: int = logging.INFO) -> None:
        """In the Log tab, marked with the measurement."""
        tell(self.procedure, self.info.title or self.procedure, text, level)

    def clear_notes(self) -> None:
        """A new run: the Log tab keeps what earlier runs told."""

    def process_title(self) -> str:
        return self.info.title or self.procedure

    def dock_name(self) -> str:
        """Where the window shows this run: the measurement in the run bar."""
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
        raw = saved_procedure(self.procedure)
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
        self.expected = self.graphs_of(run.plots)
        self.hub.show_run(self.expected)
        self.clear_notes()
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
            self.note(f"would not start: {e}", logging.WARNING)
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
        self.note(message, logging.WARNING)
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

    def chosen_plots(self, plots):
        """The plots of a run as the dock draws them (where each goes)."""
        return plots

    def graphs_of(self, plots) -> List[str]:
        """The graphs plots of a run are drawn in."""
        routed = self.hub.route(self.chosen_plots(plots), lambda _: None)
        return list(dict.fromkeys(plot.title for plot in routed))

    def show_graphs(self) -> None:
        """Its graphs on screen, each in front of its own group: those of the
        run going, else those the parameters and devices chosen would fill
        (all of the procedure's while they describe no run)."""
        if self.run_status.running and self.expected:
            titles = self.expected + [t for t in self.reached if t not in self.expected]
        else:
            try:
                run = self.session.call(
                    DescribeProcedure(
                        procedure=self.procedure,
                        parameters=self.parameters(),
                        devices=self.mapping(),
                    )
                )
                plots = run.plots
            except (ValueError, LabError):
                plots = self.plots
            titles = self.graphs_of(plots)
        self.hub.show_run(titles)

    def on_started(self, measurement) -> None:
        self.measurement = measurement
        self.plots = self.hub.route(self.chosen_plots(self.runner.plots), self.note)
        self.hub.register_plots(self.plots)
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
        self.note(message, logging.WARNING)
        self.update_status(outcome="failed to start")
        QMessageBox.warning(self, self.info.title, message)

    def on_finished(self, measurement) -> None:
        self.raise_graph()
        text = f"{measurement.status}"
        if measurement.error:
            text += f": {measurement.error}"
        if measurement.metadata.get("path"):
            text += f"\nsaved {measurement.metadata['path']}"
        self.note(text, logging.WARNING if measurement.error else logging.INFO)
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


class ScanBox(ProcedureBox):
    """A quick scan in a device dock, its device fixed (I-V of this SIS
    bias): the dock scrolls it; its comment, Start/Stop, state, progress and
    a folded log are under its devices and parameters."""

    scan = True

    def __init__(self, session, hub, procedure: str, fixed: Mapping[str, str]):
        super().__init__(session, hub, procedure, fixed)
        footer = QFrame()
        column = QVBoxLayout(footer)
        column.setContentsMargins(0, 6, 0, 0)
        self.controls = RunControls()
        self.controls.bind(self)
        column.addWidget(self.controls)
        # Folded, the log shows its last line
        sections = sections_path(procedure, scan=True)
        self.log_box = Collapsible("Log", f"{sections}/log", expanded=False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMaximumHeight(70)
        self.log_box.addWidget(self.log)
        column.addWidget(self.log_box)
        self.layout().addWidget(footer)

    def note(self, text: str, level: int = logging.INFO) -> None:
        self.log.appendPlainText(text)
        self.log_box.set_summary(text.splitlines()[-1] if text else "")

    def clear_notes(self) -> None:
        self.log.clear()
        self.log_box.set_summary("")

    def device(self) -> str:
        return next(iter(self.fixed.values()))

    def process_title(self) -> str:
        return f"{super().process_title()} · {self.session.title_of(self.device())}"

    def dock_name(self) -> str:
        """A scan is in its device's dock."""
        return dock_name(DEVICE, self.device())


class MeasureForm(QWidget):
    """What the popup under the run bar's settings button shows of a
    measurement: its title and description on top, its devices and
    parameters (the box, which runs it) under them."""

    def __init__(self, session, hub, procedure: str, parent=None):
        super().__init__(parent)
        header = self.make_header(session.procedure(procedure))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.box = self.make_box(session, hub, procedure, header)
        layout.addWidget(self.box)

    def make_header(self, about) -> QWidget:
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
        return header

    def make_box(self, session, hub, procedure, header):
        return ProcedureBox(session, hub, procedure, header=header)


# The monitor's parameter of what it watches: "<ref>" or "<ref>/<quantity key>"
WATCH = "watch"
WATCHED = "Devices to watch"


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

    def listed(self) -> Tuple[str, ...]:
        """Every device it offers, by ref."""
        return tuple(item.data(0, Qt.UserRole) for item in self.device_items())

    def widget(self, key: str) -> Optional[QWidget]:
        """The tree is the editor of what is watched."""
        return self if key == WATCH else None

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
        self.devices_box.setTitle(WATCHED)
        self.form.layout_.setRowVisible(self.form.editors[WATCH].widget, False)

    def make_devices(self) -> WatchTree:
        return WatchTree()

    def watched(self) -> Iterable[Tuple[DeviceInfo, Sequence[QuantityInfo]]]:
        """The devices to offer, with what each reads."""
        session = self.session
        return (
            (info, session.description(info.ref).quantities)
            for info in session.devices()
        )

    def refresh_devices(self, *_) -> None:
        saved = [e for e in self.saved_devices.get(WATCH, "").split(",") if e]
        self.devices.set_devices(self.watched(), self.devices.entries() or saved)
        self.devices_box.setVisible(True)
        self.show_devices_summary()

    def device_fields(self) -> List[FieldState]:
        """What is watched is one field: ref/key of each value, or the ref of
        a device with its measured values."""
        return [
            FieldState(
                field_name(self.procedure, WATCH), WATCH, ui.DEVICE, WATCHED,
                ", ".join(self.devices.entries()), choices=self.devices.listed(),
            )  # fmt: skip
        ]

    def parameter_fields(self) -> List[FieldState]:
        return [f for f in super().parameter_fields() if f.key != WATCH]

    def fill(self, parameters: Mapping[str, Any], devices: Mapping[str, str]) -> None:
        """What to watch comes as its parameter or as devices (a device with
        its measured values)."""
        watch = [*parameters.get(WATCH, ()), *devices]
        super().fill({k: v for k, v in parameters.items() if k != WATCH}, {})
        if watch:
            self.devices.set_devices(self.watched(), watch)

    def devices_problem(self) -> Optional[str]:
        return None if self.devices.entries() else "Tick the values to watch"

    def chosen_devices(self) -> Dict[str, str]:
        return {WATCH: ",".join(self.devices.entries())}

    def parameters(self) -> Dict[str, Any]:
        return {**super().parameters(), WATCH: self.devices.entries()}


class MonitorForm(MeasureForm):
    def make_box(self, session, hub, procedure, header):
        return MonitorBox(session, hub, procedure, header=header)
