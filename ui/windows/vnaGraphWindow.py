import logging
from typing import Iterable

from PyQt6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg


logger = logging.getLogger(__name__)


class VNAGraphWindow(QWidget):
    datasets = []

    def __init__(self, x: Iterable, y: Iterable):
        super().__init__()
        layout = QVBoxLayout()
        self.graphWidget = pg.PlotWidget()
        layout.addWidget(self.graphWidget)
        self.prepare()
        self.plotNew(x, y)
        self.setLayout(layout)

    def prepare(self) -> None:
        self.graphWidget.setBackground("w")
        self.graphWidget.setTitle(
            "Reflection (Intermediate frequency)", color="#413C58", size="20pt"
        )
        styles = {"color": "#413C58", "font-size": "15px"}
        self.graphWidget.setLabel("left", "Reflection level, dB", **styles)
        self.graphWidget.setLabel("bottom", "Intermediate frequency, GHz", **styles)
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
