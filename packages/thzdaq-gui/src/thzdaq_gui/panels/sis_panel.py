"""SIS block tools: calibration coefficients and magnet demagnetization."""

import json
from dataclasses import replace

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.measurements.procedures import Demagnetize
from thzdaq_core.sis import (
    calibration_for,
    default_sis_calibration,
    evaluate_sis_calibration,
    normalize_sis_calibration,
)
from thzdaq_core.station.storage import save_station
from thzdaq_instruments.units import MA


def _ma_spin(value: float, low: float = -100, high: float = 100) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(low, high)
    spin.setDecimals(2)
    spin.setSuffix(" mA")
    spin.setValue(value)
    return spin


class SisPanel(QWidget):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)

        calibration = QGroupBox("Calibration coefficients")
        cal = QVBoxLayout(calibration)
        row = QHBoxLayout()
        self.biasRole = QComboBox()
        self.biasRole.currentTextChanged.connect(self.load_calibration)
        row.addWidget(QLabel("Bias role"))
        row.addWidget(self.biasRole, 1)
        cal.addLayout(row)
        cal.addWidget(
            QLabel(
                'Numbers or quoted expressions like "5.476e-9 / 5" '
                "(+ - * / ** and parentheses)."
            )
        )
        self.editor = QPlainTextEdit()
        self.editor.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        cal.addWidget(self.editor)
        buttons = QHBoxLayout()
        self.btnDefaults = QPushButton("Defaults")
        self.btnDefaults.clicked.connect(self.restore_defaults)
        self.btnSaveProfile = QPushButton("Save to profile")
        self.btnSaveProfile.clicked.connect(self.save_to_profile)
        self.btnWrite = QPushButton("Write to block")
        self.btnWrite.clicked.connect(self.write_to_block)
        for button in (self.btnDefaults, self.btnSaveProfile, self.btnWrite):
            buttons.addWidget(button)
        cal.addLayout(buttons)
        self.calStatus = QLabel()
        self.calStatus.setWordWrap(True)
        cal.addWidget(self.calStatus)
        layout.addWidget(calibration, 2)

        demag = QGroupBox("Demagnetization")
        form = QFormLayout(demag)
        self.coilRole = QComboBox()
        self.minimum = _ma_spin(-30)
        self.maximum = _ma_spin(30)
        self.step = _ma_spin(5, 0.01, 50)
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0, 10)
        self.delay.setValue(0.05)
        self.delay.setSuffix(" s")
        form.addRow("Coil role", self.coilRole)
        form.addRow("Minimum", self.minimum)
        form.addRow("Maximum", self.maximum)
        form.addRow("Step", self.step)
        form.addRow("Step delay", self.delay)
        self.demagProgress = QProgressBar()
        form.addRow(self.demagProgress)
        row = QHBoxLayout()
        self.btnDemag = QPushButton("Demagnetize")
        self.btnDemag.clicked.connect(self.demagnetize)
        self.btnDemagStop = QPushButton("Stop")
        self.btnDemagStop.clicked.connect(session.runner.cancel)
        row.addWidget(self.btnDemag)
        row.addWidget(self.btnDemagStop)
        form.addRow(row)
        layout.addWidget(demag)

        self._demag_running = False
        session.station_changed.connect(self.show_station)
        session.runner.running_changed.connect(self.on_running)
        session.runner.progress.connect(self.on_progress)
        self.show_station(session.station)

    # Station
    def show_station(self, station) -> None:
        roles = list(station.config.roles) if station is not None else []
        for combo, hint in ((self.biasRole, "sis"), (self.coilRole, "ctrl")):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(roles)
            preferred = (
                current
                if current in roles
                else next((r for r in roles if hint in r), "")
            )
            combo.setCurrentText(preferred)
            combo.blockSignals(False)
        self.load_calibration()
        self.on_running(self.session.runner.running)

    def role_config(self, role: str):
        station = self.session.station
        if station is None or role not in station.config.roles:
            return None
        return station.config.roles[role]

    # Calibration
    def load_calibration(self) -> None:
        spec = self.role_config(self.biasRole.currentText())
        if spec is None:
            self.editor.setPlainText("")
            return
        try:
            coefficients = calibration_for(
                str(spec.channel), spec.metadata.get("calibration_coefficients")
            )
            origin = (
                "profile"
                if spec.metadata.get("calibration_coefficients")
                else "defaults"
            )
        except ValueError as e:
            coefficients, origin = (
                spec.metadata.get("calibration_coefficients"),
                f"invalid: {e}",
            )
        self.editor.setPlainText(json.dumps(coefficients, ensure_ascii=False, indent=4))
        self.calStatus.setText(f"Loaded from {origin}")

    def edited(self) -> dict:
        return normalize_sis_calibration(json.loads(self.editor.toPlainText()))

    def restore_defaults(self) -> None:
        spec = self.role_config(self.biasRole.currentText())
        if spec is not None:
            defaults = default_sis_calibration(str(spec.channel))
            self.editor.setPlainText(json.dumps(defaults, ensure_ascii=False, indent=4))
            self.calStatus.setText("Defaults (not saved)")

    def save_to_profile(self) -> None:
        role = self.biasRole.currentText()
        spec = self.role_config(role)
        if spec is None:
            return
        try:
            coefficients = self.edited()
        except ValueError as e:  # JSONDecodeError is a ValueError
            QMessageBox.warning(self, "Calibration coefficients", str(e))
            return
        config = self.session.station.config
        roles = dict(config.roles)
        roles[role] = replace(
            spec, metadata={**spec.metadata, "calibration_coefficients": coefficients}
        )
        save_station(replace(config, roles=roles), self.session.path)
        self.session.reload()
        self.calStatus.setText(f"Saved to {self.session.path}")

    def write_to_block(self) -> None:
        role = self.biasRole.currentText()
        station = self.session.station
        if station is None or not role:
            return
        try:
            evaluated = evaluate_sis_calibration(self.edited())
        except ValueError as e:
            QMessageBox.warning(self, "Calibration coefficients", str(e))
            return
        answer = QMessageBox.question(
            self,
            "Write calibration",
            f"Write the coefficients to the EEPROM of '{role}'?",
        )
        if answer != QMessageBox.Yes:
            return
        self.calStatus.setText("Writing…")

        def job():
            port = station.role(role)
            if not hasattr(port, "write_calibration"):
                raise TypeError(f"{role} is not a SIS bias channel")
            return port.write_calibration(evaluated)

        self.session.worker.submit(
            job,
            lambda answer: self.calStatus.setText(
                f"Written, block answered {answer!r}"
            ),
            lambda error: self.calStatus.setText(f"Write failed: {error}"),
        )

    # Demagnetization
    def demagnetize(self) -> None:
        if self.session.station is None or not self.coilRole.currentText():
            return
        procedure = Demagnetize(
            minimum=self.minimum.value() * MA,
            maximum=self.maximum.value() * MA,
            step=self.step.value() * MA,
            step_delay=self.delay.value(),
        )
        try:
            procedure.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Demagnetization", str(e))
            return
        self._demag_running = True
        self.demagProgress.setRange(0, procedure.estimate_steps())
        self.session.runner.start(
            self.session.station,
            self.session.store,
            procedure,
            {"coil": self.coilRole.currentText()},
            "demagnetization",
        )

    def on_running(self, running: bool) -> None:
        if not running:
            self._demag_running = False
        has_station = self.session.station is not None
        self.btnDemag.setEnabled(has_station and not running)
        self.btnDemagStop.setEnabled(running and self._demag_running)
        self.btnWrite.setEnabled(has_station and not running)

    def on_progress(self, done: int, total) -> None:
        if self._demag_running:
            self.demagProgress.setValue(done)
