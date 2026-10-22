"""Graph docks: one per kind of curve (I-V, P-V, P-IF, ...), as in the old app.

Measurements send their records to the graphs named by their PlotSpecs; every
run adds its own curves ("#12 SIS b1d4 hot"). Any table column of any
measurement in the Data dock can be added by hand as well (Add curve), with
titles and units taken from the measurement's column descriptions.
"""

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6 import QtGui
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.data.measurement import Column, Measurement
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.registry import list_procedures

from thzdaq_gui import theme

# Units shown with an SI prefix chosen by pyqtgraph (mV, uA, GHz)
SI_UNITS = {"V", "A", "Hz", "s", "W", "Pa", "Ohm"}


@dataclass
class Axis:
    label: str = ""
    unit: str = ""  # SI unit when the axis auto-scales, else ""
    scale: float = 1.0  # stored value / scale = shown value

    @classmethod
    def from_column(cls, column: Optional[Column]) -> "Axis":
        if column is None:
            return cls()
        title = column.title or column.key
        if column.unit in SI_UNITS:
            return cls(title, column.unit)
        return cls(column.label)


def curve_name(measurement: Measurement, group: Tuple) -> str:
    number = measurement.metadata.get("number", "")
    head = f"#{number} " if number != "" else ""
    devices = [use.title for use in measurement.devices.values() if use.title]
    who = devices[0] if len(devices) == 1 else (measurement.title or measurement.procedure)
    rest = " ".join(str(v) for v in group if v not in (None, ""))
    return f"{head}{who} {rest}".strip()


class GraphWidget(QWidget):
    """A line graph with curves from any measurements."""

    curves_changed = Signal()
    add_curve_clicked = Signal(object)  # this graph

    def __init__(self, title: str, x: Axis, y: Axis, analysis=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.x, self.y = x, y
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        bar = QHBoxLayout()
        self.btnAdd = self._tool("plus", "Add a curve from a measurement", self.add_dialog)
        self.btnHidden = self._tool(
            "eye-off-outline", "Remove hidden curves", self.remove_hidden
        )
        self.btnClear = self._tool("delete-sweep-outline", "Remove all curves", self.clear)
        self.btnRange = self._tool("fit-to-screen-outline", "Auto range", self.auto_range)
        for button in (self.btnAdd, self.btnHidden, self.btnClear, self.btnRange):
            bar.addWidget(button)
        bar.addStretch()
        layout.addLayout(bar)
        self.plot = pg.PlotWidget()
        item = self.plot.getPlotItem()
        item.setTitle(title, color=theme.ACCENT, size="11pt")
        item.showGrid(x=True, y=True, alpha=0.25)
        self._label("bottom", x)
        self._label("left", y)
        self.legend = item.addLegend(offset=(-10, 10), labelTextColor=theme.TEXT)
        layout.addWidget(self.plot, 1)
        # Curve key -> points in display units, and the plotted item
        self.points: Dict[object, List[Tuple[float, float]]] = {}
        self.items: Dict[object, pg.PlotDataItem] = {}
        self.names: Dict[object, str] = {}
        self.analysis = None
        if analysis == "iv":
            from thzdaq_gui.iv_analysis import IVAnalysisBar

            self.analysis = IVAnalysisBar(self)
            layout.addWidget(self.analysis)

    def _tool(self, icon_name: str, tip: str, slot) -> QToolButton:
        button = QToolButton()
        button.setIcon(theme.icon(icon_name))
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def _label(self, side: str, axis: Axis) -> None:
        if axis.unit:
            self.plot.setLabel(side, axis.label, units=axis.unit)
        else:
            self.plot.setLabel(side, axis.label)

    def curve_label(self, key) -> str:
        return self.names.get(key, "curve")

    def append(self, key, name: str, x: float, y: float) -> None:
        """Add a point (stored units) to curve `key`, creating it if new."""
        if x is None or y is None:
            return
        try:
            point = (float(x) / self.x.scale, float(y) / self.y.scale)
        except (TypeError, ValueError):
            return
        if not all(math.isfinite(v) for v in point):
            return
        self.points.setdefault(key, []).append(point)
        item = self.items.get(key)
        if item is None:
            color = theme.COLORS[len(self.items) % len(theme.COLORS)]
            item = self.plot.plot(
                [], [], pen=pg.mkPen(color, width=2), symbol="o", symbolSize=5,
                symbolBrush=color, symbolPen=None, name=name,
            )  # fmt: skip
            self.items[key] = item
            self.names[key] = name
            self.curves_changed.emit()
        xs, ys = zip(*self.points[key])
        item.setData(np.asarray(xs), np.asarray(ys))

    def add_columns(
        self, measurement: Measurement, table: str, x: str, y: str, group_by=()
    ) -> int:
        """Whole columns of a measurement table; returns the number of curves."""
        data = measurement.tables.get(table)
        if data is None:
            return 0
        keys = set()
        for row in data.rows():
            group = tuple(row.get(g) for g in group_by)
            key = (measurement.id, table, x, y, group)
            keys.add(key)
            self.append(key, curve_name(measurement, group), row.get(x), row.get(y))
        return len(keys)

    def remove(self, key) -> None:
        item = self.items.pop(key, None)
        if item is not None:
            self.plot.removeItem(item)
        self.points.pop(key, None)
        self.names.pop(key, None)
        self.curves_changed.emit()

    def remove_hidden(self) -> None:
        for key, item in list(self.items.items()):
            if not item.isVisible():
                self.remove(key)

    def clear(self) -> None:
        for key in list(self.items):
            self.remove(key)
        if self.analysis is not None:
            self.analysis.clear()

    def auto_range(self) -> None:
        self.plot.enableAutoRange()

    def add_dialog(self) -> None:
        self.add_curve_clicked.emit(self)


class MapGraphWidget(QWidget):
    """z over an x/y grid (2SB bias optimization)."""

    def __init__(self, spec: PlotSpec, parent=None):
        super().__init__(parent)
        self.title = spec.title
        self.spec = spec
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.view = pg.GraphicsLayoutWidget()
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

    def add_record(self, record) -> None:
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


def graph_for_spec(spec: PlotSpec):
    if spec.kind == "map":
        return MapGraphWidget(spec)
    return GraphWidget(
        spec.title,
        Axis(spec.x_label, scale=spec.x_scale),
        Axis(spec.y_label, scale=spec.y_scale),
        analysis=spec.analysis,
    )


# Device monitor values go to the same graphs as the monitor procedure
MONITOR_GRAPHS = {
    "power": "P-t",
    "temperature": "T-t",
    "voltage": "V-t",
    "current": "I-t",
    "current_set": "Coil-t",
    "pressure": "p-t",
}


class GraphHub(QObject):
    """Owns the graph widgets by title and routes records to them.

    The main window puts each graph into a dock; graph_created lets it add
    docks for graphs made later (New graph).
    """

    graph_created = Signal(object)  # GraphWidget or MapGraphWidget
    raise_requested = Signal(object)  # show this graph's dock

    def __init__(self, parent=None):
        super().__init__(parent)
        self.graphs: Dict[str, QWidget] = {}
        self.specs: Dict[str, PlotSpec] = {}
        self.add_curve_request: Optional[Callable[[GraphWidget], None]] = None
        for cls in list_procedures():
            for spec in cls.plots:
                self.specs.setdefault(spec.title, spec)

    def titles(self) -> List[str]:
        return list(self.specs) + [t for t in self.graphs if t not in self.specs]

    def graph(self, title: str) -> QWidget:
        if title not in self.graphs:
            spec = self.specs.get(title)
            if spec is not None:
                widget = graph_for_spec(spec)
            else:
                widget = GraphWidget(title, Axis(), Axis())
            if isinstance(widget, GraphWidget):
                widget.add_curve_clicked.connect(self._add_curve)
            self.graphs[title] = widget
            self.graph_created.emit(widget)
        return self.graphs[title]

    def _add_curve(self, widget) -> None:
        if self.add_curve_request is not None:
            self.add_curve_request(widget)

    def close(self) -> None:
        """Delete graphs not owned by docks (tests, a hub without a window)."""
        for widget in self.graphs.values():
            if widget.parent() is None:
                widget.deleteLater()
        self.graphs.clear()

    def raise_graph(self, title: str) -> None:
        self.raise_requested.emit(self.graph(title))

    def new_graph(self, title: str) -> QWidget:
        if title in self.graphs or title in self.specs:
            raise ValueError(f"Graph {title!r} exists")
        return self.graph(title)

    def feed(self, measurement: Measurement, specs, table: str, record) -> None:
        """A live record of a running measurement."""
        for spec in specs:
            if spec.table != table:
                continue
            widget = self.graph(spec.title)
            if isinstance(widget, MapGraphWidget):
                widget.add_record(record)
            else:
                group = spec.group_key(record)
                key = (measurement.id, spec.table, spec.x, spec.y, group)
                widget.append(
                    key, curve_name(measurement, group), record.get(spec.x),
                    record.get(spec.y),
                )  # fmt: skip

    def show_measurement(self, measurement: Measurement, specs) -> List[str]:
        """Plot a whole (saved) measurement in its graphs; returns their titles."""
        shown = []
        for spec in specs:
            if spec.table not in measurement.tables:
                continue
            widget = self.graph(spec.title)
            if isinstance(widget, MapGraphWidget):
                widget.clear()
                for record in measurement.records(spec.table):
                    widget.add_record(record)
            else:
                widget.add_columns(
                    measurement, spec.table, spec.x, spec.y, spec.group_by
                )
            shown.append(spec.title)
        return shown

    def monitor_value(self, device: str, title: str, key: str, t: float, value) -> None:
        graph_title = MONITOR_GRAPHS.get(key)
        if graph_title is None:
            return
        self.graph(graph_title).append(("monitor", device, key), title, t, value)


class AddCurveDialog(QDialog):
    """Pick a measurement, its table and the columns for x and y."""

    def __init__(self, measurements: List[Measurement], graph: GraphWidget, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Add curve to {graph.title}")
        self.measurements = [m for m in measurements if m.tables]
        self.graph = graph
        form = QFormLayout()
        self.measurement = QComboBox()
        for m in self.measurements:
            self.measurement.addItem(f"{m.id}  {m.title or m.procedure}  {m.comment}", m)
        self.table = QComboBox()
        self.x = QComboBox()
        self.y = QComboBox()
        self.group = QComboBox()
        form.addRow("Measurement", self.measurement)
        form.addRow("Table", self.table)
        form.addRow("X", self.x)
        form.addRow("Y", self.y)
        form.addRow("Separate curves by", self.group)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_choice)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.measurement.currentIndexChanged.connect(self.fill_tables)
        self.table.currentIndexChanged.connect(self.fill_columns)
        self.fill_tables()

    def current(self) -> Optional[Measurement]:
        return self.measurement.currentData()

    def fill_tables(self) -> None:
        self.table.clear()
        m = self.current()
        if m is None:
            return
        for name, table in m.tables.items():
            self.table.addItem(f"{table.title or name} ({len(table)} rows)", name)

    def fill_columns(self) -> None:
        m, name = self.current(), self.table.currentData()
        for combo in (self.x, self.y, self.group):
            combo.clear()
        self.group.addItem("—", None)
        if m is None or name is None:
            return
        for column in m.tables[name].columns:
            for combo in (self.x, self.y, self.group):
                combo.addItem(column.label, column.key)
        if self.y.count() > 1:
            self.y.setCurrentIndex(1)

    def accept_choice(self) -> None:
        m, name = self.current(), self.table.currentData()
        if m is None or name is None:
            self.reject()
            return
        x, y, group = self.x.currentData(), self.y.currentData(), self.group.currentData()
        table = m.tables[name]
        if not self.graph.items and not self.graph.x.label:
            self.graph.x = Axis.from_column(table.get_column(x))
            self.graph.y = Axis.from_column(table.get_column(y))
            self.graph._label("bottom", self.graph.x)
            self.graph._label("left", self.graph.y)
        if not self.graph.add_columns(m, name, x, y, (group,) if group else ()):
            QMessageBox.information(self, "Add curve", "No points to plot")
        self.accept()

