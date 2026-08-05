import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt

from utils.iv_analysis import IVResistanceAnalysis


ANALYSIS_OVERLAY_ATTRIBUTE = "_iv_analysis_overlay"


def is_analysis_overlay(item) -> bool:
    return bool(getattr(item, ANALYSIS_OVERLAY_ATTRIBUTE, False))


def format_analysis_result(result: IVResistanceAnalysis) -> str:
    gap = result.gap
    gap_text = (
        f"<b>Vgap:</b> {gap.voltage_mv:.3f} mV &nbsp; "
        f"<b>Igap:</b> {gap.current_step_ua:.3f} µA"
        if gap is not None
        else "<b>Vgap:</b> n/a &nbsp; <b>Igap:</b> n/a"
    )
    return (
        f"<b>Rn:</b> {result.rn_ohm:.2f} Ω &nbsp; "
        f"<b>Rj:</b> {result.rj_ohm:.2f} Ω &nbsp; "
        f"<b>Rj/Rn:</b> {result.q:.4g}<br>"
        f"{gap_text}"
    )


class IVAnalysisOverlayRenderer:
    def __init__(self, plot_item):
        self.plot_item = plot_item
        self._items = []

    def render(self, result: IVResistanceAnalysis):
        self.clear()
        rn_fit = result.rn_fit
        tangent = result.rj_tangent

        rn_line_start = rn_fit.line_voltage_range_mv[0]
        if result.gap is not None:
            rn_line_start = min(rn_line_start, result.gap.lower_voltage_mv)
        rn_voltage = np.linspace(
            rn_line_start,
            rn_fit.line_voltage_range_mv[1],
            200,
        )
        rj_voltage = np.linspace(*tangent.line_voltage_range_mv, 200)
        rn_line = self.plot_item.plot(
            rn_voltage,
            rn_fit.current_ua(rn_voltage),
            pen=pg.mkPen("#d62728", width=2, style=Qt.PenStyle.DashLine),
            name=f"Rn fit: {result.rn_ohm:.2f} Ω",
        )
        rj_line = self.plot_item.plot(
            rj_voltage,
            tangent.current_ua(rj_voltage),
            pen=pg.mkPen("#2ca02c", width=2, style=Qt.PenStyle.DashLine),
            name=f"Rj tangent: {result.rj_ohm:.2f} Ω; Q={result.q:.2f}",
        )
        rn_point = self.plot_item.plot(
            [rn_fit.reference_voltage_mv],
            [rn_fit.reference_current_ua],
            pen=None,
            symbol="o",
            symbolSize=10,
            symbolBrush="#d62728",
            symbolPen=pg.mkPen("#202020", width=1),
        )
        rj_point = self.plot_item.plot(
            [tangent.touch_voltage_mv],
            [tangent.touch_current_ua],
            pen=None,
            symbol="o",
            symbolSize=12,
            symbolBrush="#2ca02c",
            symbolPen=pg.mkPen("#202020", width=1),
        )

        self._items = [rn_line, rj_line, rn_point, rj_point]
        if result.gap is not None:
            gap = result.gap
            gap_lower_point = self.plot_item.plot(
                [gap.lower_voltage_mv],
                [gap.lower_current_ua],
                pen=None,
                symbol="t1",
                symbolSize=10,
                symbolBrush="#9467bd",
                symbolPen=pg.mkPen("#202020", width=1),
            )
            gap_upper_point = self.plot_item.plot(
                [gap.upper_voltage_mv],
                [gap.upper_current_ua],
                pen=None,
                symbol="t",
                symbolSize=10,
                symbolBrush="#9467bd",
                symbolPen=pg.mkPen("#202020", width=1),
            )
            gap_center_point = self.plot_item.plot(
                [gap.voltage_mv],
                [(gap.lower_current_ua + gap.upper_current_ua) / 2.0],
                pen=None,
                symbol="d",
                symbolSize=9,
                symbolBrush="#202020",
                symbolPen=pg.mkPen("#f5f5f5", width=1),
            )
            self._items.extend([gap_lower_point, gap_upper_point, gap_center_point])
        for item in self._items:
            setattr(item, ANALYSIS_OVERLAY_ATTRIBUTE, True)
            item.setZValue(10)
        rn_point.setZValue(11)
        rj_point.setZValue(11)

    def clear(self):
        current_items = self.plot_item.listDataItems()
        for item in self._items:
            if item in current_items:
                self.plot_item.removeItem(item)
        self._items = []
