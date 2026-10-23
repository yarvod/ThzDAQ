"""Device docks: control and monitor one instrument or device.

The controls come from the device quantities (what its capabilities can read
or set), so every driver gets a working dock. Kinds and capabilities that
need more (SIS bias offsets and calibration, coil demagnetization, chopper,
compressor, analyzers) add their own groups below.
"""

import copy
import json
import time
from typing import Dict, List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.measurements.procedures.monitor import default_quantities
from thzdaq_core.measurements.registry import get_procedure
from thzdaq_core.sis import calibration_for, evaluate_sis_calibration
from thzdaq_core.station.station import INSTRUMENT, channel_title
from thzdaq_instruments.capabilities import (
    Compressor,
    LoadSwitch,
    NetworkAnalyzer,
    SpectrumAnalyzer,
)
from thzdaq_instruments.quantities import Quantity, read_values

from thzdaq_gui import theme
from thzdaq_gui.docks.measure import ProcedureBox
from thzdaq_gui.fields import (
    PrefixBox,
    QuantityField,
    default_prefix,
    format_number,
)
from thzdaq_gui.settings import settings


def format_value(value, quantity: Quantity, factor: float = 1.0, symbol=None) -> str:
    if value is None:
        return "--"
    if quantity.kind == "bool":
        return "ON" if value else "OFF"
    if isinstance(value, (int, float)):
        return format_number(value, factor, quantity.unit if symbol is None else symbol)
    return str(value)


class QuantityPanel(QWidget):
    """Read and set quantities of one device; optional polling and plotting.

    Fields start from the profile (configuration: multiplier, OEM head) or
    from the last values set (setpoints, in the registry); nothing is written
    to the device until Set or Enter. A configuration that differs in the
    device is marked after the first read.
    """

    def __init__(
        self,
        session,
        hub,
        ref: str,
        title: str,
        kind: str = "",
        config: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.ref = ref
        self.title = title
        self.config = config
        self.quantities: List[Quantity] = [
            q for q in session.station.quantities(ref) if q.persistent == config
        ]
        self.values: Dict[str, QLabel] = {}
        self.fields: Dict[str, QuantityField] = {}
        self.displays: Dict[str, PrefixBox] = {}
        self.toggles: Dict[str, QPushButton] = {}
        self.notes: Dict[str, QLabel] = {}
        self.device_values: Dict[str, object] = {}
        self.read_once = False
        self.pending = False
        self.started = time.monotonic()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        for row, quantity in enumerate(self.quantities):
            grid.addWidget(QLabel(quantity.title), row, 0)
            field = None
            if quantity.settable and quantity.kind != "bool":
                field = QuantityField(quantity, ref, kind)
                field.apply_requested.connect(lambda q=quantity: self.apply(q))
                self.fields[quantity.key] = field
            if quantity.readable:
                value = QLabel("--")
                value.setProperty("role", "value")
                grid.addWidget(value, row, 1)
                self.values[quantity.key] = value
                if field is None and quantity.kind != "bool":
                    display = PrefixBox(
                        quantity.unit, default_prefix(kind, quantity.key, quantity.unit)
                    )
                    self.displays[quantity.key] = display
                    grid.addWidget(display, row, 2)
            if quantity.settable and quantity.kind == "bool":
                toggle = QPushButton("Off")
                toggle.setCheckable(True)
                toggle.clicked.connect(lambda on, q=quantity: self.write(q, on))
                grid.addWidget(toggle, row, 2, 1, 2)
                self.toggles[quantity.key] = toggle
            elif field is not None:
                button = QPushButton(theme.icon("check"), "Set")
                button.setToolTip("Write to the device (or press Enter in the field)")
                button.clicked.connect(lambda _=False, q=quantity: self.apply(q))
                grid.addWidget(field, row, 2)
                grid.addWidget(button, row, 3)
            if config and quantity.readable:
                note = QLabel()
                note.setStyleSheet(f"color: {theme.ACCENT}")
                note.linkActivated.connect(lambda _, q=quantity: self.take(q))
                note.hide()
                grid.addWidget(note, row, 4)
                self.notes[quantity.key] = note
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.prefill()
        controls = QHBoxLayout()
        self.btnRead = QPushButton(theme.icon("refresh"), "Read")
        self.btnRead.clicked.connect(self.read)
        self.monitor = QCheckBox("Monitor")
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.1, 3600)
        self.interval.setValue(1.0)
        self.interval.setSuffix(" s")
        self.plot = QCheckBox("Plot")
        self.plot.setToolTip("Send the measured values to the P-t, V-t, I-t ... graphs")
        self.plot.toggled.connect(self.plot_toggled)
        self.window = QDoubleSpinBox()
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
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.read)
        self.monitor.toggled.connect(self.set_monitoring)
        self.interval.valueChanged.connect(
            lambda v: self.timer.setInterval(int(v * 1000))
        )

    # Where values are remembered
    def instrument_spec(self):
        station = self.session.station
        return station.config.instruments.get(self.ref) if station else None

    def remembered(self, key: str):
        if self.config:
            spec = self.instrument_spec()
            return spec.settings.get(key) if spec is not None else None
        return settings().value(f"setpoints/{self.ref}/{key}")

    def remember(self, quantity: Quantity, value) -> None:
        if not self.config:
            settings().setValue(f"setpoints/{self.ref}/{quantity.key}", value)
            return
        spec = self.instrument_spec()
        if spec is None or spec.settings.get(quantity.key) == value:
            return
        config = copy.deepcopy(self.session.station.config)
        config.instruments[self.ref].settings[quantity.key] = value
        self.session.update_config(config)

    def prefill(self) -> None:
        for key, field in self.fields.items():
            value = self.remembered(key)
            if value is not None:
                try:
                    field.set_value(float(value) if field.spin else value)
                except (TypeError, ValueError):
                    pass

    # Reading
    def set_monitoring(self, on: bool) -> None:
        if on:
            self.started = time.monotonic()
            self.timer.start(int(self.interval.value() * 1000))
            self.read()
        else:
            self.timer.stop()

    def device(self):
        return self.session.station.device(self.ref)

    def read(self) -> None:
        if self.pending or self.session.station is None:
            return
        self.pending = True
        readable = [q for q in self.quantities if q.readable]
        self.session.worker.submit(
            lambda: read_values(self.device(), readable), self.show_values, self.failed
        )

    def show_values(self, values) -> None:
        self.pending = False
        now = time.monotonic() - self.started
        first = not self.read_once
        self.read_once = True
        for quantity in self.quantities:
            value = values.get(quantity.key)
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
            field = self.fields.get(quantity.key)
            if first and field is not None and not field.pending:
                if self.remembered(quantity.key) is None:
                    field.set_value(value)
            if self.config and value is not None:
                self.compare(quantity, value)
        if self.plot.isChecked():
            self.plot_values(values, now)

    def plot_toggled(self, on: bool) -> None:
        self.raised = not on

    def plot_values(self, values, now: float) -> None:
        window = self.window.value() or None
        for quantity in self.plotted:
            graph = self.hub.monitor_value(
                self.ref, self.title, quantity, now, values.get(quantity.key), window
            )
            if graph is not None and not self.raised:
                # The graph of the first value comes to the front, once
                self.raised = True
                self.hub.raise_graph(graph)

    def compare(self, quantity: Quantity, value) -> None:
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

    def take(self, quantity: Quantity) -> None:
        """Keep the device value: into the field and the profile, nothing is written."""
        value = self.device_values.get(quantity.key)
        if value is None:
            return
        field = self.fields.get(quantity.key)
        if field is not None:
            field.set_value(value)
        self.notes[quantity.key].hide()
        self.remember(quantity, value)

    def failed(self, error) -> None:
        self.pending = False
        self.monitor.setChecked(False)
        for label in self.values.values():
            label.setText("--")
        self.session.worker.error.emit(
            f"{self.title}: {error.__class__.__name__}: {error}"
        )

    # Writing
    def apply(self, quantity: Quantity) -> None:
        field = self.fields.get(quantity.key)
        if field is not None:
            self.write(quantity, field.value())

    def write(self, quantity: Quantity, value) -> None:
        if self.session.station is None:
            return

        def done(_):
            field = self.fields.get(quantity.key)
            if field is not None:
                field.set_pending(False)
            self.remember(quantity, value)
            self.read()

        self.session.worker.submit(
            lambda: quantity.write(self.device(), value), done, self.failed
        )

    def stop(self) -> None:
        self.monitor.setChecked(False)


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)))
    except (TypeError, ValueError):
        return str(a).strip().upper() == str(b).strip().upper()


class ActionsGroup(QGroupBox):
    """Buttons calling device methods in the device thread."""

    def __init__(self, title: str, panel: QuantityPanel, actions, parent=None):
        super().__init__(title, parent)
        layout = QHBoxLayout(self)
        self.panel = panel
        for text, icon_name, call in actions:
            button = QPushButton(theme.icon(icon_name), text)
            button.clicked.connect(lambda _=False, c=call: self.run(c))
            layout.addWidget(button)
        self.result = QLabel()
        self.result.setProperty("role", "value")
        layout.addWidget(self.result, 1)

    def run(self, call) -> None:
        session = self.panel.session
        session.worker.submit(
            lambda: call(self.panel.device()),
            lambda value: self.result.setText("" if value is None else str(value)),
            lambda error: self.result.setText(f"{error}"),
        )


class ChopperGroup(QGroupBox):
    """Hot / Cold and continuous rotation.

    Hot and Cold turn the blade by the sensors until the load is in place
    (aligned to the detent), so no separate rotate or align is needed.
    """

    def __init__(self, panel: QuantityPanel, parent=None):
        super().__init__("Chopper", parent)
        self.panel = panel
        layout = QVBoxLayout(self)
        moves = QHBoxLayout()
        for text, icon_name, call, tip in (
            ("Hot", "fire", lambda d: d.to_hot(), "Turn to the hot load (by the sensors)"),
            ("Cold", "snowflake", lambda d: d.to_cold(), "Turn to the cold load (by the sensors)"),
        ):  # fmt: skip
            button = QPushButton(theme.icon(icon_name), text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, c=call: self.run(c))
            moves.addWidget(button)
        layout.addLayout(moves)
        rotation = QHBoxLayout()
        rotation.addWidget(QLabel("Frequency"))
        self.frequency = QDoubleSpinBox()
        self.frequency.setRange(0.1, 20.0)
        self.frequency.setDecimals(2)
        self.frequency.setSingleStep(0.1)
        self.frequency.setSuffix(" Hz")
        saved = settings().value(f"setpoints/{panel.ref}/chopper_frequency")
        self.frequency.setValue(float(saved) if saved is not None else 10.0)
        self.btnStart = QPushButton(
            theme.icon("rotate-3d-variant"), "Continuous rotation"
        )
        self.btnStart.clicked.connect(self.start)
        self.btnStop = QPushButton(theme.icon("stop"), "Stop")
        self.btnStop.clicked.connect(lambda: self.run(lambda d: d.stop()))
        for widget in (self.frequency, self.btnStart, self.btnStop):
            rotation.addWidget(widget)
        layout.addLayout(rotation)
        self.result = QLabel()
        self.result.setProperty("role", "muted")
        layout.addWidget(self.result)

    def start(self) -> None:
        frequency = self.frequency.value()
        settings().setValue(f"setpoints/{self.panel.ref}/chopper_frequency", frequency)
        self.run(lambda d: d.start_rotation(frequency))

    def run(self, call) -> None:
        self.result.setText("working...")

        def done(_):
            self.result.setText("")
            self.panel.read()

        self.panel.session.worker.submit(
            lambda: call(self.panel.device()),
            done,
            lambda error: self.result.setText(f"{error}"),
        )


class CompressorGroup(QGroupBox):
    def __init__(self, panel: QuantityPanel, parent=None):
        super().__init__("Compressor", parent)
        self.panel = panel
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        for text, icon_name, call in (
            ("Turn on", "power", lambda d: d.turn_on()),
            ("Turn off", "power-off", lambda d: d.turn_off()),
            ("Read", "refresh", None),
        ):
            button = QPushButton(theme.icon(icon_name), text)
            button.clicked.connect(lambda _=False, c=call: self.run(c))
            row.addWidget(button)
        layout.addLayout(row)
        self.text = QLabel("--")
        self.text.setProperty("role", "value")
        layout.addWidget(self.text)

    def run(self, call) -> None:
        def job():
            device = self.panel.device()
            if call is not None:
                call(device)
            return device.read_temperatures(), device.read_pressures()

        def show(values):
            temperatures, pressures = values
            self.text.setText(
                "T: " + ", ".join(f"{t:.1f} K" for t in temperatures)
                + "\np: " + ", ".join(pg.siFormat(p, suffix="Pa") for p in pressures)
            )  # fmt: skip

        self.panel.session.worker.submit(job, show, lambda e: self.text.setText(str(e)))


class TraceGroup(QGroupBox):
    """Spectrum or network analyzer: settings and the last trace."""

    def __init__(self, panel: QuantityPanel, vna: bool, parent=None):
        super().__init__("Network analyzer" if vna else "Spectrum analyzer", parent)
        self.panel = panel
        self.vna = vna
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.start = pg.SpinBox(value=1e9, suffix="Hz", siPrefix=True, dec=True)
        self.stop = pg.SpinBox(value=10e9, suffix="Hz", siPrefix=True, dec=True)
        self.points = QSpinBox()
        self.points.setRange(2, 100001)
        self.points.setValue(401)
        self.parameter = QPlainTextEdit("S11")
        self.parameter.setMaximumHeight(28)
        form.addRow("Start" if vna else "Center", self.start)
        form.addRow("Stop" if vna else "Span", self.stop)
        if vna:
            form.addRow("Points", self.points)
            form.addRow("S-parameter", self.parameter)
        else:
            self.start.setValue(5e9)
            self.stop.setValue(1e9)
        layout.addLayout(form)
        row = QHBoxLayout()
        apply_button = QPushButton(theme.icon("check"), "Apply")
        apply_button.clicked.connect(self.apply)
        read = QPushButton(theme.icon("chart-line"), "Read trace")
        read.clicked.connect(self.read)
        self.continuous = QCheckBox("Continuous")
        self.continuous.toggled.connect(
            lambda on: self.timer.start(500) if on else self.timer.stop()
        )
        row.addWidget(apply_button)
        row.addWidget(read)
        row.addWidget(self.continuous)
        row.addStretch()
        layout.addLayout(row)
        self.graph = pg.PlotWidget()
        self.graph.setLabel("bottom", "Frequency", units="Hz")
        self.graph.setLabel("left", "|S|, dB" if vna else "Power, dBm")
        self.graph.showGrid(x=True, y=True, alpha=0.25)
        self.graph.setMinimumHeight(220)
        self.curve = self.graph.plot([], [], pen=pg.mkPen(theme.ACCENT, width=2))
        layout.addWidget(self.graph)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.read)
        self.pending = False

    def apply(self) -> None:
        start, stop = self.start.value(), self.stop.value()
        points, parameter = self.points.value(), self.parameter.toPlainText().strip()

        def job():
            device = self.panel.device()
            if self.vna:
                device.set_frequency_range(start, stop)
                device.set_points(points)
                device.select_parameter(parameter or "S11")
            else:
                device.set_center_frequency(start)
                device.set_span(stop)

        self.panel.session.worker.submit(job, None, self.panel.failed)

    def read(self) -> None:
        if self.pending:
            return
        self.pending = True
        self.panel.session.worker.submit(
            lambda: self.panel.device().read_trace(), self.show, self.error
        )

    def show(self, trace) -> None:
        self.pending = False
        values = np.asarray(trace.values)
        if np.iscomplexobj(values):
            with np.errstate(divide="ignore"):
                values = 20 * np.log10(np.abs(values))
        self.curve.setData(np.asarray(trace.frequency), values)

    def error(self, error) -> None:
        self.pending = False
        self.continuous.setChecked(False)
        self.panel.failed(error)


class CalibrationDialog(QDialog):
    """SIS block calibration coefficients: expressions allowed ("5.47e-9 / 5")."""

    def __init__(self, coefficients: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SIS calibration coefficients")
        self.resize(520, 520)
        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit(json.dumps(coefficients, indent=2))
        layout.addWidget(self.editor)
        self.problem = QLabel()
        self.problem.setStyleSheet("color: #e57373")
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.check)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.coefficients = coefficients

    def check(self) -> None:
        try:
            data = json.loads(self.editor.toPlainText())
            evaluate_sis_calibration(data)
        except (ValueError, TypeError, KeyError) as e:
            self.problem.setText(str(e))
            return
        self.coefficients = data
        self.accept()


OFFSET_VOLTAGE = Quantity(
    "offset_voltage", "Offset voltage", "V", set=lambda t, v: None
)
OFFSET_CURRENT = Quantity(
    "offset_current", "Offset current", "A", set=lambda t, v: None
)


class SisBiasGroup(QGroupBox):
    """Offsets and calibration of a SIS bias device, kept in the station profile."""

    def __init__(self, panel: QuantityPanel, device_id: str, parent=None):
        super().__init__("SIS bias settings", parent)
        self.panel = panel
        self.device_id = device_id
        layout = QFormLayout(self)
        settings = self.spec().settings
        # Same fields as the rest of the dock: number + prefix (µV, µA)
        self.offset_voltage = QuantityField(OFFSET_VOLTAGE, device_id, "sis_bias")
        self.offset_current = QuantityField(OFFSET_CURRENT, device_id, "sis_bias")
        for field in (self.offset_voltage, self.offset_current):
            field.set_value(settings.get(field.quantity.key, 0.0))
            field.apply_requested.connect(self.save_offsets)
        save = QPushButton(theme.icon("content-save-outline"), "Save offsets")
        save.setToolTip("Keep the offsets in the station profile (or Enter in a field)")
        save.clicked.connect(self.save_offsets)
        layout.addRow("Offset voltage", self.offset_voltage)
        layout.addRow("Offset current", self.offset_current)
        layout.addRow("", save)
        row = QHBoxLayout()
        edit = QPushButton(theme.icon("table-edit"), "Calibration…")
        edit.clicked.connect(self.edit_calibration)
        write = QPushButton(theme.icon("upload"), "Write to block")
        write.clicked.connect(self.write_calibration)
        row.addWidget(edit)
        row.addWidget(write)
        layout.addRow("Calibration", row)

    def spec(self):
        return self.panel.session.station.config.find_device(self.device_id)[1]

    def _update(self, change) -> None:
        session = self.panel.session
        config = copy.deepcopy(session.station.config)
        change(config.find_device(self.device_id)[1])
        session.update_config(config)

    def save_offsets(self) -> None:
        def change(spec):
            spec.settings["offset_voltage"] = float(self.offset_voltage.value())
            spec.settings["offset_current"] = float(self.offset_current.value())

        self._update(change)
        for field in (self.offset_voltage, self.offset_current):
            field.set_pending(False)

    def calibration(self) -> dict:
        spec = self.spec()
        return calibration_for(
            spec.channel, spec.metadata.get("calibration_coefficients")
        )

    def edit_calibration(self) -> None:
        dialog = CalibrationDialog(self.calibration(), self)
        if dialog.exec() == QDialog.Accepted:
            self._update(
                lambda spec: spec.metadata.__setitem__(
                    "calibration_coefficients", dialog.coefficients
                )
            )

    def write_calibration(self) -> None:
        answer = QMessageBox.question(
            self,
            "Write calibration",
            f"Write the calibration of {self.panel.title} to the SIS block EEPROM?",
        )
        if answer != QMessageBox.Yes:
            return
        values = evaluate_sis_calibration(self.calibration())
        self.panel.session.worker.submit(
            lambda: self.panel.device().write_calibration(values),
            lambda answer: QMessageBox.information(
                self, "Calibration", f"Block answered: {answer}"
            ),
            lambda error: QMessageBox.critical(self, "Calibration", str(error)),
        )


def scan_group(session, hub, title: str, procedure: str, fixed) -> QGroupBox:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.addWidget(
        ProcedureBox(session, hub, get_procedure(procedure), fixed, compact=True)
    )
    return box


# Capabilities whose dock has its own group even without quantities
GROUP_CAPABILITIES = (LoadSwitch, Compressor, SpectrumAnalyzer, NetworkAnalyzer)
GROUP_KINDS = ("sis_bias", "sis_coil")


def has_content(station, info) -> bool:
    """Whether the dock of a device would show anything."""
    if station.quantities(info.ref) or info.kind in GROUP_KINDS:
        return True
    if any(c in info.capabilities for c in GROUP_CAPABILITIES):
        return True
    if info.kind == INSTRUMENT:
        cls = station.driver_class(info.ref)
        return any(
            station.quantities(f"{info.ref}:{key}") for key in cls.fixed_channels()
        )
    return False


class DeviceWidget(QScrollArea):
    """Dock content of an instrument (with its fixed channels) or a device."""

    def __init__(self, session, hub, ref: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.ref = ref
        self.panels: List[QuantityPanel] = []
        self.setWidgetResizable(True)
        station = session.station
        info = station.info(ref)
        self.info = info
        inner = QWidget()
        layout = QVBoxLayout(inner)
        title = QLabel(info.title)
        title.setProperty("role", "title")
        layout.addWidget(title)
        spec = station.config.instruments[info.instrument]
        subtitle = QLabel(
            f"{spec.driver} · {info.ref}"
            + ("" if info.kind == INSTRUMENT else f" · {info.kind}")
        )
        subtitle.setProperty("role", "muted")
        layout.addWidget(subtitle)
        main = QuantityPanel(session, hub, ref, info.title, info.kind)
        if main.quantities:
            layout.addWidget(self._boxed("Values", main))
        self.panels.append(main)
        if info.kind == INSTRUMENT:
            # Multiplier, OEM head: kept in the profile, compared with the device
            config = QuantityPanel(
                session, hub, ref, info.title, info.kind, config=True
            )
            if config.quantities:
                layout.addWidget(self._boxed("Configuration", config))
                self.panels.append(config)
            cls = station.driver_class(ref)
            for key in cls.fixed_channels():
                channel_ref = f"{ref}:{key}"
                panel = QuantityPanel(
                    session, hub, channel_ref, channel_title(info.title, key), "channel"
                )
                self.panels.append(panel)
                layout.addWidget(
                    self._boxed(channel_title("", key).strip() or str(key), panel)
                )
        for group in self.extra_groups(main):
            layout.addWidget(group)
        layout.addStretch()
        self.setWidget(inner)

    @staticmethod
    def _boxed(title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        QVBoxLayout(box).addWidget(widget)
        return box

    def extra_groups(self, panel: QuantityPanel):
        info, session, hub = self.info, self.session, self.hub
        caps = info.capabilities
        groups = []
        driver = self.session.station.driver_class(info.instrument)
        if LoadSwitch in caps and hasattr(driver, "start_rotation"):
            groups.append(ChopperGroup(panel))
        elif LoadSwitch in caps:
            groups.append(ActionsGroup("Calibration load", panel, (
                ("Hot", "fire", lambda d: d.to_hot()),
                ("Cold", "snowflake", lambda d: d.to_cold()),
            )))  # fmt: skip
        if Compressor in caps:
            groups.append(CompressorGroup(panel))
        if SpectrumAnalyzer in caps:
            groups.append(TraceGroup(panel, vna=False))
        if NetworkAnalyzer in caps:
            groups.append(TraceGroup(panel, vna=True))
        if info.kind == "sis_bias":
            groups.append(SisBiasGroup(panel, info.ref))
            groups.append(
                scan_group(session, hub, "I-V scan", "sis.iv_curve", {"bias": info.ref})
            )
        if info.kind == "sis_coil":
            groups.append(
                scan_group(
                    session, hub, "I-CL scan", "sis.cl_curve", {"coil": info.ref}
                )
            )
            groups.append(
                scan_group(
                    session,
                    hub,
                    "Demagnetization",
                    "sis.demagnetize",
                    {"coil": info.ref},
                )
            )
        return groups

    def stop(self) -> None:
        for panel in self.panels:
            panel.stop()


def device_widget(session, hub, ref: str) -> Optional[DeviceWidget]:
    return DeviceWidget(session, hub, ref)
