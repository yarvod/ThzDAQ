"""Manual control of any role, built from its capabilities (no per-vendor widgets).

Every instrument call goes through the device worker; while a measurement runs,
controls are read-only.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.station.ports import SidebandSwitch
from thzdaq_instruments.capabilities import (
    Compressor,
    CurrentSource,
    FrequencySource,
    LoadSwitch,
    PowerDetector,
    PowerLevel,
    Rotator,
    Switchable,
    Thermometer,
    TunableFilter,
    VacuumGauge,
    VoltageCurrentMeter,
    VoltageSource,
)
from thzdaq_instruments.units import GHZ, MA, MV, UA, kelvin_to_celsius

Reading = Dict[str, Any]


def _spin(suffix: str, decimals: int, low: float, high: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(decimals)
    spin.setRange(low, high)
    spin.setSuffix(f" {suffix}")
    spin.setKeyboardTracking(False)
    return spin


class Section(QGroupBox):
    """Controls of one capability. read() runs in the worker, show() in the GUI."""

    def __init__(self, title: str, panel: "RoleControl"):
        super().__init__(title)
        self.panel = panel
        self.form = QFormLayout(self)
        self.writers: List[QWidget] = []

    def call(
        self, job: Callable[[], Any], then: Optional[Callable[[Any], None]] = None
    ):
        self.panel.call(job, then)

    def read(self, port) -> Reading:
        return {}

    def show(self, reading: Reading) -> None:
        ...

    def set_writable(self, writable: bool) -> None:
        for widget in self.writers:
            widget.setEnabled(writable)


class SwitchSection(Section):
    def __init__(self, panel, port):
        super().__init__("Output", panel)
        self.check = QCheckBox("On")
        self.check.clicked.connect(
            lambda value: self.call(lambda: port.set_output(value))
        )
        self.form.addRow(self.check)
        self.writers.append(self.check)

    def read(self, port):
        return {"output": port.get_output()}

    def show(self, reading):
        self.check.setChecked(bool(reading["output"]))


class SetpointSection(Section):
    """A settable quantity with a readback of the setpoint."""

    def __init__(self, panel, title, unit, scale, decimals, low, high, setter, getter):
        super().__init__(title, panel)
        self.scale, self.getter = scale, getter
        self.spin = _spin(unit, decimals, low, high)
        button = QPushButton("Set")
        button.clicked.connect(
            lambda: self.call(lambda value=self.spin.value() * scale: setter(value))
        )
        row = QHBoxLayout()
        row.addWidget(self.spin)
        row.addWidget(button)
        self.form.addRow(row)
        self.writers += [self.spin, button]

    def read(self, port):
        return {"value": self.getter()}

    def show(self, reading):
        if not self.spin.hasFocus():
            self.spin.setValue(reading["value"] / self.scale)


class ReadoutSection(Section):
    def __init__(
        self, panel, title, fields: List[Tuple[str, str, Callable[[Any], str]]], reader
    ):
        super().__init__(title, panel)
        self.reader = reader
        self.labels = {}
        for key, label, _ in fields:
            self.labels[key] = QLabel("—")
            self.form.addRow(label, self.labels[key])
        self.formatters = {key: fmt for key, _, fmt in fields}

    def read(self, port):
        return self.reader()

    def show(self, reading):
        for key, value in reading.items():
            if key in self.labels:
                self.labels[key].setText(self.formatters[key](value))


class ButtonsSection(Section):
    def __init__(
        self,
        panel,
        title,
        actions: List[Tuple[str, Callable[[], Any]]],
        reader=None,
        fmt=str,
    ):
        super().__init__(title, panel)
        self.reader, self.fmt = reader, fmt
        row = QHBoxLayout()
        for text, action in actions:
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, action=action: self.call(action))
            row.addWidget(button)
            self.writers.append(button)
        self.form.addRow(row)
        self.state = QLabel("—")
        if reader is not None:
            self.form.addRow("State", self.state)

    def read(self, port):
        return {"state": self.reader()} if self.reader else {}

    def show(self, reading):
        if "state" in reading:
            self.state.setText(self.fmt(reading["state"]))


def build_sections(panel: "RoleControl", port) -> List[Section]:
    """Sections for every capability of the port; SIS-like ports (no output switch) use mV/μA."""
    sections: List[Section] = []
    supply_like = isinstance(port, Switchable)
    if isinstance(port, Switchable) and not isinstance(port, SidebandSwitch):
        sections.append(SwitchSection(panel, port))
    if isinstance(port, VoltageSource):
        unit, scale, decimals, limit = (
            ("V", 1.0, 3, 100.0) if supply_like else ("mV", MV, 4, 30.0)
        )
        sections.append(
            SetpointSection(panel, "Voltage", unit, scale, decimals, -limit, limit,
                            port.set_voltage, port.get_voltage)  # fmt: skip
        )
    if isinstance(port, CurrentSource):
        unit, scale, decimals, limit = (
            ("A", 1.0, 4, 20.0) if supply_like else ("mA", MA, 4, 100.0)
        )
        sections.append(
            SetpointSection(panel, "Current", unit, scale, decimals, -limit, limit,
                            port.set_current, port.get_current)  # fmt: skip
        )
    if isinstance(port, VoltageCurrentMeter):
        v_scale, v_unit = (1.0, "V") if supply_like else (MV, "mV")
        i_scale, i_unit = (1.0, "A") if supply_like else (UA, "μA")

        def measure():
            reading = port.measure()
            return {"voltage": reading.voltage, "current": reading.current}

        sections.append(
            ReadoutSection(panel, "Measured", [
                ("voltage", "Voltage", lambda v: f"{v / v_scale:.4f} {v_unit}"),
                ("current", "Current", lambda v: f"{v / i_scale:.4f} {i_unit}"),
            ], measure)  # fmt: skip
        )
    if isinstance(port, FrequencySource):
        sections.append(
            SetpointSection(panel, "Frequency", "GHz", GHZ, 6, 0, 2000,
                            port.set_frequency, port.get_frequency)  # fmt: skip
        )
    if isinstance(port, PowerLevel):
        sections.append(
            SetpointSection(
                panel, "Power", "dBm", 1.0, 2, -140, 30, port.set_power, port.get_power
            )
        )
    if isinstance(port, PowerDetector):
        sections.append(
            ReadoutSection(panel, "Power meter",
                           [("power", "Power", lambda v: f"{v:.3f} dBm")],
                           lambda: {"power": port.read_power()})  # fmt: skip
        )
    if isinstance(port, Thermometer):
        sections.append(
            ReadoutSection(panel, "Temperature",
                           [("temperature", "T", lambda v: f"{v:.3f} K")],
                           lambda: {"temperature": port.read_temperature()})  # fmt: skip
        )
    if isinstance(port, VacuumGauge):
        sections.append(
            ReadoutSection(panel, "Vacuum", [("pressure", "Pressure", lambda v: f"{v:.3e} Pa")],
                           lambda: {"pressure": port.read_pressure()})  # fmt: skip
        )
    if isinstance(port, TunableFilter):
        sections.append(TuneSection(panel, port))
    if isinstance(port, LoadSwitch):
        sections.append(
            ButtonsSection(
                panel, "Load", [("Hot", port.to_hot), ("Cold", port.to_cold)]
            )
        )
    if isinstance(port, SidebandSwitch):
        sections.append(
            ButtonsSection(
                panel, "IF channel",
                [("Upper", lambda: port.select("upper")), ("Lower", lambda: port.select("lower"))],
                reader=port.selected,
            )  # fmt: skip
        )
    if isinstance(port, Rotator):
        sections.append(
            SetpointSection(
                panel, "Angle", "deg", 1.0, 2, -720, 720, port.rotate_to, port.get_angle
            )
        )
    if isinstance(port, Compressor):
        sections.append(
            ButtonsSection(
                panel, "Compressor", [("On", port.turn_on), ("Off", port.turn_off)],
                reader=port.read_temperatures,
                fmt=lambda temps: ", ".join(f"{kelvin_to_celsius(t):.1f} °C" for t in temps),
            )  # fmt: skip
        )
    return sections


class TuneSection(Section):
    def __init__(self, panel, port):
        super().__init__("Filter", panel)
        self.spin = _spin("GHz", 4, 0, 100)
        self.actual = QLabel("—")
        button = QPushButton("Tune")
        button.clicked.connect(
            lambda: self.call(
                lambda value=self.spin.value() * GHZ: port.tune(value),
                lambda actual: self.actual.setText(f"{actual / GHZ:.4f} GHz"),
            )
        )
        row = QHBoxLayout()
        row.addWidget(self.spin)
        row.addWidget(button)
        self.form.addRow(row)
        self.form.addRow("Tuned", self.actual)
        self.writers += [self.spin, button]


class RoleControl(QWidget):
    def __init__(self, session, role: str, port, parent=None):
        super().__init__(parent)
        self.session, self.role, self.port = session, role, port
        layout = QVBoxLayout(self)
        self.sections = build_sections(self, port)
        for section in self.sections:
            layout.addWidget(section)
        if not self.sections:
            layout.addWidget(QLabel("No controllable capabilities"))
        layout.addStretch()
        self.set_writable(not session.runner.running)

    def call(self, job, then=None):
        def after(result):
            if then is not None:
                then(result)
            self.refresh()

        self.session.worker.submit(job, after)

    def refresh(self) -> None:
        sections, port = self.sections, self.port

        def job():
            return [section.read(port) for section in sections]

        def show(readings):
            for section, reading in zip(sections, readings):
                if reading:
                    section.show(reading)

        self.session.worker.submit(job, show)

    def set_writable(self, writable: bool) -> None:
        for section in self.sections:
            section.set_writable(writable)


class ControlPanel(QWidget):
    """Pick a role, get controls for what it can do, optionally poll readings."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.roleCombo = QComboBox()
        self.btnOpen = QPushButton("Open")
        self.btnOpen.clicked.connect(self.open_role)
        top.addWidget(self.roleCombo, 1)
        top.addWidget(self.btnOpen)
        layout.addLayout(top)
        poll = QHBoxLayout()
        self.poll = QCheckBox("Poll every")
        self.interval = QSpinBox()
        self.interval.setRange(100, 60000)
        self.interval.setValue(1000)
        self.interval.setSuffix(" ms")
        poll.addWidget(self.poll)
        poll.addWidget(self.interval)
        poll.addStretch()
        layout.addLayout(poll)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)

        self.control: Optional[RoleControl] = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_once)
        self.poll.toggled.connect(self.toggle_poll)
        self.interval.valueChanged.connect(self.timer.setInterval)
        session.station_changed.connect(self.show_station)
        session.runner.running_changed.connect(self.on_running)
        self.show_station(session.station)

    def show_station(self, station) -> None:
        self.roleCombo.clear()
        self.scroll.takeWidget()
        self.control = None
        if station is not None:
            self.roleCombo.addItems(list(station.config.roles))
        self.btnOpen.setEnabled(station is not None)

    def open_role(self) -> None:
        station, role = self.session.station, self.roleCombo.currentText()
        if station is None or not role:
            return
        self.status.setText(f"Opening {role}…")

        def done(port):
            self.status.setText(f"{role}: {port!r}")
            self.control = RoleControl(self.session, role, port)
            self.scroll.setWidget(self.control)
            self.control.refresh()

        def failed(error):
            self.status.setText(f"{role}: {error}")

        self.session.worker.submit(lambda: station.role(role), done, failed)

    def toggle_poll(self, enabled: bool) -> None:
        if enabled:
            self.timer.start(self.interval.value())
        else:
            self.timer.stop()

    def poll_once(self) -> None:
        # Skip a tick rather than piling up jobs behind a slow instrument
        if self.control is not None and self.session.worker.pending == 0:
            self.control.refresh()

    def on_running(self, running: bool) -> None:
        if self.control is not None:
            self.control.set_writable(not running)
