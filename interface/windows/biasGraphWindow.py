from typing import Optional

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
)

from interface.windows.graphWindow import GraphWindow
from interface.windows.ivAnalysisOverlay import (
    IVAnalysisOverlayRenderer,
    format_analysis_result,
    is_analysis_overlay,
)
from interface.windows.ivAnalysisParametersDialog import IVAnalysisParametersDialog
from utils.iv_analysis import (
    IVAnalysisParameters,
    IVAnalyzer,
    IVAnalyzerFactory,
    NumpyIVAnalyzerFactory,
)


class BiasGraphWindow(GraphWindow):
    window_title = "I-V curve"
    graph_title = "I-V curve"
    x_label = "Bias Voltage, mV"
    y_label = "Bias Current, mkA"

    def __init__(
        self,
        parent,
        analyzer: Optional[IVAnalyzer] = None,
        analyzer_factory: Optional[IVAnalyzerFactory] = None,
        analysis_parameters: Optional[IVAnalysisParameters] = None,
        overlay_renderer_factory=IVAnalysisOverlayRenderer,
        parameters_dialog_class=IVAnalysisParametersDialog,
    ):
        self.analysis_parameters = analysis_parameters or IVAnalysisParameters()
        self.analyzer_factory = analyzer_factory or NumpyIVAnalyzerFactory()
        self._manages_analyzer = analyzer is None
        self.analyzer = analyzer or self.analyzer_factory.create(
            self.analysis_parameters
        )
        self.parameters_dialog_class = parameters_dialog_class
        super().__init__(parent)
        self.overlay_renderer = overlay_renderer_factory(self.graphWidget.getPlotItem())
        self._analyzed_curve_name = None
        self._create_analysis_controls()
        self.curves_changed.connect(self._refresh_curve_selector)
        self._refresh_curve_selector()

    def _create_analysis_controls(self):
        analysis_layout = QHBoxLayout()
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.setSpacing(4)

        curve_label = QLabel("Curve:")
        self.analysisCurveSelector = QComboBox(self)
        self.analysisCurveSelector.setMinimumWidth(70)
        self.analysisCurveSelector.setMaximumWidth(170)
        self.analysisCurveSelector.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.analysisCurveSelector.currentIndexChanged.connect(
            self._update_curve_selector_tooltip
        )

        self.btnAnalyzeCurve = QPushButton("Analyze", self)
        self.btnAnalyzeCurve.setMaximumWidth(75)
        self.btnAnalyzeCurve.setToolTip(
            "Calculate Rn, Rj, Rj/Rn, Vgap and Igap for the selected curve"
        )
        self.btnAnalyzeCurve.clicked.connect(self.analyze_selected_curve)
        self.btnAnalysisParameters = QPushButton("Parameters", self)
        self.btnAnalysisParameters.setMaximumWidth(85)
        self.btnAnalysisParameters.setToolTip(
            "Configure I-V analysis ranges and filter"
        )
        self.btnAnalysisParameters.setEnabled(self._manages_analyzer)
        self.btnAnalysisParameters.clicked.connect(self.open_analysis_parameters)
        self.btnClearAnalysis = QPushButton("Clear", self)
        self.btnClearAnalysis.setMaximumWidth(55)
        self.btnClearAnalysis.setToolTip("Remove the I-V analysis from the graph")
        self.btnClearAnalysis.clicked.connect(self.clear_analysis)

        analysis_layout.addWidget(curve_label)
        analysis_layout.addWidget(self.analysisCurveSelector)
        analysis_layout.addWidget(self.btnAnalyzeCurve)
        analysis_layout.addWidget(self.btnAnalysisParameters)
        analysis_layout.addWidget(self.btnClearAnalysis)
        analysis_layout.addStretch(1)

        self.analysisResultLabel = QLabel(self.graphWidget)
        self.analysisResultLabel.setWordWrap(False)
        self.analysisResultLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
        )
        self.analysisResultLabel.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.analysisResultLabel.setStyleSheet(
            "QLabel { background: rgba(245, 246, 248, 225); "
            "border: 1px solid #d7d9de; "
            "border-radius: 3px; padding: 3px; color: #30333a; }"
        )
        self.analysisResultLabel.hide()

        self.main_layout.insertLayout(1, analysis_layout)

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
        self._update_curve_selector_tooltip()

        has_curves = bool(names)
        self.analysisCurveSelector.setEnabled(has_curves)
        self.btnAnalyzeCurve.setEnabled(has_curves)
        self.btnClearAnalysis.setEnabled(self._analyzed_curve_name is not None)

    def _update_curve_selector_tooltip(self):
        curve_name = self.analysisCurveSelector.currentData()
        self.analysisCurveSelector.setToolTip(
            self._curve_label(curve_name) if curve_name else ""
        )

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
            self.analysisResultLabel.clear()
            self.analysisResultLabel.hide()
            self.btnClearAnalysis.setEnabled(False)
            QMessageBox.warning(self, "I-V analysis", str(error))
            return

        self.overlay_renderer.render(result)
        self._analyzed_curve_name = curve_name
        self.analysisResultLabel.setText(format_analysis_result(result))
        self.analysisResultLabel.adjustSize()
        self.analysisResultLabel.move(8, 28)
        self.analysisResultLabel.show()
        self.analysisResultLabel.raise_()
        self.btnClearAnalysis.setEnabled(True)

    def open_analysis_parameters(self):
        if not self._manages_analyzer:
            return
        dialog = self.parameters_dialog_class(self, self.analysis_parameters)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_analysis_parameters(dialog.parameters)

    def set_analysis_parameters(self, parameters: IVAnalysisParameters):
        if not self._manages_analyzer:
            raise RuntimeError("The injected I-V analyzer is not configurable")
        analyzer = self.analyzer_factory.create(parameters)
        self.clear_analysis()
        self.analysis_parameters = parameters
        self.analyzer = analyzer

    def clear_analysis(self):
        self.overlay_renderer.clear()
        self._analyzed_curve_name = None
        self.analysisResultLabel.clear()
        self.analysisResultLabel.hide()
        self.btnClearAnalysis.setEnabled(False)
