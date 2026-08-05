import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from interface.windows.ivAnalysisParametersDialog import (
    IVAnalysisParametersDialog,
)
from utils.iv_analysis import IVAnalysisConfig, IVAnalysisParameters, IVGapConfig


class IVAnalysisParametersDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_round_trips_all_analysis_parameters(self):
        parameters = IVAnalysisParameters(
            resistance=IVAnalysisConfig(
                rn_min_voltage_mv=4.5,
                rn_max_voltage_mv=6.5,
                rj_min_voltage_mv=0.1,
                rj_max_voltage_mv=2.7,
            ),
            gap=IVGapConfig(
                gap_min_voltage_mv=2.25,
                gap_max_voltage_mv=3.1,
                gap_slope_factor=2.5,
                smoothing_window=41,
                smoothing_degree=4,
                interpolation_points=1201,
            ),
        )
        dialog = IVAnalysisParametersDialog(None, parameters)

        dialog.accept()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.parameters, parameters)
        dialog.deleteLater()

    def test_supports_an_automatic_rn_upper_limit(self):
        dialog = IVAnalysisParametersDialog(None, IVAnalysisParameters())

        dialog.rnMaxVoltage.setValue(0.0)
        dialog.accept()

        self.assertIsNone(dialog.parameters.resistance.rn_max_voltage_mv)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
