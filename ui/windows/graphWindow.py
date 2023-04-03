import logging
from typing import Iterable

from PyQt6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg


logger = logging.getLogger(__name__)


class GraphWindow(QWidget):
    window_title = "Graph"
    graph_title = "Base Graph"
    y_label = "y label"
    x_label = "x label"

    def __init__(self, x: Iterable, y: Iterable):
        super().__init__()
        self.setWindowTitle(self.window_title)
        layout = QVBoxLayout()
        self.datasets = []
        self.graphWidget = pg.PlotWidget()
        layout.addWidget(self.graphWidget)
        self.prepare()
        self.plotNew(x, y)
        self.setLayout(layout)

    def prepare(self) -> None:
        self.graphWidget.setBackground("w")
        self.graphWidget.setTitle(self.graph_title, color="#413C58", size="20pt")
        styles = {"color": "#413C58", "font-size": "15px"}
        self.graphWidget.setLabel("left", self.y_label, **styles)
        self.graphWidget.setLabel("bottom", self.x_label, **styles)
        self.graphWidget.addLegend()
        self.graphWidget.showGrid(x=True, y=True)

    def plotGraph(self, index: int = 0):
        pen = pg.mkPen(color="#303036")
        try:
            x = self.datasets[index]["x"]
            y = self.datasets[index]["y"]
        except (IndexError, KeyError) as e:
            logger.error(f"Plot graph Error: {e}")
            return
        self.graphWidget.plot(
            x,
            y,
            name=f"{index + 1}",
            pen=pen,
            symbolSize=10,
        )

    def addData(self, x: Iterable, y: Iterable) -> int:
        self.datasets.append({"x": x, "y": y})
        return len(self.datasets) - 1

    def plotNew(self, x: Iterable, y: Iterable):
        index = self.addData(x, y)
        self.plotGraph(index)
