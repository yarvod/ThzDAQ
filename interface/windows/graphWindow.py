import logging
import re
from typing import Iterable

from PySide6 import QtGui
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout
import pyqtgraph as pg


logger = logging.getLogger(__name__)


class GraphWindow(QWidget):
    curves_changed = Signal()

    window_title = "Graph"
    graph_title = "Base Graph"
    y_label = "y label"
    x_label = "x label"
    colors = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowIcon(QtGui.QIcon("./assets/logo_small.png"))
        self.setWindowTitle(self.window_title)
        self.main_layout = QVBoxLayout()
        self.actions_layout = QHBoxLayout()
        self.graphWidget = pg.PlotWidget()
        self.btnRemoveHiddenCurves = QPushButton("Remove hidden curves")
        self.btnRemoveHiddenCurves.clicked.connect(self.remove_hidden_graphs)
        self.btnRemoveAllCurves = QPushButton("Remove all curves")
        self.btnRemoveAllCurves.clicked.connect(self.remove_all_graphs)
        self.actions_layout.addWidget(self.btnRemoveHiddenCurves)
        self.actions_layout.addWidget(self.btnRemoveAllCurves)
        self.main_layout.addLayout(self.actions_layout)
        self.main_layout.addWidget(self.graphWidget)
        self.prepare()
        self.setLayout(self.main_layout)

    def get_plot_items(self):
        plotItem = self.graphWidget.getPlotItem()
        return {
            item.name(): item
            for item in plotItem.listDataItems()
            if item.name() is not None
        }

    def prepare(self) -> None:
        self.graphWidget.setBackground("w")
        self.graphWidget.setTitle(self.graph_title, color="#413C58", size="10pt")
        styles = {"color": "#413C58", "font-size": "15px"}
        self.graphWidget.setLabel("left", self.y_label, **styles)
        self.graphWidget.setLabel("bottom", self.x_label, **styles)
        self.graphWidget.addLegend()
        self.graphWidget.showGrid(x=True, y=True)

    def get_color(self, ind):
        number = ind % len(self.colors) - 1 if ind >= 1 else 0
        return self.colors[number]

    @staticmethod
    def get_plot_number(name: str):
        val = next((_ for _ in re.findall(r"№ (\d+);", name)), 0)
        return int(val)

    def get_last_plot_number(self):
        items = self.get_plot_items()
        plot_number = max(
            [self.get_plot_number(name) for name in items.keys()], default=0
        )
        print(f"PLOT_NUMBER {plot_number}")
        return plot_number

    def plotNew(
        self,
        x: Iterable,
        y: Iterable,
        new_plot: bool = True,
        measure_id=None,
        legend_postfix="",
    ) -> str:
        items = self.get_plot_items()

        plot_num = max([self.get_plot_number(name) for name in items.keys()], default=0)
        if new_plot:
            plot_num += 1
        graph_id = f"id {measure_id}; № {plot_num}; {legend_postfix}"

        if items.get(graph_id):
            item = items.get(graph_id)
            x_data = list(item.xData)
            x_data.extend(x)
            y_data = list(item.yData)
            y_data.extend(y)
            items.get(graph_id).setData(x_data, y_data)
            self.curves_changed.emit()
            return graph_id

        pen = pg.mkPen(color=self.get_color(plot_num), width=2)
        self.graphWidget.plot(
            x, y, name=f"{graph_id}", pen=pen, symbolSize=6, symbolBrush=pen.color()
        )
        self.curves_changed.emit()
        return graph_id

    def plot(
        self,
        x: Iterable,
        y: Iterable,
        plot_num=None,
        measure_id=None,
        legend_postfix="",
    ) -> str:
        items = self.get_plot_items()

        if not plot_num:
            plot_num = max(
                [self.get_plot_number(name) for name in items.keys()], default=1
            )

        graph_id = f"id {measure_id}; № {plot_num}; {legend_postfix}"

        if items.get(graph_id):
            item = items.get(graph_id)
            x_data = list(item.xData)
            x_data.extend(x)
            y_data = list(item.yData)
            y_data.extend(y)
            items.get(graph_id).setData(x_data, y_data)
            self.curves_changed.emit()
            return plot_num

        pen = pg.mkPen(color=self.get_color(plot_num), width=2)
        self.graphWidget.plot(
            x, y, name=f"{graph_id}", pen=pen, symbolSize=6, symbolBrush=pen.color()
        )
        self.curves_changed.emit()
        return plot_num

    def remove_hidden_graphs(self):
        plotItem = self.graphWidget.getPlotItem()
        items_to_remove = [
            item for item in plotItem.listDataItems() if not item.isVisible()
        ]
        for item in items_to_remove:
            plotItem.removeItem(item)
        if items_to_remove:
            self.curves_changed.emit()

    def remove_all_graphs(self):
        plotItem = self.graphWidget.getPlotItem()
        items_to_remove = list(plotItem.listDataItems())
        for item in items_to_remove:
            plotItem.removeItem(item)
        if items_to_remove:
            self.curves_changed.emit()
