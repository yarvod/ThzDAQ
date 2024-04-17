import logging
import re
from typing import Iterable

from PyQt5 import QtGui
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout
import pyqtgraph as pg


logger = logging.getLogger(__name__)


class GraphWindow(QWidget):
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
        vlayout = QVBoxLayout()
        hlayout = QHBoxLayout()
        self.graphWidget = pg.PlotWidget()
        self.btnRemoveHiddenCurves = QPushButton("Remove hidden curves")
        self.btnRemoveHiddenCurves.clicked.connect(self.remove_hidden_graphs)
        self.btnRemoveAllCurves = QPushButton("Remove all curves")
        self.btnRemoveAllCurves.clicked.connect(self.remove_all_graphs)
        hlayout.addWidget(self.btnRemoveHiddenCurves)
        hlayout.addWidget(self.btnRemoveAllCurves)
        vlayout.addLayout(hlayout)
        vlayout.addWidget(self.graphWidget)
        self.prepare()
        self.setLayout(vlayout)

    def get_plot_items(self):
        plotItem = self.graphWidget.getPlotItem()
        return {item.name(): item for item in plotItem.items}

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

    def plotNew(
        self,
        x: Iterable,
        y: Iterable,
        new_plot: bool = True,
        measure_id=None,
        legend_postfix="",
    ) -> str:
        items = self.get_plot_items()

        def get_id(name: str):
            val = next((_ for _ in re.findall(r"№ (\d+);", name)), 0)
            return int(val)

        plot_num = max([get_id(name) for name in items.keys()], default=0)
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
            return graph_id

        pen = pg.mkPen(color=self.get_color(plot_num), width=2)
        self.graphWidget.plot(
            x, y, name=f"{graph_id}", pen=pen, symbolSize=6, symbolBrush=pen.color()
        )
        return graph_id

    def remove_hidden_graphs(self):
        plotItem = self.graphWidget.getPlotItem()
        items_to_remove = {
            item.name(): item for item in plotItem.items if not item.isVisible()
        }
        for item in items_to_remove.values():
            plotItem.removeItem(item)

    def remove_all_graphs(self):
        plotItem = self.graphWidget.getPlotItem()
        items_to_remove = {item.name(): item for item in plotItem.items}
        for item in items_to_remove.values():
            plotItem.removeItem(item)
