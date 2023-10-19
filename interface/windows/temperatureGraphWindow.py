import logging
from collections import defaultdict

from PyQt5 import QtGui
from PyQt5.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg

from store.state import state

logger = logging.getLogger(__name__)


class TemperatureGraphWindow(QWidget):
    window_title = "Temperature graphs"
    graph_title = "Temperature (time)"
    y_label = "Temperature, K"
    x_label = "Time, s"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.window_title)
        self.setWindowIcon(QtGui.QIcon("./assets/logo_small.png"))
        layout = QVBoxLayout()
        self.graphWidget = pg.PlotWidget()
        layout.addWidget(self.graphWidget)
        self.dataset = defaultdict(dict[str, list])
        self.prepare()
        self.setLayout(layout)

    def get_color(self, ds_id: str):
        if ds_id == "A":
            return pg.intColor(1 * 10, 100)
        elif ds_id == "C":
            return pg.intColor(7 * 10, 100)

    def prepare(self) -> None:
        self.graphWidget.setBackground("w")
        self.graphWidget.setTitle(self.graph_title, color="#413C58", size="20pt")
        styles = {"color": "#413C58", "font-size": "15px"}
        self.graphWidget.setLabel("left", self.y_label, **styles)
        self.graphWidget.setLabel("bottom", self.x_label, **styles)
        self.graphWidget.addLegend()
        self.graphWidget.showGrid(x=True, y=True)

    def plotGraph(self, ds_id: str) -> None:
        try:
            x = self.dataset[ds_id]["x"]
            y = self.dataset[ds_id]["y"]
        except (IndexError, KeyError) as e:
            logger.error(f"Plot graph Error: {e}")
            return

        plotItem = self.graphWidget.getPlotItem()
        items = {item.name(): item for item in plotItem.items}
        if items.get(ds_id):
            items.get(ds_id).setData(x, y)
            return
        pen = pg.mkPen(color=self.get_color(ds_id), width=2)
        self.graphWidget.plot(
            x, y, name=ds_id, pen=pen, symbolSize=6, symbolBrush=pen.color()
        )

    def addData(self, ds_id: str, x: float, y: float, reset_data: bool = True) -> None:
        if reset_data:
            self.dataset[ds_id]["y"] = [y]
            self.dataset[ds_id]["x"] = [x]
            return

        if max(self.dataset[ds_id]["x"]) >= state.LAKE_SHORE_STREAM_TIME:
            del self.dataset[ds_id]["y"][0]
            del self.dataset[ds_id]["x"][0]

        self.dataset[ds_id]["y"].append(y)
        self.dataset[ds_id]["x"].append(x)

    def plotNew(self, ds_id: str, x: float, y: float, reset_data: bool = True) -> None:
        self.addData(ds_id=ds_id, x=x, y=y, reset_data=reset_data)
        self.plotGraph(ds_id)
