"""I-V analysis on a plotted curve: Rn fit, Rj tangent, Q and the gap."""

import json
from dataclasses import asdict
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.analysis.iv import (
    IVAnalysisConfig,
    IVAnalysisParameters,
    IVGapConfig,
    IVResistanceAnalysis,
    NumpyIVAnalyzerFactory,
)

SETTINGS = ("ThzDAQ", "thzdaq-gui")


def format_result(result: IVResistanceAnalysis) -> str:
    gap = result.gap
    gap_text = (
        f"<b>Vgap</b> {gap.voltage_mv:.3f} mV &nbsp; <b>Igap</b> {gap.current_step_ua:.3f} µA"
        if gap is not None
        else "<b>Vgap</b> n/a"
    )
    return (
        f"<b>Rn</b> {result.rn_ohm:.2f} Ω &nbsp; <b>Rj</b> {result.rj_ohm:.2f} Ω &nbsp; "
        f"<b>Rj/Rn</b> {result.q:.4g} &nbsp; {gap_text}"
    )


def load_parameters() -> IVAnalysisParameters:
    raw = QSettings(*SETTINGS).value("iv_analysis")
    if not raw:
        return IVAnalysisParameters()
    try:
        data = json.loads(raw)
        return IVAnalysisParameters(
            resistance=IVAnalysisConfig(**data["resistance"]),
            gap=IVGapConfig(**data["gap"]),
        )
    except (ValueError, KeyError, TypeError):
        return IVAnalysisParameters()


def save_parameters(parameters: IVAnalysisParameters) -> None:
    QSettings(*SETTINGS).setValue("iv_analysis", json.dumps(asdict(parameters)))


class ParametersDialog(QDialog):
    def __init__(self, parameters: IVAnalysisParameters, parent=None):
        super().__init__(parent)
        self.setWindowTitle("I-V analysis parameters")
        form = QFormLayout()

        def voltage(value, special=False):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 30.0)
            spin.setDecimals(3)
            spin.setSuffix(" mV")
            if special:
                spin.setSpecialValueText("Auto")
            spin.setValue(0.0 if value is None else value)
            return spin

        r, g = parameters.resistance, parameters.gap
        self.rn_min = voltage(r.rn_min_voltage_mv)
        self.rn_max = voltage(r.rn_max_voltage_mv, special=True)
        self.rj_min = voltage(r.rj_min_voltage_mv)
        self.rj_max = voltage(r.rj_max_voltage_mv)
        self.gap_min = voltage(g.gap_min_voltage_mv)
        self.gap_max = voltage(g.gap_max_voltage_mv)
        self.slope = QDoubleSpinBox()
        self.slope.setRange(1.01, 20.0)
        self.slope.setValue(g.gap_slope_factor)
        self.window = QSpinBox()
        self.window.setRange(3, 999)
        self.window.setSingleStep(2)
        self.window.setValue(g.smoothing_window)
        self.degree = QSpinBox()
        self.degree.setRange(1, 20)
        self.degree.setValue(g.smoothing_degree)
        self.points = QSpinBox()
        self.points.setRange(101, 100001)
        self.points.setValue(g.interpolation_points)
        for label, widget in (
            ("Rn fit from", self.rn_min),
            ("Rn fit to", self.rn_max),
            ("Rj search from", self.rj_min),
            ("Rj search to", self.rj_max),
            ("Gap search from", self.gap_min),
            ("Gap search to", self.gap_max),
            ("Gap slope factor", self.slope),
            ("Smoothing window", self.window),
            ("Smoothing degree", self.degree),
            ("Interpolation points", self.points),
        ):
            form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.parameters = parameters

    def build(self) -> IVAnalysisParameters:
        return IVAnalysisParameters(
            resistance=IVAnalysisConfig(
                rn_min_voltage_mv=self.rn_min.value(),
                rn_max_voltage_mv=self.rn_max.value() or None,
                rj_min_voltage_mv=self.rj_min.value(),
                rj_max_voltage_mv=self.rj_max.value(),
            ),
            gap=IVGapConfig(
                gap_min_voltage_mv=self.gap_min.value(),
                gap_max_voltage_mv=self.gap_max.value(),
                gap_slope_factor=self.slope.value(),
                smoothing_window=self.window.value(),
                smoothing_degree=self.degree.value(),
                interpolation_points=self.points.value(),
            ),
        )

    def accept_if_valid(self) -> None:
        try:
            self.parameters = self.build()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid parameters", str(e))
            return
        self.accept()


class Overlay:
    """Fit lines and markers drawn on the plot; removed before the next analysis."""

    def __init__(self, plot_item):
        self.plot_item = plot_item
        self.items = []

    def clear(self) -> None:
        for item in self.items:
            self.plot_item.removeItem(item)
        self.items = []

    def draw(self, result: IVResistanceAnalysis) -> None:
        self.clear()
        fit, tangent = result.rn_fit, result.rj_tangent
        start = fit.line_voltage_range_mv[0]
        if result.gap is not None:
            start = min(start, result.gap.lower_voltage_mv)
        rn_v = np.linspace(start, fit.line_voltage_range_mv[1], 200)
        rj_v = np.linspace(*tangent.line_voltage_range_mv, 200)
        dashed = Qt.PenStyle.DashLine
        self.items.append(
            self.plot_item.plot(
                rn_v, fit.current_ua(rn_v), pen=pg.mkPen("#d62728", width=2, style=dashed),
                name=f"Rn {result.rn_ohm:.2f} Ω",
            )
        )  # fmt: skip
        self.items.append(
            self.plot_item.plot(
                rj_v, tangent.current_ua(rj_v), pen=pg.mkPen("#2ca02c", width=2, style=dashed),
                name=f"Rj {result.rj_ohm:.2f} Ω, Q={result.q:.2f}",
            )
        )  # fmt: skip
        markers = [
            (fit.reference_voltage_mv, fit.reference_current_ua, "o", "#d62728"),
            (tangent.touch_voltage_mv, tangent.touch_current_ua, "o", "#2ca02c"),
        ]
        if result.gap is not None:
            gap = result.gap
            markers += [
                (gap.lower_voltage_mv, gap.lower_current_ua, "t1", "#9467bd"),
                (gap.upper_voltage_mv, gap.upper_current_ua, "t", "#9467bd"),
                (
                    gap.voltage_mv,
                    (gap.lower_current_ua + gap.upper_current_ua) / 2,
                    "d",
                    "#202020",
                ),
            ]
        for x, y, symbol, color in markers:
            self.items.append(
                self.plot_item.plot(
                    [x], [y], pen=None, symbol=symbol, symbolSize=10, symbolBrush=color,
                    symbolPen=pg.mkPen("#202020", width=1),
                )
            )  # fmt: skip
        for item in self.items:
            item.setZValue(10)


class IVAnalysisBar(QWidget):
    """Toolbar under an I-V plot: choose a curve, analyze, tune parameters."""

    def __init__(self, line_plot, parent=None):
        super().__init__(parent)
        self.line_plot = line_plot
        self.parameters = load_parameters()
        self.overlay = Overlay(line_plot.plot.getPlotItem())
        self.result: Optional[IVResistanceAnalysis] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.curve = QComboBox()
        self.curve.setMinimumContentsLength(16)
        self.btnAnalyze = QPushButton("Analyze")
        self.btnAnalyze.clicked.connect(self.analyze)
        self.btnParameters = QPushButton("Parameters…")
        self.btnParameters.clicked.connect(self.edit_parameters)
        self.btnClear = QPushButton("Clear")
        self.btnClear.clicked.connect(self.clear)
        row.addWidget(QLabel("Curve"))
        row.addWidget(self.curve, 1)
        for button in (self.btnAnalyze, self.btnParameters, self.btnClear):
            row.addWidget(button)
        layout.addLayout(row)
        self.label = QLabel("Select a curve and press Analyze")
        self.label.setTextFormat(Qt.RichText)
        layout.addWidget(self.label)

    def refresh_curves(self) -> None:
        current = self.curve.currentData()
        self.curve.blockSignals(True)
        self.curve.clear()
        for group in self.line_plot.points:
            self.curve.addItem(self.line_plot.spec.label(group) or "curve", group)
        index = self.curve.findData(current)
        self.curve.setCurrentIndex(index if index >= 0 else self.curve.count() - 1)
        self.curve.blockSignals(False)

    def analyze(self) -> Optional[IVResistanceAnalysis]:
        group = self.curve.currentData()
        points = self.line_plot.points.get(group)
        if not points:
            self.label.setText("No curve to analyze")
            return None
        voltage, current = zip(*points)
        analyzer = NumpyIVAnalyzerFactory().create(self.parameters)
        try:
            self.result = analyzer.analyze(voltage, current)
        except ValueError as e:
            self.overlay.clear()
            self.label.setText(f"Analysis failed: {e}")
            return None
        self.overlay.draw(self.result)
        self.label.setText(format_result(self.result))
        return self.result

    def edit_parameters(self) -> None:
        dialog = ParametersDialog(self.parameters, self)
        if dialog.exec() == QDialog.Accepted:
            self.parameters = dialog.parameters
            save_parameters(self.parameters)
            if self.result is not None:
                self.analyze()

    def clear(self) -> None:
        self.overlay.clear()
        self.result = None
        self.label.setText("Select a curve and press Analyze")
