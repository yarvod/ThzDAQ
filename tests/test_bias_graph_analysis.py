import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from interface.windows.biasGraphWindow import BiasGraphWindow
from interface.windows.ivAnalysisOverlay import is_analysis_overlay
from utils.iv_analysis import (
    IVAnalysisConfig,
    IVAnalysisParameters,
    IVGapConfig,
    NumpyIVGapAnalyzer,
    NumpyIVResistanceAnalyzer,
)


class _RecordingAnalyzer:
    def __init__(self):
        self.delegate = NumpyIVResistanceAnalyzer()
        self.calls = []

    def analyze(self, voltage_mv, current_ua):
        self.calls.append((list(voltage_mv), list(current_ua)))
        return self.delegate.analyze(voltage_mv, current_ua)


class BiasGraphAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.analyzer = _RecordingAnalyzer()
        self.window = BiasGraphWindow(None, analyzer=self.analyzer)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_analyzes_only_the_curve_selected_in_the_combobox(self):
        voltage = [0.5, 1.0, 2.0, 2.5, 4.0, 5.0, 6.0]
        self.window.plot(
            voltage,
            [40.0, 60.0, 100.0, 140.0, 100.0, 200.0, 300.0],
            plot_num=1,
            measure_id=11,
        )
        self.window.plot(
            voltage,
            [20.0, 30.0, 50.0, 70.0, 50.0, 100.0, 150.0],
            plot_num=2,
            measure_id=12,
        )

        self.assertEqual(self.window.analysisCurveSelector.count(), 2)
        self.assertLessEqual(self.window.analysisCurveSelector.maximumWidth(), 170)
        self.assertLessEqual(self.window.btnAnalyzeCurve.maximumWidth(), 75)
        self.assertLessEqual(self.window.btnAnalysisParameters.maximumWidth(), 85)
        self.assertFalse(self.window.btnAnalysisParameters.isEnabled())
        self.assertLessEqual(self.window.btnClearAnalysis.maximumWidth(), 55)
        self.assertTrue(self.window.analysisResultLabel.isHidden())
        self.assertEqual(
            self.window.analysisResultLabel.textInteractionFlags(),
            Qt.TextInteractionFlag.NoTextInteraction,
        )
        minimum_height_before_analysis = self.window.minimumSizeHint().height()
        second_curve_name = self.window.analysisCurveSelector.itemData(1)
        self.window.analysisCurveSelector.setCurrentIndex(1)
        self.window.analyze_selected_curve()

        self.assertEqual(len(self.analyzer.calls), 1)
        self.assertEqual(self.analyzer.calls[0][0], voltage)
        self.assertEqual(
            self.analyzer.calls[0][1],
            [20.0, 30.0, 50.0, 70.0, 50.0, 100.0, 150.0],
        )
        self.assertEqual(self.window._analyzed_curve_name, second_curve_name)
        self.assertIn("Rn:</b> 20.00 Ω", self.window.analysisResultLabel.text())
        self.assertIn("Rj:</b> 40.00 Ω", self.window.analysisResultLabel.text())
        self.assertIn("Rj/Rn:</b> 2", self.window.analysisResultLabel.text())
        self.assertIn("Vgap:</b>", self.window.analysisResultLabel.text())
        self.assertIn("Igap:</b>", self.window.analysisResultLabel.text())
        self.assertNotIn("R²", self.window.analysisResultLabel.text())
        self.assertNotIn("reference", self.window.analysisResultLabel.text())
        self.assertNotIn("Fit points", self.window.analysisResultLabel.text())
        self.assertNotIn("id 12", self.window.analysisResultLabel.text())
        self.assertFalse(self.window.analysisResultLabel.isHidden())
        self.assertIs(self.window.analysisResultLabel.parent(), self.window.graphWidget)
        self.assertTrue(
            self.window.analysisResultLabel.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
        )
        self.assertEqual(
            self.window.minimumSizeHint().height(),
            minimum_height_before_analysis,
        )
        overlay_count = sum(
            is_analysis_overlay(item)
            for item in self.window.graphWidget.getPlotItem().listDataItems()
        )
        self.assertGreaterEqual(overlay_count, 4)
        self.assertEqual(self.window.analysisCurveSelector.count(), 2)

        self.window.remove_all_graphs()

        self.assertEqual(self.window.analysisCurveSelector.count(), 0)
        self.assertIsNone(self.window._analyzed_curve_name)
        self.assertTrue(self.window.analysisResultLabel.isHidden())
        self.assertEqual(
            len(self.window.graphWidget.getPlotItem().listDataItems()),
            0,
        )

    def test_applies_parameters_through_the_analyzer_factory(self):
        window = BiasGraphWindow(None)
        parameters = IVAnalysisParameters(
            resistance=IVAnalysisConfig(
                rn_min_voltage_mv=4.5,
                rn_max_voltage_mv=6.5,
                rj_min_voltage_mv=0.2,
                rj_max_voltage_mv=2.6,
            ),
            gap=IVGapConfig(
                gap_min_voltage_mv=2.3,
                gap_max_voltage_mv=3.1,
                gap_slope_factor=2.5,
                smoothing_window=41,
                smoothing_degree=4,
                interpolation_points=1201,
            ),
        )

        window.set_analysis_parameters(parameters)

        self.assertTrue(window.btnAnalysisParameters.isEnabled())
        self.assertEqual(window.analysis_parameters, parameters)
        self.assertIsInstance(window.analyzer, NumpyIVResistanceAnalyzer)
        self.assertEqual(window.analyzer.config, parameters.resistance)
        self.assertIsInstance(window.analyzer.gap_analyzer, NumpyIVGapAnalyzer)
        self.assertEqual(window.analyzer.gap_analyzer.config, parameters.gap)
        window.close()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
