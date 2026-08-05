from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from utils.iv_analysis import (
    IVAnalysisConfig,
    IVAnalysisParameters,
    IVGapConfig,
)


class IVAnalysisParametersDialog(QDialog):
    def __init__(
        self,
        parent,
        parameters: IVAnalysisParameters,
    ):
        super().__init__(parent)
        self._parameters = parameters
        self.setWindowTitle("I-V analysis parameters")
        self.setMinimumWidth(360)

        self.rnMinVoltage = self._voltage_spinbox()
        self.rnMaxVoltage = self._voltage_spinbox()
        self.rnMaxVoltage.setSpecialValueText("Auto")
        self.rjMinVoltage = self._voltage_spinbox()
        self.rjMaxVoltage = self._voltage_spinbox()
        self.gapMinVoltage = self._voltage_spinbox()
        self.gapMaxVoltage = self._voltage_spinbox()

        self.gapSlopeFactor = QDoubleSpinBox(self)
        self.gapSlopeFactor.setRange(1.01, 20.0)
        self.gapSlopeFactor.setDecimals(2)
        self.gapSlopeFactor.setSingleStep(0.1)

        self.smoothingWindow = QSpinBox(self)
        self.smoothingWindow.setRange(3, 999)
        self.smoothingWindow.setSingleStep(2)
        self.smoothingWindow.setToolTip("Odd Savitzky-Golay window length")

        self.smoothingDegree = QSpinBox(self)
        self.smoothingDegree.setRange(1, 20)

        self.interpolationPoints = QSpinBox(self)
        self.interpolationPoints.setRange(101, 10001)
        self.interpolationPoints.setSingleStep(100)

        form = QFormLayout()
        form.addRow(QLabel("Rn fit from, mV"), self.rnMinVoltage)
        form.addRow(QLabel("Rn fit to, mV"), self.rnMaxVoltage)
        form.addRow(QLabel("Rj search from, mV"), self.rjMinVoltage)
        form.addRow(QLabel("Rj search to, mV"), self.rjMaxVoltage)
        form.addRow(QLabel("Gap search from, mV"), self.gapMinVoltage)
        form.addRow(QLabel("Gap search to, mV"), self.gapMaxVoltage)
        form.addRow(QLabel("Fallback slope factor"), self.gapSlopeFactor)
        form.addRow(QLabel("Savitzky-Golay window"), self.smoothingWindow)
        form.addRow(QLabel("Savitzky-Golay degree"), self.smoothingDegree)
        form.addRow(QLabel("Interpolation points"), self.interpolationPoints)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            parent=self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self._restore_defaults)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self._set_values(parameters)

    @property
    def parameters(self) -> IVAnalysisParameters:
        return self._parameters

    def accept(self):
        try:
            self._parameters = self._read_values()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid analysis parameters", str(error))
            return
        super().accept()

    def _read_values(self) -> IVAnalysisParameters:
        rn_max = self.rnMaxVoltage.value()
        return IVAnalysisParameters(
            resistance=IVAnalysisConfig(
                rn_min_voltage_mv=self.rnMinVoltage.value(),
                rn_max_voltage_mv=None if rn_max == 0.0 else rn_max,
                rj_min_voltage_mv=self.rjMinVoltage.value(),
                rj_max_voltage_mv=self.rjMaxVoltage.value(),
            ),
            gap=IVGapConfig(
                gap_min_voltage_mv=self.gapMinVoltage.value(),
                gap_max_voltage_mv=self.gapMaxVoltage.value(),
                gap_slope_factor=self.gapSlopeFactor.value(),
                smoothing_window=self.smoothingWindow.value(),
                smoothing_degree=self.smoothingDegree.value(),
                interpolation_points=self.interpolationPoints.value(),
            ),
        )

    def _set_values(self, parameters: IVAnalysisParameters):
        resistance = parameters.resistance
        gap = parameters.gap
        self.rnMinVoltage.setValue(resistance.rn_min_voltage_mv)
        self.rnMaxVoltage.setValue(resistance.rn_max_voltage_mv or 0.0)
        self.rjMinVoltage.setValue(resistance.rj_min_voltage_mv)
        self.rjMaxVoltage.setValue(resistance.rj_max_voltage_mv)
        self.gapMinVoltage.setValue(gap.gap_min_voltage_mv)
        self.gapMaxVoltage.setValue(gap.gap_max_voltage_mv)
        self.gapSlopeFactor.setValue(gap.gap_slope_factor)
        self.smoothingWindow.setValue(gap.smoothing_window)
        self.smoothingDegree.setValue(gap.smoothing_degree)
        self.interpolationPoints.setValue(gap.interpolation_points)

    def _restore_defaults(self):
        self._set_values(IVAnalysisParameters())

    def _voltage_spinbox(self) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox(self)
        spinbox.setRange(0.0, 100.0)
        spinbox.setDecimals(3)
        spinbox.setSingleStep(0.1)
        return spinbox
