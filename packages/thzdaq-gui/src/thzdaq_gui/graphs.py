"""Graph docks: one per kind of curve (I-V, P-V, P-IF, ...), as in the old app.

Measurements send their records to the graphs named by their PlotSpecs; every
run adds its own curves ("#12 SIS b1d4 hot"). Any table column of any
measurement in the Data dock can be added by hand as well (Add curve), with
titles and units taken from the measurement's column descriptions.
"""

import bisect
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from pyqtgraph.graphicsItems.GraphicsWidgetAnchor import GraphicsWidgetAnchor
from PySide6 import QtGui
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from thzdaq_core.data.measurement import Column, Measurement
from thzdaq_core.measurements.plots import PlotSpec
from thzdaq_core.measurements.procedures.monitor import plot_for
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


def _names_devices(measurement: Measurement) -> bool:
    samples = measurement.tables.get("samples")
    return samples is not None and samples.get_column("device") is not None


def curve_name(measurement: Measurement, group: Tuple) -> str:
    head = f"#{measurement.id}" if measurement.id else ""
    devices = [use.title for use in measurement.devices.values() if use.title]
    rest = " ".join(str(v) for v in group if v not in (None, ""))
    if len(devices) == 1:
        who = devices[0]
    elif rest and _names_devices(measurement):
        who = ""  # the group names the device (a monitor of several)
    else:
        who = measurement.title or measurement.procedure
    return " ".join(part for part in (head.strip(), who, rest) if part)


class GraphWidget(QWidget):
    """A line graph with curves from any measurements.

    key names its dock and stays when a graph made with New graph… (custom)
    is renamed; graphs of the procedures are keyed by their title.
    """

    curves_changed = Signal()
    add_curve_clicked = Signal(object)  # this graph
    edit_clicked = Signal(object)
    delete_clicked = Signal(object)

    def __init__(
        self,
        title: str,
        x: Axis,
        y: Axis,
        analysis=None,
        key: Optional[str] = None,
        custom: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.title = title
        self.key = key or title
        self.custom = custom
        self.x, self.y = x, y
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        bar = QHBoxLayout()
        self.btnAdd = self._tool(
            "plus", "Add a curve from a measurement", self.add_dialog
        )
        self.btnHidden = self._tool(
            "eye-off-outline", "Remove hidden curves", self.remove_hidden
        )
        self.btnClear = self._tool(
            "delete-sweep-outline", "Remove all curves", self.clear
        )
        self.btnRange = self._tool(
            "fit-to-screen-outline", "Auto range", self.auto_range
        )
        for button in (self.btnAdd, self.btnHidden, self.btnClear, self.btnRange):
            bar.addWidget(button)
        bar.addStretch()
        if custom:
            self.btnEdit = self._tool(
                "pencil-outline", "Rename the graph, axis labels",
                lambda: self.edit_clicked.emit(self),
            )  # fmt: skip
            self.btnDelete = self._tool(
                "delete-outline", "Delete the graph",
                lambda: self.delete_clicked.emit(self),
            )  # fmt: skip
            bar.addWidget(self.btnEdit)
            bar.addWidget(self.btnDelete)
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

    def set_title(self, title: str) -> None:
        self.title = title
        self.plot.getPlotItem().setTitle(title, color=theme.ACCENT, size="11pt")

    def set_axes(self, x: Axis, y: Axis) -> None:
        self.x = Axis(x.label, x.unit, self.x.scale)
        self.y = Axis(y.label, y.unit, self.y.scale)
        self._label("bottom", self.x)
        self._label("left", self.y)

    def _label(self, side: str, axis: Axis) -> None:
        if axis.unit:
            self.plot.setLabel(side, axis.label, units=axis.unit)
        else:
            self.plot.setLabel(side, axis.label)

    def curve_label(self, key) -> str:
        return self.names.get(key, "curve")

    def append(
        self, key, name: str, x: float, y: float, window: Optional[float] = None
    ) -> bool:
        """Add a point (stored units) to curve `key`, creating it if new.

        window keeps only the points within that span of x before the newest
        one (a long monitor); the measurement itself keeps everything.
        """
        if x is None or y is None:
            return False
        try:
            point = (float(x) / self.x.scale, float(y) / self.y.scale)
        except (TypeError, ValueError):
            return False
        if not all(math.isfinite(v) for v in point):
            return False
        points = self.points.setdefault(key, [])
        points.append(point)
        if window:
            start = bisect.bisect_left(
                points, point[0] - window / self.x.scale, key=lambda p: p[0]
            )
            del points[:start]
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
        return True

    def add_columns(
        self,
        measurement: Measurement,
        table: str,
        x: str,
        y: str,
        group_by=(),
        where=(),
    ) -> int:
        """Whole columns of a measurement table; returns the number of curves.

        A curve of this measurement already drawn (its live run, an earlier
        Plot) is drawn again from the start, not continued: appending the
        sweep once more joined its end back to its start.
        """
        data = measurement.tables.get(table)
        if data is None:
            return 0
        keys = set()
        for row in data.rows():
            if any(row.get(k) != v for k, v in where):
                continue
            group = tuple(row.get(g) for g in group_by)
            key = (measurement.id, table, x, y, group)
            if key not in keys:
                keys.add(key)
                self.points.pop(key, None)
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


def release_anchors(scene) -> None:
    """Disconnect anchored items (a legend with an offset) from their parent.

    An anchored legend gets its parent's geometryChanged connected to one of
    its own methods. When the plot is deleted with that connection alive, the
    garbage collector later frees the legend's wrapper and corrupts memory in
    PySide 6.8 (a crash at a random later allocation, like PYSIDE-1919).
    The attributes are private to pyqtgraph's GraphicsWidgetAnchor (0.13.7).
    """
    if scene is None:
        return
    for item in scene.items():
        if not isinstance(item, GraphicsWidgetAnchor):
            continue
        parent = getattr(item, "_GraphicsWidgetAnchor__parent", None)
        slot = getattr(item, "_GraphicsWidgetAnchor__geometryChanged", None)
        if parent is None or slot is None:
            continue
        try:
            parent.geometryChanged.disconnect(slot)
        except (RuntimeError, TypeError):
            pass
        item._GraphicsWidgetAnchor__parent = None


def close_views(widget: QWidget) -> None:
    """Close the pyqtgraph views inside a widget before it is deleted."""
    for view in widget.findChildren(pg.GraphicsView):
        if not getattr(view, "closed", False):
            release_anchors(view.scene())
            view.close()


def close_plots() -> None:
    """Close every pyqtgraph view before the application quits.

    pyqtgraph disconnects all known views on quit; views deleted with their
    docks before that make it warn "Failed to disconnect ... destroyed()".
    """
    from pyqtgraph.Qt import isQObjectAlive

    for view in list(pg.ViewBox.AllViews):
        if isQObjectAlive(view):
            release_anchors(view.scene())
            view.close()
    pg.ViewBox.AllViews.clear()
    pg.ViewBox.NamedViews.clear()


def graph_for_spec(spec: PlotSpec):
    if spec.kind == "map":
        return MapGraphWidget(spec)
    return GraphWidget(
        spec.title,
        Axis(spec.x_label, scale=spec.x_scale),
        Axis(spec.y_label, scale=spec.y_scale),
        analysis=spec.analysis,
    )


class GraphHub(QObject):
    """Owns the graph widgets by title and routes records to them.

    The main window puts each graph into a dock; graph_created lets it add
    docks for graphs made later (New graph).
    """

    graph_created = Signal(object)  # GraphWidget or MapGraphWidget
    raise_requested = Signal(object)  # show this graph's dock in front
    show_requested = Signal(object)  # open this graph's dock if closed
    graph_renamed = Signal(object)  # a custom graph, its new title
    graph_removed = Signal(object)  # a custom graph to delete
    custom_changed = Signal()  # the custom graphs to remember

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
            self._add(widget)
        return self.graphs[title]

    def _add(self, widget) -> None:
        if isinstance(widget, GraphWidget):
            widget.add_curve_clicked.connect(self._add_curve)
        self.graphs[widget.title] = widget
        self.graph_created.emit(widget)

    def _add_curve(self, widget) -> None:
        if self.add_curve_request is not None:
            self.add_curve_request(widget)

    def close(self) -> None:
        """Delete graphs not owned by docks (tests, a hub without a window)."""
        for widget in self.graphs.values():
            if widget.parent() is None:
                close_views(widget)
                widget.deleteLater()
        self.graphs.clear()

    def raise_graph(self, title: str) -> None:
        self.raise_requested.emit(self.graph(title))

    def show_graph(self, title: str) -> None:
        """On screen, without taking the front from another graph."""
        self.show_requested.emit(self.graph(title))

    def _check_free(self, title: str) -> str:
        title = title.strip()
        if not title:
            raise ValueError("The graph needs a title")
        if title in self.graphs or title in self.specs:
            raise ValueError(f"Graph {title!r} exists")
        return title

    def new_graph(
        self, title: str, key: Optional[str] = None, x: str = "", y: str = ""
    ) -> GraphWidget:
        """A graph of the user's own (New graph…), renamed and deleted at will."""
        title = self._check_free(title)
        if key is None:
            used = {getattr(w, "key", "") for w in self.graphs.values()}
            key = next(
                f"custom{n}" for n in range(1, 10000) if f"custom{n}" not in used
            )
        widget = GraphWidget(title, Axis(x), Axis(y), key=key, custom=True)
        widget.edit_clicked.connect(self._edit)
        widget.delete_clicked.connect(self.graph_removed)
        self._add(widget)
        self.custom_changed.emit()
        return widget

    def custom_graphs(self) -> List[dict]:
        return [
            {"key": w.key, "title": w.title, "x": w.x.label, "y": w.y.label}
            for w in self.graphs.values()
            if getattr(w, "custom", False)
        ]

    def rename(self, widget: GraphWidget, title: str) -> None:
        if title.strip() != widget.title:
            title = self._check_free(title)
            del self.graphs[widget.title]
            widget.set_title(title)
            self.graphs[title] = widget
            self.graph_renamed.emit(widget)
        self.custom_changed.emit()

    def remove(self, widget: GraphWidget) -> None:
        """Forget a custom graph; the window deletes its dock."""
        if self.graphs.get(widget.title) is widget and widget.custom:
            del self.graphs[widget.title]
            self.custom_changed.emit()

    def _edit(self, widget: GraphWidget) -> None:
        dialog = GraphDialog(widget)
        while dialog.exec() == QDialog.Accepted:
            try:
                self.rename(widget, dialog.title.text())
            except ValueError as e:
                QMessageBox.warning(dialog, "Graph", str(e))
                continue
            widget.set_axes(
                Axis(dialog.x.text().strip()), Axis(dialog.y.text().strip())
            )
            self.custom_changed.emit()
            return

    def feed(
        self,
        measurement: Measurement,
        specs,
        table: str,
        record,
        window: Optional[float] = None,
    ) -> List[str]:
        """A live record of a running measurement; returns the graphs it reached."""
        reached = []
        for spec in specs:
            if spec.table != table or not spec.accepts(record):
                continue
            widget = self.graph(spec.title)
            if isinstance(widget, MapGraphWidget):
                widget.add_record(record)
                reached.append(spec.title)
                continue
            group = spec.group_key(record)
            key = (measurement.id, spec.table, spec.x, spec.y, group)
            if widget.append(
                key, curve_name(measurement, group), record.get(spec.x),
                record.get(spec.y), window,
            ):  # fmt: skip
                reached.append(spec.title)
        return reached

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
                    measurement, spec.table, spec.x, spec.y, spec.group_by,
                    spec.where,
                )  # fmt: skip
            shown.append(spec.title)
        return shown

    def monitor_value(
        self,
        device: str,
        title: str,
        quantity,
        t: float,
        value,
        window: Optional[float] = None,
    ) -> Optional[str]:
        """A value read in a device dock; returns its graph if it was plotted."""
        graph_title = plot_for(quantity)
        widget = self.graph(graph_title)
        name = f"{title} {quantity.title}"
        if widget.append(("monitor", device, quantity.key), name, t, value, window):
            return graph_title
        return None


class GraphDialog(QDialog):
    """Title and axis labels of a custom graph."""

    def __init__(self, graph: GraphWidget, parent=None):
        super().__init__(parent or graph)
        self.setWindowTitle(f"Graph {graph.title}")
        form = QFormLayout()
        self.title = QLineEdit(graph.title)
        self.x = QLineEdit(graph.x.label)
        self.y = QLineEdit(graph.y.label)
        self.x.setPlaceholderText("from the first curve")
        self.y.setPlaceholderText("from the first curve")
        form.addRow("Title", self.title)
        form.addRow("X axis", self.x)
        form.addRow("Y axis", self.y)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)


class AddCurveDialog(QDialog):
    """Pick a measurement, its table and the columns for x and y."""

    def __init__(
        self, measurements: List[Measurement], graph: GraphWidget, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Add curve to {graph.title}")
        self.measurements = [m for m in measurements if m.tables]
        self.graph = graph
        form = QFormLayout()
        self.measurement = QComboBox()
        for m in self.measurements:
            self.measurement.addItem(
                f"{m.id}  {m.title or m.procedure}  {m.comment}", m
            )
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
        x, y, group = (
            self.x.currentData(),
            self.y.currentData(),
            self.group.currentData(),
        )
        table = m.tables[name]
        if not self.graph.items and not self.graph.x.label:
            self.graph.x = Axis.from_column(table.get_column(x))
            self.graph.y = Axis.from_column(table.get_column(y))
            self.graph._label("bottom", self.graph.x)
            self.graph._label("left", self.graph.y)
        if not self.graph.add_columns(m, name, x, y, (group,) if group else ()):
            QMessageBox.information(self, "Add curve", "No points to plot")
        self.accept()
