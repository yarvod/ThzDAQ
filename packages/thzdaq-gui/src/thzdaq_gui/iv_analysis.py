"""I-V analysis on a plotted curve: Rn fit, Rj tangent, Q and the gap, done by the
daemon (analyze_iv) so every client gets the same result.

The curve is drawn in display units (mV, µA): it goes to the analysis in SI by
the axes' scales, and the lines and points of the result come back the same
way. An option left at Auto keeps the analysis default.
"""

from typing import Callable, Optional, Tuple

import msgspec
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.analysis import AnalyzeIv, IVAnalysis, IVLine, IVOptions
from thzdaq_api.errors import LabError

from thzdaq_gui.settings import IV_ANALYSIS, settings

MV, UA = 1e-3, 1e-6  # the dialog's units
AUTO = "Auto"

Analyze = Callable[[AnalyzeIv], IVAnalysis]  # the lab's call


def format_result(result: IVAnalysis) -> str:
    gap = result.gap
    gap_text = (
        f"<b>Vgap</b> {gap.voltage / MV:.3f} mV &nbsp; "
        f"<b>Igap</b> {gap.current_step / UA:.3f} µA"
        if gap is not None
        else "<b>Vgap</b> n/a"
    )
    return (
        f"<b>Rn</b> {result.rn.resistance:.2f} Ω &nbsp; "
        f"<b>Rj</b> {result.rj.resistance:.2f} Ω &nbsp; "
        f"<b>Rj/Rn</b> {result.q:.4g} &nbsp; {gap_text}"
    )


def load_options() -> IVOptions:
    raw = settings().value(IV_ANALYSIS)
    try:
        return msgspec.json.decode(raw, type=IVOptions) if raw else IVOptions()
    except (msgspec.DecodeError, msgspec.ValidationError):
        return IVOptions()  # saved by an older version: the defaults


def save_options(options: IVOptions) -> None:
    settings().setValue(IV_ANALYSIS, msgspec.json.encode(options).decode())


class ParametersDialog(QDialog):
    """The options of the analysis; the lowest value of a field is Auto."""

    def __init__(self, options: IVOptions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("I-V analysis parameters")
        form = QFormLayout()

        def spin(cls, low, high, value, scale=1.0, suffix="", decimals=3):
            box = cls()
            box.setRange(low, high)
            if cls is QDoubleSpinBox:
                box.setDecimals(decimals)
            box.setSuffix(suffix)
            box.setSpecialValueText(AUTO)
            box.setValue(low if value is None else value / scale)
            return box

        def voltage(value):
            return spin(QDoubleSpinBox, -0.001, 30.0, value, MV, " mV")

        o = options
        self.fields = {
            "rn_from": ("Rn fit from", voltage(o.rn_from), MV),
            "rn_to": ("Rn fit to", voltage(o.rn_to), MV),
            "rj_from": ("Rj search from", voltage(o.rj_from), MV),
            "rj_to": ("Rj search to", voltage(o.rj_to), MV),
            "gap_from": ("Gap search from", voltage(o.gap_from), MV),
            "gap_to": ("Gap search to", voltage(o.gap_to), MV),
            "gap_slope_factor": (
                "Gap slope factor",
                spin(QDoubleSpinBox, 1.0, 20.0, o.gap_slope_factor, decimals=2),
                None,
            ),
            "smoothing_window": (
                "Smoothing window", spin(QSpinBox, 1, 999, o.smoothing_window), None
            ),
            "smoothing_degree": (
                "Smoothing degree", spin(QSpinBox, 0, 20, o.smoothing_degree), None
            ),
            "interpolation_points": (
                "Interpolation points",
                spin(QSpinBox, 100, 100001, o.interpolation_points),
                None,
            ),
        }  # fmt: skip
        for label, widget, _ in self.fields.values():
            form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @property
    def options(self) -> IVOptions:
        """What is set; a field at Auto is left to the analysis."""
        values = {}
        for name, (_, widget, scale) in self.fields.items():
            if widget.value() != widget.minimum():
                value = widget.value()
                values[name] = value * scale if scale else value
        return IVOptions(**values)


class Overlay:
    """Fit lines and markers drawn on the plot; removed before the next analysis."""

    def __init__(self, plot_item, scales: Tuple[float, float]):
        self.plot_item = plot_item
        self.scales = scales  # stored value / scale = shown value, of x and y
        self.items = []

    def clear(self) -> None:
        for item in self.items:
            self.plot_item.removeItem(item)
        self.items = []

    def shown(self, point) -> Tuple[float, float]:
        return point[0] / self.scales[0], point[1] / self.scales[1]

    def line(self, line: IVLine, start: float, color: str, name: str) -> None:
        voltage = np.linspace(start, line.voltage_range[1], 200)
        current = line.slope * voltage + line.intercept
        x, y = voltage / self.scales[0], current / self.scales[1]
        pen = pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine)
        self.items.append(self.plot_item.plot(x, y, pen=pen, name=name))

    def draw(self, result: IVAnalysis) -> None:
        self.clear()
        rn, rj, gap = result.rn, result.rj, result.gap
        start = (
            rn.voltage_range[0]
            if gap is None
            else min(rn.voltage_range[0], gap.lower[0])
        )
        self.line(rn, start, "#d62728", f"Rn {rn.resistance:.2f} Ω")
        self.line(
            rj, rj.voltage_range[0], "#2ca02c",
            f"Rj {rj.resistance:.2f} Ω, Q={result.q:.2f}",
        )  # fmt: skip
        markers = [(rn.point, "o", "#d62728"), (rj.point, "o", "#2ca02c")]
        if gap is not None:
            middle = (gap.voltage, (gap.lower[1] + gap.upper[1]) / 2)
            markers += [
                (gap.lower, "t1", "#9467bd"),
                (gap.upper, "t", "#9467bd"),
                (middle, "d", "#202020"),
            ]
        for point, symbol, color in markers:
            x, y = self.shown(point)
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

    def __init__(self, line_plot, analyze: Analyze, parent=None):
        super().__init__(parent)
        self.line_plot = line_plot
        self.analyze_iv = analyze
        self.options = load_options()
        scales = (line_plot.x.scale, line_plot.y.scale)
        self.overlay = Overlay(line_plot.plot.getPlotItem(), scales)
        self.result: Optional[IVAnalysis] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Two narrow rows: the I-V dock must fit a narrow column
        row = QHBoxLayout()
        self.curve = QComboBox()
        self.curve.setMinimumContentsLength(8)
        self.curve.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(QLabel("Curve"))
        row.addWidget(self.curve, 1)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        self.btnAnalyze = QPushButton("Analyze")
        self.btnAnalyze.clicked.connect(self.analyze)
        self.btnParameters = QPushButton("Parameters…")
        self.btnParameters.clicked.connect(self.edit_parameters)
        self.btnClear = QPushButton("Clear")
        self.btnClear.clicked.connect(self.clear)
        for button in (self.btnAnalyze, self.btnParameters, self.btnClear):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.label = QLabel("Select a curve and press Analyze")
        self.label.setTextFormat(Qt.RichText)
        layout.addWidget(self.label)
        self.keys = []
        line_plot.curves_changed.connect(self.refresh_curves)
        self.refresh_curves()

    def refresh_curves(self) -> None:
        """The curves of the plot; a new one (the last run) is selected."""
        current = self.curve.currentData()
        keys = list(self.line_plot.points)
        new = [key for key in keys if key not in self.keys]
        self.keys = keys
        self.curve.blockSignals(True)
        self.curve.clear()
        for key in keys:
            self.curve.addItem(self.line_plot.curve_label(key), key)
        index = self.curve.findData(new[-1] if new else current)
        self.curve.setCurrentIndex(index if index >= 0 else self.curve.count() - 1)
        self.curve.blockSignals(False)
        if current is not None and current not in keys:
            self.clear()  # the analyzed curve is gone: so are its fit lines

    def analyze(self) -> Optional[IVAnalysis]:
        group = self.curve.currentData()
        points = self.line_plot.points.get(group)
        if not points:
            self.label.setText("No curve to analyze")
            return None
        x_scale, y_scale = self.overlay.scales
        operation = AnalyzeIv(
            voltage=tuple(x * x_scale for x, _ in points),
            current=tuple(y * y_scale for _, y in points),
            options=self.options,
        )
        try:
            self.result = self.analyze_iv(operation)
        except LabError as e:
            self.overlay.clear()
            self.label.setText(f"Analysis failed: {e}")
            return None
        self.overlay.draw(self.result)
        self.label.setText(format_result(self.result))
        return self.result

    def edit_parameters(self) -> None:
        dialog = ParametersDialog(self.options, self)
        if dialog.exec() == QDialog.Accepted:
            self.options = dialog.options
            save_options(self.options)
            if self.result is not None:
                self.analyze()

    def clear(self) -> None:
        self.overlay.clear()
        self.result = None
        self.label.setText("Select a curve and press Analyze")
