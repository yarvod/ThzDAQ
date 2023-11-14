import logging
from collections import defaultdict
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
        return {int(item.name()): item for item in plotItem.items}

    def prepare(self) -> None:
        self.graphWidget.setBackground("w")
        self.graphWidget.setTitle(self.graph_title, color="#413C58", size="20pt")
        styles = {"color": "#413C58", "font-size": "15px"}
        self.graphWidget.setLabel("left", self.y_label, **styles)
        self.graphWidget.setLabel("bottom", self.x_label, **styles)
        self.graphWidget.addLegend()
        self.graphWidget.showGrid(x=True, y=True)

    def plotGraph(self, x: Iterable, y: Iterable, new_plot: bool = True):
        items = self.get_plot_items()
        ds_id = max(items.keys(), default=0)
        if new_plot:
            ds_id += 1

        if items.get(ds_id):
            item = items.get(ds_id)
            x_data = list(item.xData)
            x_data.extend(x)
            y_data = list(item.yData)
            y_data.extend(y)
            items.get(ds_id).setData(x_data, y_data)
            return ds_id

        pen = pg.mkPen(color=pg.intColor(ds_id * 10, 100), width=2)
        self.graphWidget.plot(
            x, y, name=f"{ds_id}", pen=pen, symbolSize=6, symbolBrush=pen.color()
        )
        return ds_id

    def addData(self, x: Iterable, y: Iterable, new_plot: bool = True) -> int:
        ds_id = max(self.datasets.keys(), default=0)
        if new_plot:
            ds_id += 1
        if not self.datasets[ds_id].get("x"):
            self.datasets[ds_id]["x"] = x
        else:
            self.datasets[ds_id]["x"].extend(x)
        if not self.datasets[ds_id].get("y"):
            self.datasets[ds_id]["y"] = y
        else:
            self.datasets[ds_id]["y"].extend(y)
        return ds_id

    def plotNew(self, x: Iterable, y: Iterable, new_plot: bool = True) -> int:
        return self.plotGraph(x, y, new_plot)

    def remove_hidden_graphs(self):
        plotItem = self.graphWidget.getPlotItem()
        items_to_remove = {
            int(item.name()): item for item in plotItem.items if not item.isVisible()
        }
        for item in items_to_remove.values():
            plotItem.removeItem(item)

    def remove_all_graphs(self):
        plotItem = self.graphWidget.getPlotItem()
        items_to_remove = {int(item.name()): item for item in plotItem.items}
        for item in items_to_remove.values():
            plotItem.removeItem(item)
