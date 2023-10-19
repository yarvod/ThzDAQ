from typing import List

from PyQt5 import QtGui
from PyQt5.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg

from utils.logger import logger


class SpectrumGraphWindow(QWidget):
    window_title = "Spectrum graph"
    graph_title = "Spectrum"
    y_label = "Power, dB"
    x_label = "Frequency, Hz"

    def __init__(self):
        super().__init__()
        self.setWindowIcon(QtGui.QIcon("./assets/logo_small.png"))
        self.setWindowTitle(self.window_title)
        layout = QVBoxLayout()
        self.graphWidget = pg.PlotWidget()
        layout.addWidget(self.graphWidget)
        self.dataset = {"y": [], "x": []}
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

    def plotGraph(self) -> None:
        try:
            x = self.dataset["x"]
            y = self.dataset["y"]
        except (IndexError, KeyError) as e:
            logger.error(f"Plot graph Error: {e}")
            return

        plotItem = self.graphWidget.getPlotItem()
        items = {item.name(): item for item in plotItem.items}
        if items.get("Stream"):
            items.get("Stream").setData(x, y)
            return

        pen = pg.mkPen(color="#0000FF")
        self.graphWidget.plot(
            x, y, name="Stream", pen=pen, symbolSize=5, symbolBrush=pen.color()
        )

    def addData(self, x: List, y: List) -> None:
        self.dataset["y"] = y
        self.dataset["x"] = x

    def plotNew(self, x: List, y: List) -> None:
        self.addData(x=x, y=y)
        self.plotGraph()
