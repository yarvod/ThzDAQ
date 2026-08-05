import unittest

import numpy as np

from utils.iv_analysis import (
    IVAnalysisConfig,
    IVGapConfig,
    NumpyIVGapAnalyzer,
    NumpyIVResistanceAnalyzer,
)


class IVResistanceAnalyzerTest(unittest.TestCase):
    @staticmethod
    def _gap_curve(overshoot_ua=0.0):
        voltage_mv = np.linspace(0.1, 6.0, 300)
        subgap_current_ua = 20.0 * voltage_mv
        normal_current_ua = 100.0 * voltage_mv - 180.0
        transition = 1.0 / (1.0 + np.exp(-(voltage_mv - 2.58) / 0.045))
        current_ua = (
            subgap_current_ua + (normal_current_ua - subgap_current_ua) * transition
        )
        current_ua += overshoot_ua * np.exp(-(((voltage_mv - 2.72) / 0.07) ** 2))
        return voltage_mv, current_ua

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

    def test_calculates_gap_from_normal_fit_intersection(self):
        voltage_mv, current_ua = self._gap_curve(overshoot_ua=30.0)

        result = NumpyIVResistanceAnalyzer().analyze(voltage_mv, current_ua)

        self.assertIsNotNone(result.gap)
        self.assertEqual(result.gap.upper_method, "normal_fit_intersection")
        self.assertGreater(result.vgap_mv, result.gap.lower_voltage_mv)
        self.assertLess(result.vgap_mv, result.gap.upper_voltage_mv)
        self.assertGreater(result.igap_ua, 0.0)

    def test_uses_double_normal_slope_when_fit_does_not_cross_curve(self):
        voltage_mv, current_ua = self._gap_curve()

        result = NumpyIVResistanceAnalyzer().analyze(voltage_mv, current_ua)

        self.assertIsNotNone(result.gap)
        self.assertEqual(result.gap.upper_method, "double_normal_slope")
        self.assertGreater(result.igap_ua, 0.0)

    def test_leaves_gap_empty_when_curve_has_no_knee(self):
        voltage_mv = np.linspace(0.1, 6.0, 100)
        current_ua = 50.0 * voltage_mv

        result = NumpyIVResistanceAnalyzer().analyze(voltage_mv, current_ua)

        self.assertIsNone(result.gap)
        self.assertIsNone(result.vgap_mv)
        self.assertIsNone(result.igap_ua)

    def test_gap_analyzer_can_be_injected(self):
        class NoGapAnalyzer:
            def __init__(self):
                self.calls = []

            def analyze(self, voltage_mv, current_ua, rn_fit):
                self.calls.append((voltage_mv, current_ua, rn_fit))
                return None

        gap_analyzer = NoGapAnalyzer()
        voltage_mv, current_ua = self._gap_curve()

        result = NumpyIVResistanceAnalyzer(gap_analyzer=gap_analyzer).analyze(
            voltage_mv,
            current_ua,
        )

        self.assertIsNone(result.gap)
        self.assertEqual(len(gap_analyzer.calls), 1)

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
        with self.assertRaisesRegex(ValueError, "Gap maximum"):
            NumpyIVGapAnalyzer(
                IVGapConfig(
                    gap_min_voltage_mv=3.0,
                    gap_max_voltage_mv=2.2,
                )
            )
        with self.assertRaisesRegex(ValueError, "Smoothing window"):
            NumpyIVGapAnalyzer(IVGapConfig(smoothing_window=30))


if __name__ == "__main__":
    unittest.main()
