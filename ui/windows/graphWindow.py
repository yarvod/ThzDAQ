import logging
from collections import defaultdict
from typing import Iterable

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton
import pyqtgraph as pg


logger = logging.getLogger(__name__)


class GraphWindow(QWidget):
    window_title = "Graph"
    graph_title = "Base Graph"
    y_label = "y label"
    x_label = "x label"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.window_title)
        layout = QVBoxLayout()
        self.graphWidget = pg.PlotWidget()
        self.btnRemoveGraphs = QPushButton("Remove hidden graphs")
        self.btnRemoveGraphs.clicked.connect(self.remove_hidden_graphs)
        layout.addWidget(self.btnRemoveGraphs)
        layout.addWidget(self.graphWidget)
        self.datasets = defaultdict(dict)
        self.prepare()
        self.setLayout(layout)

    def prepare(self) -> None:
        self.graphWidget.setBackground("w")
        self.graphWidget.setTitle(self.graph_title, color="#413C58", size="20pt")
        styles = {"color": "#413C58", "font-size": "15px"}
        self.graphWidget.setLabel("left", self.y_label, **styles)
        self.graphWidget.setLabel("bottom", self.x_label, **styles)
        self.graphWidget.addLegend()
        self.graphWidget.showGrid(x=True, y=True)

    def plotGraph(self, ds_id: int = 1):
        pen = pg.mkPen(color=pg.intColor(ds_id * 10, 100))
        try:
            x = self.datasets[ds_id]["x"]
            y = self.datasets[ds_id]["y"]
        except (IndexError, KeyError) as e:
            logger.error(f"Plot graph Error: {e}")
            return
        self.graphWidget.plot(
            x, y, name=f"{ds_id}", pen=pen, symbolSize=5, symbolBrush=pen.color()
        )

    def addData(self, x: Iterable, y: Iterable) -> int:
        ds_id = max(self.datasets.keys(), default=0) + 1
        self.datasets[ds_id] = {"x": x, "y": y}
        return ds_id

    def plotNew(self, x: Iterable, y: Iterable):
        ds_id = self.addData(x, y)
        self.plotGraph(ds_id)
        return ds_id

    def remove_hidden_graphs(self):
        plotItem = self.graphWidget.getPlotItem()
        items_to_remove = {
            int(item.name()): item for item in plotItem.items if not item.isVisible()
        }
        for item in items_to_remove.values():
            plotItem.removeItem(item)
        self.datasets = {
            ds_id: ds
            for ds_id, ds in self.datasets.items()
            if ds_id not in items_to_remove.keys()
        }
