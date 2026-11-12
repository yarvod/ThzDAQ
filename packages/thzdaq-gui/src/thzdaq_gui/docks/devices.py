"""Device docks: control and monitor one instrument or device.

What a dock shows is the device as the lab describes it: its quantities, its
actions and the settings it keeps in the profile, so every driver gets a
working dock. It reads, sets and acts through the lab (DeviceModel), and keeps
what belongs in the profile through update_station. Actions get buttons; an
analyzer's trace, a chopper's rotation and a SIS bias's calibration get groups
of their own, a device kind its quick scans. A device whose instrument takes
raw commands has their console in a folded Advanced section.
"""

import json
import math
import time
from typing import Any, Dict, List, Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.devices import (
    CHANNEL,
    INSTRUMENT,
    ActionInfo,
    ArgumentInfo,
    DeviceDescription,
    DeviceInfo,
    QuantityInfo,
    Trace,
)
from thzdaq_api.errors import LabError
from thzdaq_api.leases import EXCLUSIVE, READ, SHARED
from thzdaq_api.procedures import (
    CURRENT_VS_COIL_CURRENT,
    DEMAGNETIZATION,
    CURRENT_VS_VOLTAGE,
    default_quantities,
)
from thzdaq_api.station import GetSisCalibration, SetSisCalibration

from thzdaq_gui import profile as fmt
from thzdaq_gui import theme
from thzdaq_gui.collapsible import Collapsible
from thzdaq_gui.device_types import type_title
from thzdaq_gui.dock_names import DEVICE, dock_name
from thzdaq_gui.docks.measure import ProcedureBox
from thzdaq_gui.docks.raw import RawConsole
from thzdaq_gui.fields import PrefixBox, QuantityField, default_prefix, format_number
from thzdaq_gui.forms import CompactDoubleSpinBox, Editor
from thzdaq_gui.models.device import DeviceModel
from thzdaq_gui.settings import (
    ADVANCED,
    argument_key,
    sections_path,
    setpoint_key,
    settings,
)

# Actions of drivers a dock gives a place of its own, by key
TO_HOT, TO_COLD = "to_hot", "to_cold"
START_ROTATION, STOP = "start_rotation", "stop"
CONFIGURE, READ_TRACE = "configure", "read_trace"
WRITE_CALIBRATION = "write_calibration"  # a SIS bias's coefficients into the block
RUNNING = "running"  # what a chopper reads: whether it rotates
ACTION_ICONS = {
    TO_HOT: "fire",
    TO_COLD: "snowflake",
    "turn_on": "power",
    "turn_off": "power-off",
    START_ROTATION: "rotate-3d-variant",
    STOP: "stop",
    CONFIGURE: "check",
    READ_TRACE: "chart-line",
    WRITE_CALIBRATION: "upload",
}

# How a measurement uses a device it holds (its lease)
USES = {READ: "reads", SHARED: "sets", EXCLUSIVE: "sweeps"}

# Quick measurements of a device kind, run on the device: (title, procedure, slot)
SCANS = {
    "sis_bias": (("I-V scan", CURRENT_VS_VOLTAGE, "bias"),),
    "sis_coil": (
        ("I-CL scan", CURRENT_VS_COIL_CURRENT, "coil"),
        ("Demagnetization", DEMAGNETIZATION, "coil"),
    ),
}


def format_value(
    value, quantity: QuantityInfo, factor: float = 1.0, symbol=None
) -> str:
    if value is None:
        return "--"
    if quantity.kind == "bool":
        return "ON" if value else "OFF"
    if isinstance(value, float) and not math.isfinite(value):
        return "--"  # no value (a power meter in W at zero has no dBm)
    if isinstance(value, (int, float)):
        return format_number(value, factor, quantity.unit if symbol is None else symbol)
    return str(value)


class QuantityPanel(QWidget):
    """Read and set quantities of one device; optional polling and plotting.

    Fields start from the profile (configuration: multiplier, OEM head) or
    from the last values set (setpoints, in the registry); nothing is written
    to the device until Set or Enter. A configuration that differs in the
    device is marked after the first read. Monitor asks the lab to poll the
    device; readings come as they are told. A device that measures nothing
    but its setpoints (a generator, a grid, a YIG filter) shows what each
    holds next to its field, as a measured value is shown; a read that fails
    says why under the values.
    """

    def __init__(
        self,
        session,
        hub,
        model: DeviceModel,
        quantities: Sequence[QuantityInfo],
        kind: str,
        dock: str,
        config: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.model = model
        self.ref = model.ref
        self.title = model.title
        self.config = config
        self.dock = dock  # where Processes reveals its monitor
        self.process = None  # polling, in the session's Processes
        self.quantities: List[QuantityInfo] = list(quantities)
        self.by_key = {q.key: q for q in self.quantities}
        self.values: Dict[str, QLabel] = {}
        self.fields: Dict[str, QuantityField] = {}
        self.displays: Dict[str, PrefixBox] = {}
        self.toggles: Dict[str, QPushButton] = {}
        self.notes: Dict[str, QLabel] = {}
        self.held = [] if config else read_back(self.quantities)
        self.device_values: Dict[str, object] = {}
        self.read_once = False
        self.pending = False
        self.started = time.monotonic()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # One row per value: a setpoint is its field (what we set, not polled),
        # a measured value is its reading; spare width stays on the right
        grid = QGridLayout()
        for row, quantity in enumerate(self.quantities):
            grid.addWidget(QLabel(quantity.title), row, 0)
            if quantity.settable and quantity.kind == "bool":
                toggle = QPushButton("Off")
                toggle.setCheckable(True)
                toggle.clicked.connect(lambda on, q=quantity: self.write(q, on))
                grid.addWidget(toggle, row, 1)
                self.toggles[quantity.key] = toggle
            elif quantity.settable:
                field = QuantityField(quantity, self.ref, kind)
                field.apply_requested.connect(lambda q=quantity: self.apply(q))
                self.fields[quantity.key] = field
                button = QPushButton(theme.icon("check"), "Set")
                button.setToolTip("Write to the device (or press Enter in the field)")
                button.clicked.connect(lambda _=False, q=quantity: self.apply(q))
                grid.addWidget(field, row, 1)
                grid.addWidget(button, row, 2)
            elif quantity.readable:
                value = QLabel("--")
                value.setProperty("role", "value")
                self.values[quantity.key] = value
                if quantity.kind == "bool":
                    grid.addWidget(value, row, 1)
                else:
                    display = PrefixBox(
                        quantity.prefixes,
                        quantity.unit,
                        default_prefix(kind, quantity.key, quantity.unit),
                    )
                    display.setToolTip("Unit of the reading")
                    self.displays[quantity.key] = display
                    cell = QHBoxLayout()
                    cell.addWidget(value, 1)
                    cell.addWidget(display)
                    grid.addLayout(cell, row, 1)
            if quantity in self.held:
                value = QLabel("--")
                value.setProperty("role", "value")
                value.setToolTip("What the device holds now")
                self.values[quantity.key] = value
                grid.addWidget(value, row, 3)
            if config and quantity.readable:
                note = QLabel()
                note.setStyleSheet(f"color: {theme.ACCENT}")
                note.linkActivated.connect(lambda _, q=quantity: self.take(q))
                note.hide()
                grid.addWidget(note, row, 3)
                self.notes[quantity.key] = note
        grid.setColumnStretch(4, 1)
        layout.addLayout(grid)
        self.problem = QLabel()  # why the last read failed, until one succeeds
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(f"color: {theme.BAD}")
        layout.addWidget(self.problem)
        self.problem.hide()
        self.prefill()
        controls = QHBoxLayout()
        self.btnRead = QPushButton(theme.icon("refresh"), "Read")
        self.btnRead.clicked.connect(self.read)
        self.monitor = QCheckBox("Monitor")
        self.interval = CompactDoubleSpinBox()
        self.interval.setRange(0.1, 3600)
        self.interval.setValue(1.0)
        self.interval.setSuffix(" s")
        self.plot = QCheckBox("Plot")
        self.plot.setToolTip("Send the measured values to the P-t, V-t, I-t ... graphs")
        self.window = CompactDoubleSpinBox()
        self.window.setRange(0, 1e6)
        self.window.setDecimals(0)
        self.window.setValue(600)
        self.window.setSuffix(" s")
        self.window.setSpecialValueText("all")
        self.window.setToolTip(
            "The graphs show this last part of the curve, so a long monitor "
            "stays fast; 0 shows everything"
        )
        self.plotted = default_quantities(self.quantities)
        self.raised = False
        controls.addWidget(self.btnRead)
        controls.addWidget(self.monitor)
        controls.addWidget(self.interval)
        controls.addWidget(self.plot)
        controls.addWidget(self.window)
        controls.addStretch()
        # Parent first: setVisible() on a widget without a parent shows it as a window
        layout.addLayout(controls)
        hidden = (self.monitor, self.interval, self.plot, self.window) if config else ()
        if not self.plotted:
            hidden += (self.plot, self.window)
        if not any(q.readable for q in self.quantities):
            hidden = (self.btnRead, self.monitor, self.interval, self.plot, self.window)
        for widget in hidden:
            widget.hide()
        self.monitor.toggled.connect(self.set_monitoring)
        self.interval.valueChanged.connect(self.repoll)
        self.interval.valueChanged.connect(self.show_process_status)
        self.plot.toggled.connect(self.plot_toggled)
        model.values.connect(self.show_values)
        model.observed.connect(self.show_observed)
        model.unknown.connect(self.forget)
        model.read_failed.connect(self.failed)
        model.set_done.connect(self.was_set)
        model.set_failed.connect(self.set_failed)
        if model.known_values:
            self.show_observed(model.known_values)

    # Where values are remembered: a configuration in the profile, a setpoint here
    def kept(self) -> Dict[str, Any]:
        """The instrument's configuration in the profile."""
        instrument = fmt.instruments(self.session.profile().profile).get(self.ref)
        return (instrument or {}).get(fmt.SETTINGS) or {}

    def remembered(self, key: str):
        if self.config:
            return self.kept().get(key)
        return settings().value(setpoint_key(self.ref, key))

    def remember(self, quantity: QuantityInfo, value) -> None:
        if not self.config:
            settings().setValue(setpoint_key(self.ref, quantity.key), value)
            return
        if self.kept().get(quantity.key) == value:
            return
        profile = fmt.changed(self.session.profile().profile)
        instrument = fmt.instruments(profile)[self.ref]
        instrument.setdefault(fmt.SETTINGS, {})[quantity.key] = value
        try:
            self.session.update_profile(profile)
        except LabError as e:
            self.tell(str(e))

    def prefill(self) -> None:
        for key, field in self.fields.items():
            value = self.remembered(key)
            if value is not None:
                try:
                    field.set_value(float(value) if field.spin else value)
                except (TypeError, ValueError):
                    pass

    # Reading
    def watched(self, quantity: QuantityInfo) -> bool:
        """Read on every poll: what the device measures or switches, its
        configuration (to compare), a setpoint only when it is plotted."""
        if not quantity.readable:
            return False
        if not quantity.settable or quantity.kind == "bool" or self.config:
            return True
        if quantity in self.held:
            return True
        return self.plot.isChecked() and quantity in self.plotted

    def polled(self, quantity: QuantityInfo) -> bool:
        """Read now: what is watched, and a setpoint once, to fill its field
        (it is what we set)."""
        return self.watched(quantity) or (quantity.readable and not self.read_once)

    def read(self) -> None:
        keys = [q.key for q in self.quantities if self.polled(q)]
        if self.pending or not keys:
            return
        self.pending = True
        self.model.read(keys)

    def set_monitoring(self, on: bool) -> None:
        if on:
            self.started = time.monotonic()
            self.raised = False
            if self.process is None:
                self.process = self.session.processes.start(
                    f"Monitor · {self.title}",
                    "timer-outline",
                    self.dock,
                    stop=lambda: self.monitor.setChecked(False),
                )
            self.show_process_status()
            self.read()
            self.repoll()
        else:
            self.model.stop_polling()
            self.session.processes.finish(self.process)
            self.process = None

    def repoll(self, *_) -> None:
        """The poll as the monitor asks for it now: its interval, what is watched."""
        if self.monitor.isChecked():
            keys = [q.key for q in self.quantities if self.watched(q)]
            self.model.poll(self.interval.value(), keys)

    def show_process_status(self, *_) -> None:
        if self.process is not None:
            self.process.update(status=f"every {self.interval.value():g} s")

    def show_observed(self, values) -> None:
        """What the lab knows, set or read by anyone: idle setpoint fields follow
        it (profile settings are not written). Not a reading: it ends no read
        and goes on no graph, it may be old."""
        if not self.config:
            for key, value in values.items():
                field = self.fields.get(key)
                if field is not None and value is not None and not field.pending:
                    field.set_value(value)
        self.show_held(values)

    def show_values(self, values) -> None:
        """A reading of the device: what it holds of this panel's values."""
        self.pending = False
        self.problem.hide()
        now = time.monotonic() - self.started
        first = not self.read_once
        self.read_once = True
        self.show_held(values)
        for key, field in self.fields.items():
            if first and key in values and not field.pending:
                if self.remembered(key) is None:
                    field.set_value(values[key])
        if self.plot.isChecked():
            self.plot_values(values, now)

    def show_held(self, values) -> None:
        """What the device holds of this panel's values: readouts, switches and,
        for a configuration, how it differs from the profile."""
        for quantity in self.quantities:
            if quantity.key not in values:
                continue
            value = values[quantity.key]
            if quantity.key in self.values:
                box = self.fields.get(quantity.key)
                box = box.prefix if box is not None else self.displays.get(quantity.key)
                factor = box.factor() if box is not None else 1.0
                symbol = box.symbol() if box is not None and box.count() else None
                self.values[quantity.key].setText(
                    format_value(value, quantity, factor, symbol)
                )
            toggle = self.toggles.get(quantity.key)
            if toggle is not None and value is not None:
                toggle.setChecked(bool(value))
                toggle.setText("On" if value else "Off")
            if self.config and value is not None:
                self.compare(quantity, value)

    def plot_toggled(self, on: bool) -> None:
        self.raised = not on
        self.repoll()

    def plot_values(self, values, now: float) -> None:
        window = self.window.value() or None
        for quantity in self.plotted:
            if quantity.key not in values:
                continue
            self.hub.monitor_value(
                self.ref, self.title, quantity, now, values[quantity.key], window
            )
        plotted = [q for q in self.plotted if values.get(q.key) is not None]
        if plotted and not self.raised:
            # The graphs of the values come on screen once a monitor or Plot
            # starts, each in front of its own group
            self.raised = True
            self.hub.show_monitor(plotted)

    def compare(self, quantity: QuantityInfo, value) -> None:
        """Mark a configuration that differs between the device and the profile."""
        note = self.notes.get(quantity.key)
        saved = self.remembered(quantity.key)
        if note is None:
            return
        self.device_values[quantity.key] = value
        same = saved is None or _same(saved, value)
        note.setVisible(not same)
        note.setText(
            f'device: {value}  (profile: {saved})  <a href="take">Take from device</a>'
        )
        note.setToolTip(
            "The device differs from the station profile. Set writes the field "
            "value to the device; Take from device saves the device value in the profile."
        )

    def take(self, quantity: QuantityInfo) -> None:
        """Keep the device value: into the field and the profile, nothing is written."""
        value = self.device_values.get(quantity.key)
        if value is None:
            return
        field = self.fields.get(quantity.key)
        if field is not None:
            field.set_value(value)
        self.notes[quantity.key].hide()
        self.remember(quantity, value)

    def forget(self) -> None:
        """Nothing is known of the device (a raw write to its instrument): its
        readouts are empty until it is read again."""
        for label in self.values.values():
            label.setText("--")

    def failed(self, message: str) -> None:
        self.pending = False
        self.monitor.setChecked(False)
        self.forget()
        self.problem.setText(message)
        self.problem.show()
        self.tell(message)

    def tell(self, message: str) -> None:
        """In the status bar, with the device named."""
        self.session.calls.error.emit(f"{self.title}: {message}")

    # Writing
    def apply(self, quantity: QuantityInfo) -> None:
        field = self.fields.get(quantity.key)
        if field is not None:
            self.write(quantity, field.value())

    def write(self, quantity: QuantityInfo, value) -> None:
        if quantity.danger and not confirmed(self, quantity.title, quantity.danger):
            self.unflip(quantity.key, value)
            return
        self.model.set(quantity.key, value)

    def was_set(self, key: str, value) -> None:
        quantity = self.by_key.get(key)
        if quantity is None:
            return  # another panel's value of the device
        field = self.fields.get(key)
        if field is not None:
            field.set_value(value)  # the field is what the device was set to
        self.remember(quantity, value)
        self.read()

    def set_failed(self, key: str, value, message: str) -> None:
        if key in self.by_key:
            self.unflip(key, value)
            self.tell(message)

    def unflip(self, key: str, value) -> None:
        """A switch the click has flipped goes back: it was not set."""
        toggle = self.toggles.get(key)
        if toggle is not None:
            toggle.setChecked(not value)
            toggle.setText("On" if not value else "Off")

    def stop(self) -> None:
        self.monitor.setChecked(False)


def read_back(quantities: Sequence[QuantityInfo]) -> List[QuantityInfo]:
    """Setpoints whose reading a dock shows next to their field: those of a
    device that measures nothing else (a generator, a grid, a YIG filter); a
    device that measures (a supply, a SIS bias) shows what it measures."""
    if any(q.readable and not q.settable for q in quantities):
        return []
    return [q for q in quantities if q.readable and q.settable]


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)))
    except (TypeError, ValueError):
        return str(a).strip().upper() == str(b).strip().upper()


def confirmed(parent: QWidget, title: str, danger: str) -> bool:
    """Whether a person goes on with something that may harm the bench."""
    answer = QMessageBox.question(parent, title, f"{danger}. {title}?")
    return answer == QMessageBox.Yes


def action_button(action: ActionInfo, run) -> QPushButton:
    """A button running a device action; a dangerous one asks first, with its
    warning."""
    button = QPushButton(theme.icon(ACTION_ICONS.get(action.key, "play")), action.title)
    button.setToolTip(action.help or action.danger)

    def clicked():
        if action.danger and not confirmed(button, action.title, action.danger):
            return
        run()

    button.clicked.connect(clicked)
    return button


def argument_editor(argument: ArgumentInfo) -> Editor:
    """An editor of one argument of an action, SI values."""
    if argument.kind == "float":
        spin = pg.SpinBox(
            suffix=argument.unit,
            siPrefix=bool(argument.prefixes),
            dec=True,
            bounds=(argument.minimum, argument.maximum),
        )
        return Editor(spin, spin.value, lambda v: spin.setValue(float(v)))
    if argument.kind == "int":
        whole = QSpinBox()
        low, high = argument.minimum, argument.maximum
        whole.setRange(
            -(2**31) if low is None else int(low),
            2**31 - 1 if high is None else int(high),
        )
        return Editor(whole, whole.value, lambda v: whole.setValue(int(v)))
    if argument.kind == "bool":
        check = QCheckBox()
        return Editor(
            check, check.isChecked, lambda v: check.setChecked(v in (True, "true"))
        )
    if argument.choices:
        combo = QComboBox()
        combo.addItems(argument.choices)
        return Editor(
            combo, combo.currentText, lambda v: combo.setCurrentIndex(combo.findText(v))
        )
    line = QLineEdit()
    return Editor(line, line.text, lambda v: line.setText(str(v)))


class ArgumentFields(QWidget):
    """Editors of an action's arguments; the values given last are remembered
    per device."""

    def __init__(self, ref: str, action: ActionInfo, parent=None):
        super().__init__(parent)
        self.ref = ref
        self.action = action
        self.editors: Dict[str, Editor] = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        for argument in action.arguments:
            editor = argument_editor(argument)
            saved = settings().value(self.key(argument))
            start = saved if saved is not None else argument.default
            if start is None:
                start = argument.minimum
            if start is not None:
                editor.set(start)
            form.addRow(argument.title, editor.widget)
            self.editors[argument.key] = editor

    def key(self, argument: ArgumentInfo) -> str:
        return argument_key(self.ref, self.action.key, argument.key)

    def values(self) -> Dict[str, Any]:
        return {key: editor.get() for key, editor in self.editors.items()}

    def remember(self) -> None:
        for argument in self.action.arguments:
            settings().setValue(self.key(argument), self.editors[argument.key].get())

    def text(self) -> str:
        """The values as people read them: "7.5 Hz"."""
        values = self.values()
        return ", ".join(
            (
                f"{values[a.key]:g} {a.unit}".strip()
                if isinstance(values[a.key], (int, float))
                else str(values[a.key])
            )
            for a in self.action.arguments
        )


class ActionsGroup(QGroupBox):
    """Buttons running device actions; an action with arguments has its fields
    above its button. After an action that changes the device, the panel reads
    it."""

    def __init__(
        self,
        title: str,
        panel: QuantityPanel,
        actions: Sequence[ActionInfo],
        parent=None,
    ):
        super().__init__(title, parent)
        self.panel = panel
        self.actions = {action.key: action for action in actions}
        self.arguments: Dict[str, ArgumentFields] = {}
        layout = QVBoxLayout(self)
        self.row = QHBoxLayout()  # actions without arguments
        layout.addLayout(self.row)
        for action in actions:
            button = action_button(action, lambda a=action: self.run(a))
            if not action.arguments:
                self.row.addWidget(button)
                continue
            fields = ArgumentFields(panel.ref, action)
            self.arguments[action.key] = fields
            line = QHBoxLayout()
            line.addWidget(fields)
            line.addWidget(button)
            line.addStretch()
            layout.addLayout(line)
        self.row.addStretch()
        self.result = QLabel()
        self.result.setProperty("role", "muted")
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        panel.model.acted.connect(self.done)
        panel.model.action_failed.connect(self.failed)

    def add_to_row(self, widget: QWidget) -> None:
        self.row.insertWidget(self.row.count() - 1, widget)  # before the stretch

    def call(self, key: str) -> None:
        self.run(self.actions[key])

    def run(self, action: ActionInfo) -> None:
        fields = self.arguments.get(action.key)
        arguments = fields.values() if fields is not None else {}
        if fields is not None:
            fields.remember()
        self.result.setText("working...")
        self.panel.model.call(action.key, arguments)

    def done(self, key: str, result) -> None:
        if key not in self.actions:
            return
        self.result.setText("" if result is None else str(result))
        if self.actions[key].changes:
            self.panel.read()

    def failed(self, key: str, message: str) -> None:
        if key in self.actions:
            self.result.setText(message)


class ChopperGroup(ActionsGroup):
    """Hot / Cold and continuous rotation.

    Hot and Cold turn the blade by the sensors until the load is in place
    (aligned to the detent), so no separate rotate or align is needed. While
    the chopper says it rotates, the rotation is in Processes.
    """

    def __init__(
        self, panel: QuantityPanel, actions: Sequence[ActionInfo], parent=None
    ):
        super().__init__("Chopper", panel, actions, parent)
        self.process = None  # continuous rotation, in the session's Processes
        panel.model.values.connect(self.show_values)
        self.destroyed.connect(lambda: panel.session.processes.finish(self.process))

    def show_values(self, values) -> None:
        if RUNNING in values:
            self.show_rotation(bool(values[RUNNING]))

    def show_rotation(self, rotating: bool) -> None:
        processes = self.panel.session.processes
        if rotating and self.process is None:
            self.process = processes.start(
                f"Rotation · {self.panel.title}",
                "fan",
                self.panel.dock,
                stop=lambda: self.call(STOP),
            )
        elif not rotating:
            processes.finish(self.process)
            self.process = None
        if self.process is not None:
            self.process.update(status=self.arguments[START_ROTATION].text())


class TraceGroup(ActionsGroup):
    """An analyzer: its sweep (configure) and the last trace, read once or
    continuously."""

    KEYS = (CONFIGURE, READ_TRACE)

    def __init__(
        self,
        title: str,
        panel: QuantityPanel,
        actions: Sequence[ActionInfo],
        parent=None,
    ):
        super().__init__(title, panel, actions, parent)
        self.continuous = QCheckBox("Continuous")
        self.continuous.toggled.connect(
            lambda on: self.timer.start(500) if on else self.timer.stop()
        )
        self.add_to_row(self.continuous)
        self.graph = pg.PlotWidget()
        self.graph.setLabel("bottom", "Frequency", units="Hz")
        self.graph.showGrid(x=True, y=True, alpha=0.25)
        self.graph.setMinimumHeight(220)
        self.curve = self.graph.plot([], [], pen=pg.mkPen(theme.ACCENT, width=1))
        self.layout().addWidget(self.graph)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.read)
        self.pending = False

    def read(self) -> None:
        if not self.pending:
            self.pending = True
            self.call(READ_TRACE)

    def done(self, key: str, result) -> None:
        if key == READ_TRACE:
            self.pending = False
            self.result.setText("")
            self.show(result)
        else:
            super().done(key, result)

    def failed(self, key: str, message: str) -> None:
        if key == READ_TRACE:
            self.pending = False
            self.continuous.setChecked(False)
        super().failed(key, message)

    def show(self, trace: Trace) -> None:
        values = np.asarray(trace.values)
        if trace.imaginary is not None:
            with np.errstate(divide="ignore"):
                values = 20 * np.log10(np.hypot(values, np.asarray(trace.imaginary)))
        self.graph.setLabel("left", trace.label())
        self.curve.setData(np.asarray(trace.frequency), values)


class SettingsGroup(QGroupBox):
    """What a configured device keeps in the station profile (a SIS bias's
    offsets), in the same fields as the rest of the dock."""

    def __init__(self, panel: QuantityPanel, kind: str, described, parent=None):
        super().__init__("Settings", parent)
        self.panel = panel
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        _, device = fmt.find_device(panel.session.profile().profile, panel.ref)
        saved = device.get(fmt.SETTINGS) or {}
        self.fields: Dict[str, QuantityField] = {}
        for setting in described:
            field = QuantityField(setting, panel.ref, kind)
            field.set_value(saved.get(setting.key, 0.0))
            field.apply_requested.connect(self.save)
            layout.addRow(setting.title, field)
            self.fields[setting.key] = field
        save = QPushButton(theme.icon("content-save-outline"), "Save")
        save.setToolTip("Keep them in the station profile (or Enter in a field)")
        save.clicked.connect(self.save)
        layout.addRow("", save)

    def save(self) -> None:
        session = self.panel.session
        profile = fmt.changed(session.profile().profile)
        _, device = fmt.find_device(profile, self.panel.ref)
        values = device.setdefault(fmt.SETTINGS, {})
        for key, field in self.fields.items():
            values[key] = float(field.value())
        try:
            session.update_profile(profile)
        except LabError as e:
            QMessageBox.warning(self, self.title(), str(e))
            return
        for field in self.fields.values():
            field.set_pending(False)


class CalibrationDialog(QDialog):
    """SIS block calibration coefficients: expressions allowed ("5.47e-9 / 5").
    Save hands them to the lab, which checks them; a refusal is shown here."""

    def __init__(self, coefficients: dict, save, parent=None):
        super().__init__(parent)
        self.save = save
        self.setWindowTitle("SIS calibration coefficients")
        self.resize(520, 520)
        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit(json.dumps(coefficients, indent=2))
        layout.addWidget(self.editor)
        self.problem = QLabel()
        self.problem.setStyleSheet(f"color: {theme.BAD}")
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.check)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.coefficients = coefficients

    def check(self) -> None:
        try:
            data = json.loads(self.editor.toPlainText())
            self.save(data)
        except (ValueError, LabError) as e:
            self.problem.setText(str(e))
            return
        self.coefficients = data
        self.accept()


class CalibrationGroup(QGroupBox):
    """Calibration coefficients of a SIS bias, kept in the station profile, and
    their write into the block."""

    def __init__(self, panel: QuantityPanel, action: ActionInfo, parent=None):
        super().__init__("Calibration", parent)
        self.panel = panel
        row = QHBoxLayout(self)
        edit = QPushButton(theme.icon("table-edit"), "Coefficients…")
        edit.clicked.connect(self.edit_calibration)
        row.addWidget(edit)
        row.addWidget(action_button(action, self.write_calibration))
        row.addStretch()
        panel.model.acted.connect(self.written)
        panel.model.action_failed.connect(self.refused)

    def calibration(self) -> dict:
        """As the profile keeps them, or the defaults of the channel."""
        return self.panel.session.call(GetSisCalibration(ref=self.panel.ref))

    def keep(self, coefficients: dict) -> None:
        self.panel.session.call(
            SetSisCalibration(ref=self.panel.ref, coefficients=coefficients)
        )

    def edit_calibration(self) -> None:
        CalibrationDialog(self.calibration(), self.keep, self).exec()

    def write_calibration(self) -> None:
        """With the coefficients of the profile as it is now."""
        self.panel.model.call(WRITE_CALIBRATION)

    def written(self, key: str, answer) -> None:
        if key == WRITE_CALIBRATION:
            QMessageBox.information(self, self.title(), f"Block answered: {answer}")

    def refused(self, key: str, message: str) -> None:
        if key == WRITE_CALIBRATION:
            QMessageBox.critical(self, self.title(), message)


def scan_group(session, hub, title: str, procedure: str, fixed) -> Collapsible:
    """A quick measurement of this device, folded by default: the measurement
    docks run the same; folded, the title line shows how it runs."""
    section = Collapsible(title, sections_path(procedure, scan=True), expanded=False)
    box = ProcedureBox(session, hub, procedure, fixed, compact=True)
    box.reveal = lambda: section.set_expanded(True)
    box.status_changed.connect(section.set_summary)
    section.addWidget(box)
    return section


def channels_of(devices: Sequence[DeviceInfo], info: DeviceInfo) -> List[DeviceInfo]:
    """The fixed channels of an instrument (outputs of a supply), shown in its dock."""
    if info.kind != INSTRUMENT:
        return []
    return [d for d in devices if d.kind == CHANNEL and d.instrument == info.ref]


def has_content(session, info: DeviceInfo) -> bool:
    """Whether the dock of a device would show anything: its controls, or
    the raw commands of an instrument no other dock shows them for (one
    without a driver of its own)."""
    if info.kind in SCANS:
        return True
    described = session.description(info.ref)
    if described.quantities or described.actions or described.settings:
        return True
    devices = session.devices()
    if info.raw and info.kind == INSTRUMENT:
        others = [d for d in devices if d.instrument == info.ref and d.ref != info.ref]
        if not others:
            return True
    return any(
        session.description(channel.ref).quantities
        for channel in channels_of(devices, info)
    )


class DeviceWidget(QScrollArea):
    """Dock content of an instrument (with its fixed channels) or a device."""

    def __init__(self, session, hub, info: DeviceInfo, parent=None):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.info = info
        self.ref = info.ref
        self.panels: List[QuantityPanel] = []
        self.setWidgetResizable(True)
        described = session.description(info.ref)
        dock = dock_name(DEVICE, info.ref)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        title = QLabel(info.title)
        title.setProperty("role", "title")
        layout.addWidget(title)
        subtitle = QLabel(
            f"{info.driver} · {info.ref}"
            + ("" if info.kind == INSTRUMENT else f" · {info.kind}")
        )
        subtitle.setProperty("role", "muted")
        layout.addWidget(subtitle)
        self.use = QLabel()  # who uses it now
        self.use.setWordWrap(True)
        self.use.setStyleSheet(f"color: {theme.ACCENT}")
        layout.addWidget(self.use)
        self.channels = channels_of(session.devices(), info)
        model = DeviceModel(session, info, self)
        model.conflict.connect(self.ask_to_share)
        main = QuantityPanel(
            session, hub, model,
            [q for q in described.quantities if not q.persistent], info.kind, dock,
        )  # fmt: skip
        if main.quantities:
            layout.addWidget(self._boxed("Values", main))
        self.panels.append(main)
        if info.kind == INSTRUMENT:
            # Multiplier, OEM head: kept in the profile, compared with the device
            config = QuantityPanel(
                session, hub, model,
                [q for q in described.quantities if q.persistent], info.kind, dock,
                config=True,
            )  # fmt: skip
            if config.quantities:
                layout.addWidget(self._boxed("Configuration", config))
                self.panels.append(config)
        for channel in self.channels:
            quantities = session.description(channel.ref).quantities
            channel_model = DeviceModel(session, channel, self)
            channel_model.conflict.connect(self.ask_to_share)
            panel = QuantityPanel(
                session, hub, channel_model,
                [q for q in quantities if not q.persistent], CHANNEL, dock,
            )  # fmt: skip
            self.panels.append(panel)
            layout.addWidget(self._boxed(channel.title, panel))
        for group in self.groups(main, described):
            layout.addWidget(group)
        if info.raw:
            # Commands to its instrument the driver does not wrap: rarely needed
            advanced = Collapsible("Advanced", ADVANCED, expanded=False)
            advanced.set_summary(f"raw commands to {info.instrument}")
            advanced.addWidget(RawConsole(model))
            layout.addWidget(advanced)
        layout.addStretch()
        self.setWidget(inner)
        session.leases_changed.connect(self.show_use)
        self.show_use()

    def show_use(self) -> None:
        """Which running measurements use it (or its channels) and how."""
        refs = {self.ref, *(channel.ref for channel in self.channels)}
        uses = [
            f"#{lease.run} {lease.title} {USES[lease.mode]} "
            f"{self.session.title_of(lease.device)}"
            for lease in self.session.leases()
            if lease.device in refs
        ]
        self.use.setText("In use: " + "; ".join(uses))
        self.use.setVisible(bool(uses))

    def ask_to_share(self, message: str, again) -> None:
        """A device another measurement sweeps: change it anyway?"""
        answer = QMessageBox.question(
            self,
            self.info.title,
            f"{message}.\n\nChange it anyway? The measurement notes who changed "
            "what, and its data may be spoiled.",
        )
        if answer == QMessageBox.Yes:
            again()

    @staticmethod
    def _boxed(title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        QVBoxLayout(box).addWidget(widget)
        return box

    def groups(self, panel: QuantityPanel, described: DeviceDescription):
        """Its actions, settings and quick scans."""
        info, session, hub = self.info, self.session, self.hub
        actions = {action.key: action for action in described.actions}
        groups = []
        traced = [actions.pop(key) for key in TraceGroup.KEYS if key in actions]
        calibration = actions.pop(WRITE_CALIBRATION, None)
        if actions:
            chopper = START_ROTATION in actions
            rest = list(actions.values())
            groups.append(
                ChopperGroup(panel, rest)
                if chopper
                else ActionsGroup("Actions", panel, rest)
            )
        if traced:
            groups.append(TraceGroup(type_title(info.type), panel, traced))
        if described.settings:
            groups.append(SettingsGroup(panel, info.kind, described.settings))
        if calibration is not None:
            groups.append(CalibrationGroup(panel, calibration))
        for title, procedure, slot in SCANS.get(info.kind, ()):
            groups.append(scan_group(session, hub, title, procedure, {slot: info.ref}))
        return groups

    def stop(self) -> None:
        for panel in self.panels:
            panel.stop()
