import logging
from typing import List

from PySide6 import QtGui
from PySide6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg


logger = logging.getLogger(__name__)


class SpectrumGraphWindow(QWidget):
    window_title = "Spectrum graph"
    graph_title = "Spectrum"
    y_label = "Power, dB"
    x_label = "Frequency, Hz"

    def __init__(self, parent):
        super().__init__(parent)
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
        self.graphWidget.setTitle(self.graph_title, color="#413C58", size="10pt")
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

        pen = pg.mkPen(color="#0000FF", width=2)
        self.graphWidget.plot(
            x, y, name="Stream", pen=pen, symbolSize=6, symbolBrush=pen.color()
        )

    def addData(self, x: List, y: List) -> None:
        self.dataset["y"] = y
        self.dataset["x"] = x

    def plotNew(self, x: List, y: List) -> None:
        self.addData(x=x, y=y)
        self.plotGraph()
