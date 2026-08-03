from html import escape
from typing import Optional

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)

from interface.windows.graphWindow import GraphWindow
from interface.windows.ivAnalysisOverlay import (
    IVAnalysisOverlayRenderer,
    format_analysis_result,
    is_analysis_overlay,
)
from utils.iv_analysis import IVAnalyzer, NumpyIVResistanceAnalyzer


class BiasGraphWindow(GraphWindow):
    window_title = "I-V curve"
    graph_title = "I-V curve"
    x_label = "Bias Voltage, mV"
    y_label = "Bias Current, mkA"

    def __init__(
        self,
        parent,
        analyzer: Optional[IVAnalyzer] = None,
        overlay_renderer_factory=IVAnalysisOverlayRenderer,
    ):
        self.analyzer = analyzer or NumpyIVResistanceAnalyzer()
        super().__init__(parent)
        self.overlay_renderer = overlay_renderer_factory(self.graphWidget.getPlotItem())
        self._analyzed_curve_name = None
        self._create_analysis_controls()
        self.curves_changed.connect(self._refresh_curve_selector)
        self._refresh_curve_selector()

    def _create_analysis_controls(self):
        analysis_layout = QHBoxLayout()
        curve_label = QLabel("Analyze I-V curve:")
        self.analysisCurveSelector = QComboBox(self)
        self.analysisCurveSelector.setMinimumWidth(280)
        self.btnAnalyzeCurve = QPushButton("Calculate Rn / Rj / Q", self)
        self.btnAnalyzeCurve.clicked.connect(self.analyze_selected_curve)
        self.btnClearAnalysis = QPushButton("Clear analysis", self)
        self.btnClearAnalysis.clicked.connect(self.clear_analysis)

        analysis_layout.addWidget(curve_label)
        analysis_layout.addWidget(self.analysisCurveSelector, stretch=1)
        analysis_layout.addWidget(self.btnAnalyzeCurve)
        analysis_layout.addWidget(self.btnClearAnalysis)

        self.analysisResultLabel = QLabel(self)
        self.analysisResultLabel.setWordWrap(True)
        self.analysisResultLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.analysisResultLabel.setStyleSheet(
            "QLabel { background: #f5f6f8; border: 1px solid #d7d9de; "
            "border-radius: 3px; padding: 6px; color: #30333a; }"
        )

        self.main_layout.insertLayout(1, analysis_layout)
        self.main_layout.insertWidget(2, self.analysisResultLabel)

    def _source_curve_items(self):
        return {
            name: item
            for name, item in self.get_plot_items().items()
            if not is_analysis_overlay(item)
        }

    def _refresh_curve_selector(self):
        source_items = self._source_curve_items()
        if (
            self._analyzed_curve_name is not None
            and self._analyzed_curve_name not in source_items
        ):
            self.clear_analysis()

        names = list(source_items)
        selector_names = [
            self.analysisCurveSelector.itemData(index)
            for index in range(self.analysisCurveSelector.count())
        ]
        if names != selector_names:
            selected_name = self.analysisCurveSelector.currentData()
            blocker = QSignalBlocker(self.analysisCurveSelector)
            self.analysisCurveSelector.clear()
            for name in names:
                self.analysisCurveSelector.addItem(self._curve_label(name), name)
            selected_index = self.analysisCurveSelector.findData(selected_name)
            if selected_index >= 0:
                self.analysisCurveSelector.setCurrentIndex(selected_index)
            del blocker

        has_curves = bool(names)
        self.analysisCurveSelector.setEnabled(has_curves)
        self.btnAnalyzeCurve.setEnabled(has_curves)
        self.btnClearAnalysis.setEnabled(self._analyzed_curve_name is not None)
        if not has_curves and self._analyzed_curve_name is None:
            self.analysisResultLabel.setText("No I-V curve selected for analysis")

    @staticmethod
    def _curve_label(name: str) -> str:
        return name.rstrip("; ").replace("; ", " | ")

    def analyze_selected_curve(self):
        curve_name = self.analysisCurveSelector.currentData()
        curve_item = self._source_curve_items().get(curve_name)
        if curve_item is None:
            return

        self.overlay_renderer.clear()
        self._analyzed_curve_name = None
        voltage_mv, current_ua = curve_item.getData()
        try:
            result = self.analyzer.analyze(voltage_mv, current_ua)
        except (ValueError, RuntimeError) as error:
            self.analysisResultLabel.setText(
                f"<b>{escape(self._curve_label(curve_name))}</b><br>"
                f"Analysis error: {escape(str(error))}"
            )
            self.btnClearAnalysis.setEnabled(False)
            QMessageBox.warning(self, "I-V analysis", str(error))
            return

        self.overlay_renderer.render(result)
        self._analyzed_curve_name = curve_name
        self.analysisResultLabel.setText(
            f"<b>{escape(self._curve_label(curve_name))}</b><br>"
            f"{format_analysis_result(result)}"
        )
        self.btnClearAnalysis.setEnabled(True)

    def clear_analysis(self):
        self.overlay_renderer.clear()
        self._analyzed_curve_name = None
        self.analysisResultLabel.setText("Select one I-V curve and run the analysis")
        self.btnClearAnalysis.setEnabled(False)
