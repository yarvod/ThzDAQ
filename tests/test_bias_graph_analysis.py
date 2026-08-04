import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from interface.windows.biasGraphWindow import BiasGraphWindow
from interface.windows.ivAnalysisOverlay import is_analysis_overlay
from utils.iv_analysis import NumpyIVResistanceAnalyzer


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
        self.assertLessEqual(self.window.btnClearAnalysis.maximumWidth(), 55)
        self.assertTrue(self.window.analysisResultLabel.isHidden())
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
        self.assertFalse(self.window.analysisResultLabel.isHidden())
        overlay_count = sum(
            is_analysis_overlay(item)
            for item in self.window.graphWidget.getPlotItem().listDataItems()
        )
        self.assertEqual(overlay_count, 4)
        self.assertEqual(self.window.analysisCurveSelector.count(), 2)

        self.window.remove_all_graphs()

        self.assertEqual(self.window.analysisCurveSelector.count(), 0)
        self.assertIsNone(self.window._analyzed_curve_name)
        self.assertTrue(self.window.analysisResultLabel.isHidden())
        self.assertEqual(
            len(self.window.graphWidget.getPlotItem().listDataItems()),
            0,
        )


if __name__ == "__main__":
    unittest.main()
