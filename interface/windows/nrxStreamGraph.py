import logging

from PySide6 import QtGui
from PySide6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg

from store.powerMeterUnitsModel import power_meter_unit_model
from store.state import state


logger = logging.getLogger(__name__)


class NRXStreamGraphWindow(QWidget):
    window_title = "Power Meter Stream Graph"
    graph_title = "Power (time)"
    y_label = "Power, dBm"
    x_label = "Time, s"

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(self.window_title)
        self.setWindowIcon(QtGui.QIcon("./assets/logo_small.png"))
        layout = QVBoxLayout()
        self.graphWidget = pg.PlotWidget()
        layout.addWidget(self.graphWidget)
        self.dataset = {"y": [], "x": []}
        self.prepare()
        self.setLayout(layout)
        power_meter_unit_model.value_pretty.connect(
            lambda x: self.graphWidget.setLabel("left", f"Power, {x}", **self.styles)
        )

    def prepare(self) -> None:
        self.graphWidget.setBackground("w")
        self.graphWidget.setTitle(self.graph_title, color="#413C58", size="10pt")
        self.styles = {"color": "#413C58", "font-size": "15px"}
        self.graphWidget.setLabel("left", self.y_label, **self.styles)
        self.graphWidget.setLabel("bottom", self.x_label, **self.styles)
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

    def addData(self, x: float, y: float, reset_data: bool = True) -> None:
        if reset_data:
            self.dataset["y"] = [y]
            self.dataset["x"] = [x]
            return

        if max(self.dataset["x"]) >= state.NRX_STREAM_GRAPH_TIME:
            del self.dataset["y"][0]
            del self.dataset["x"][0]

        self.dataset["y"].append(y)
        self.dataset["x"].append(x)

    def plotNew(self, x: float, y: float, reset_data: bool = True) -> None:
        self.addData(x=x, y=y, reset_data=reset_data)
        self.plotGraph()
