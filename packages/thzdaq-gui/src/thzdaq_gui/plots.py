"""Live plots described by PlotSpec: one tab per spec."""

import math
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6 import QtGui
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget
from thzdaq_core.data.dataset import Dataset
from thzdaq_core.measurements.plots import GroupKey, PlotSpec

COLORS = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
)  # fmt: skip


class LinePlot(QWidget):
    def __init__(self, spec: PlotSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot = pg.PlotWidget(background="w")
        self.plot.setTitle(spec.title, color="#413C58")
        self.plot.setLabel("bottom", spec.x_label)
        self.plot.setLabel("left", spec.y_label)
        self.plot.showGrid(x=True, y=True)
        self.plot.addLegend()
        layout.addWidget(self.plot)
        self.points: Dict[GroupKey, List[Tuple[float, float]]] = {}
        self.curves: Dict[GroupKey, pg.PlotDataItem] = {}
        self.analysis = None
        if spec.analysis == "iv":
            from thzdaq_gui.iv_analysis import IVAnalysisBar

            self.analysis = IVAnalysisBar(self)
            layout.addWidget(self.analysis)

    def clear(self) -> None:
        if self.analysis is not None:
            self.analysis.clear()
        self.plot.clear()
        self.points.clear()
        self.curves.clear()
        if self.analysis is not None:
            self.analysis.refresh_curves()

    def add(self, record: Mapping) -> None:
        point = self.spec.point(record)
        if point is None or not all(math.isfinite(v) for v in point[:2]):
            return
        group = self.spec.group_key(record)
        self.points.setdefault(group, []).append(point[:2])
        curve = self.curves.get(group)
        if curve is None:
            color = COLORS[len(self.curves) % len(COLORS)]
            pen = pg.mkPen(color, width=2)
            curve = self.plot.plot(
                [], [], pen=pen, symbol="o", symbolSize=5, symbolBrush=color,
                name=self.spec.label(group) or None,
            )  # fmt: skip
            self.curves[group] = curve
            if self.analysis is not None:
                self.analysis.refresh_curves()
        xs, ys = zip(*self.points[group])
        curve.setData(list(xs), list(ys))


class MapPlot(QWidget):
    def __init__(self, spec: PlotSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = pg.GraphicsLayoutWidget()
        self.view.setBackground("w")
        plot = self.view.addPlot(title=spec.title)
        plot.setLabel("bottom", spec.x_label)
        plot.setLabel("left", spec.y_label)
        self.image = pg.ImageItem()
        plot.addItem(self.image)
        self.histogram = pg.HistogramLUTItem()
        self.histogram.gradient.loadPreset("turbo")
        self.histogram.setImageItem(self.image)
        self.view.addItem(self.histogram)
        layout.addWidget(self.view)
        self.values: Dict[Tuple[float, float], float] = {}

    def clear(self) -> None:
        self.values.clear()
        self.image.clear()

    def add(self, record: Mapping) -> None:
        point = self.spec.point(record)
        if point is None:
            return
        x, y, z = point
        self.values[x, y] = z
        self.redraw()

    def grid(self):
        xs = sorted({x for x, _ in self.values})
        ys = sorted({y for _, y in self.values})
        data = np.full((len(xs), len(ys)), np.nan)
        for (x, y), z in self.values.items():
            data[xs.index(x), ys.index(y)] = z
        return xs, ys, data

    def redraw(self) -> None:
        xs, ys, data = self.grid()
        finite = data[np.isfinite(data)]
        if not finite.size:
            return
        low, high = float(finite.min()), float(finite.max())
        if low == high:
            low, high = low - 0.5, high + 0.5
        self.image.setImage(data, levels=(low, high), autoLevels=False)
        step_x = xs[1] - xs[0] if len(xs) > 1 else 1.0
        step_y = ys[1] - ys[0] if len(ys) > 1 else 1.0
        transform = QtGui.QTransform()
        transform.translate(xs[0] - step_x / 2, ys[0] - step_y / 2)
        transform.scale(step_x, step_y)
        self.image.setTransform(transform)


class PlotPanel(QTabWidget):
    """Shows the plots of one procedure; fed record by record or from a dataset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plots: List[QWidget] = []

    def set_specs(self, specs: Sequence[PlotSpec]) -> None:
        self.clear()
        self.plots = []
        for spec in specs:
            widget = MapPlot(spec) if spec.kind == "map" else LinePlot(spec)
            self.addTab(widget, spec.title)
            self.plots.append(widget)

    def reset(self) -> None:
        for plot in self.plots:
            plot.clear()

    def add_record(self, stream: str, record: Mapping) -> None:
        for plot in self.plots:
            if plot.spec.stream == stream:
                plot.add(record)

    def show_dataset(self, dataset: Dataset, specs: Iterable[PlotSpec]) -> None:
        self.set_specs(list(specs))
        for stream, records in dataset.streams.items():
            for record in records:
                self.add_record(stream, record)
