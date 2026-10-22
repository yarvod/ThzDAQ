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
from thzdaq_gui.graphs import SI_UNITS

PREFIXED = SI_UNITS


def format_value(value, quantity: Quantity) -> str:
    if value is None:
        return "--"
    if quantity.kind == "bool":
        return "ON" if value else "OFF"
    if isinstance(value, (int, float)):
        if quantity.unit in PREFIXED:
            return pg.siFormat(float(value), precision=5, suffix=quantity.unit)
        return f"{value:.5g} {quantity.unit}".strip()
    return str(value)


def make_spin(quantity: Quantity) -> pg.SpinBox:
    spin = pg.SpinBox(
        value=0.0,
        suffix=quantity.unit,
        siPrefix=quantity.unit in PREFIXED,
        dec=True,
        decimals=6,
        compactHeight=False,
    )
    if quantity.minimum is not None or quantity.maximum is not None:
        spin.setOpts(bounds=(quantity.minimum, quantity.maximum))
    spin.setMinimumWidth(110)
    return spin


class QuantityPanel(QWidget):
    """Read and set the quantities of one device; optional polling and plotting."""

    def __init__(self, session, hub, ref: str, title: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.ref = ref
        self.title = title
        self.quantities: List[Quantity] = session.station.quantities(ref)
        self.values: Dict[str, QLabel] = {}
        self.toggles: Dict[str, QPushButton] = {}
        self.pending = False
        self.started = time.monotonic()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        for row, quantity in enumerate(self.quantities):
            name = QLabel(quantity.title)
            grid.addWidget(name, row, 0)
            if quantity.readable:
                value = QLabel("--")
                value.setProperty("role", "value")
                grid.addWidget(value, row, 1)
                self.values[quantity.key] = value
            if quantity.settable and quantity.kind == "bool":
                toggle = QPushButton("Off")
                toggle.setCheckable(True)
                toggle.clicked.connect(lambda on, q=quantity: self.write(q, on))
                grid.addWidget(toggle, row, 2, 1, 2)
                self.toggles[quantity.key] = toggle
            elif quantity.settable:
                spin = make_spin(quantity)
                button = QPushButton(theme.icon("check"), "Set")
                button.clicked.connect(
                    lambda _=False, q=quantity, s=spin: self.write(q, s.value())
                )
                spin.editingFinished.connect(lambda q=quantity, s=spin: self.write(q, s.value()))
                grid.addWidget(spin, row, 2)
                grid.addWidget(button, row, 3)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        controls = QHBoxLayout()
        self.btnRead = QPushButton(theme.icon("refresh"), "Read")
        self.btnRead.clicked.connect(self.read)
        self.monitor = QCheckBox("Monitor")
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.1, 3600)
        self.interval.setValue(1.0)
        self.interval.setSuffix(" s")
        self.plot = QCheckBox("Plot")
        self.plot.setToolTip("Send the monitored values to the P-t, V-t, I-t ... graphs")
        controls.addWidget(self.btnRead)
        controls.addWidget(self.monitor)
        controls.addWidget(self.interval)
        controls.addWidget(self.plot)
        controls.addStretch()
        readable = any(q.readable for q in self.quantities)
        for widget in (self.btnRead, self.monitor, self.interval, self.plot):
            widget.setVisible(readable)
        layout.addLayout(controls)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.read)
        self.monitor.toggled.connect(self.set_monitoring)
        self.interval.valueChanged.connect(
            lambda v: self.timer.setInterval(int(v * 1000))
        )

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
        for quantity in self.quantities:
            value = values.get(quantity.key)
            if quantity.key in self.values:
                self.values[quantity.key].setText(format_value(value, quantity))
            toggle = self.toggles.get(quantity.key)
            if toggle is not None and value is not None:
                toggle.setChecked(bool(value))
                toggle.setText("On" if value else "Off")
            if self.plot.isChecked() and isinstance(value, (int, float)):
                self.hub.monitor_value(self.ref, self.title, quantity.key, now, value)

    def failed(self, error) -> None:
        self.pending = False
        self.monitor.setChecked(False)
        for label in self.values.values():
            label.setText("--")
        self.session.worker.error.emit(
            f"{self.title}: {error.__class__.__name__}: {error}"
        )

    def write(self, quantity: Quantity, value) -> None:
        if self.session.station is None:
            return
        self.session.worker.submit(
            lambda: quantity.write(self.device(), value),
            lambda _: self.read(),
            self.failed,
        )

    def stop(self) -> None:
        self.monitor.setChecked(False)


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
        self.continuous.toggled.connect(lambda on: self.timer.start(500) if on else self.timer.stop())
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


class SisBiasGroup(QGroupBox):
    """Offsets and calibration of a SIS bias device, kept in the station profile."""

    def __init__(self, panel: QuantityPanel, device_id: str, parent=None):
        super().__init__("SIS bias settings", parent)
        self.panel = panel
        self.device_id = device_id
        layout = QFormLayout(self)
        settings = self.spec().settings
        self.offset_voltage = pg.SpinBox(
            value=settings.get("offset_voltage", 0.0), suffix="V", siPrefix=True, dec=True
        )
        self.offset_current = pg.SpinBox(
            value=settings.get("offset_current", 0.0), suffix="A", siPrefix=True, dec=True
        )
        save = QPushButton(theme.icon("content-save-outline"), "Save offsets")
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

    def calibration(self) -> dict:
        spec = self.spec()
        return calibration_for(spec.channel, spec.metadata.get("calibration_coefficients"))

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
            lambda answer: QMessageBox.information(self, "Calibration", f"Block answered: {answer}"),
            lambda error: QMessageBox.critical(self, "Calibration", str(error)),
        )


def scan_group(session, hub, title: str, procedure: str, fixed) -> QGroupBox:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.addWidget(ProcedureBox(session, hub, get_procedure(procedure), fixed, compact=True))
    return box


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
            f"{spec.driver} · {info.ref}" + ("" if info.kind == INSTRUMENT else f" · {info.kind}")
        )
        subtitle.setProperty("role", "muted")
        layout.addWidget(subtitle)
        main = QuantityPanel(session, hub, ref, info.title)
        if main.quantities:
            layout.addWidget(self._boxed("Values", main))
        self.panels.append(main)
        if info.kind == INSTRUMENT:
            cls = station.driver_class(ref)
            for key in cls.fixed_channels():
                channel_ref = f"{ref}:{key}"
                panel = QuantityPanel(session, hub, channel_ref, channel_title(info.title, key))
                self.panels.append(panel)
                layout.addWidget(self._boxed(channel_title("", key).strip() or str(key), panel))
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
        if LoadSwitch in caps:
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
            groups.append(scan_group(session, hub, "I-V scan", "sis.iv_curve", {"bias": info.ref}))
        if info.kind == "sis_coil":
            groups.append(scan_group(session, hub, "I-CL scan", "sis.cl_curve", {"coil": info.ref}))
            groups.append(
                scan_group(session, hub, "Demagnetization", "sis.demagnetize", {"coil": info.ref})
            )
        return groups

    def stop(self) -> None:
        for panel in self.panels:
            panel.stop()


def device_widget(session, hub, ref: str) -> Optional[DeviceWidget]:
    return DeviceWidget(session, hub, ref)

