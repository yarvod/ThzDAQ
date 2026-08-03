import unittest

import numpy as np

from utils.iv_analysis import IVAnalysisConfig, NumpyIVResistanceAnalyzer


class IVResistanceAnalyzerTest(unittest.TestCase):
    def test_calculates_rn_supporting_tangent_and_q(self):
        voltage_mv = [-2.0, 0.0, 2.5, 1.0, 6.0, 2.0, 4.0, 0.5, 5.0, np.nan]
        current_ua = [
            -100.0,
            0.0,
            140.0,
            60.0,
            300.0,
            100.0,
            100.0,
            40.0,
            200.0,
            np.nan,
        ]

        result = NumpyIVResistanceAnalyzer().analyze(voltage_mv, current_ua)

        self.assertAlmostEqual(result.rn_ohm, 10.0)
        self.assertAlmostEqual(result.rj_ohm, 20.0)
        self.assertAlmostEqual(result.q, 2.0)
        self.assertAlmostEqual(result.rn_fit.slope_ua_per_mv, 100.0)
        self.assertAlmostEqual(result.rn_fit.intercept_ua, -300.0)
        self.assertAlmostEqual(result.rn_fit.r_squared, 1.0)
        self.assertEqual(result.rn_fit.point_count, 3)
        self.assertAlmostEqual(result.rj_tangent.touch_voltage_mv, 2.0)
        self.assertAlmostEqual(result.rj_tangent.touch_current_ua, 100.0)
        self.assertGreaterEqual(result.rj_tangent.minimum_clearance_ua, 0.0)

    def test_equal_supporting_slopes_choose_the_lowest_voltage(self):
        voltage_mv = [2.0, 1.0, 2.5, 4.0, 5.0]
        current_ua = [100.0, 50.0, 140.0, 100.0, 200.0]

        result = NumpyIVResistanceAnalyzer().analyze(voltage_mv, current_ua)

        self.assertAlmostEqual(result.rj_tangent.touch_voltage_mv, 1.0)
        self.assertAlmostEqual(result.rj_tangent.touch_current_ua, 50.0)

    def test_rejects_incompatible_or_insufficient_data(self):
        analyzer = NumpyIVResistanceAnalyzer()

        with self.assertRaisesRegex(ValueError, "same shape"):
            analyzer.analyze([1.0, 2.0], [1.0])
        with self.assertRaisesRegex(ValueError, "Rn fit range"):
            analyzer.analyze([0.5, 1.0, 2.0], [30.0, 50.0, 100.0])

    def test_validates_analysis_ranges(self):
        with self.assertRaisesRegex(ValueError, "Rn maximum"):
            NumpyIVResistanceAnalyzer(
                IVAnalysisConfig(
                    rn_min_voltage_mv=4.0,
                    rn_max_voltage_mv=3.0,
                )
            )
        with self.assertRaisesRegex(ValueError, "Rj maximum"):
            NumpyIVResistanceAnalyzer(
                IVAnalysisConfig(
                    rj_min_voltage_mv=1.0,
                    rj_max_voltage_mv=1.0,
                )
            )


if __name__ == "__main__":
    unittest.main()
