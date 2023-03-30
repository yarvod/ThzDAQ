from PyQt6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg


class GraphWindow(QWidget):
    def __init__(self, x: list, y: list):
        super().__init__()
        layout = QVBoxLayout()
        self.graphWidget = pg.PlotWidget()
        layout.addWidget(self.graphWidget)
        self.x = x
        self.y = y
        self.showGraph()
        self.setLayout(layout)

    def showGraph(self) -> None:
        # Add Background colour to white
        self.graphWidget.setBackground("w")
        # Add Title
        self.graphWidget.setTitle(
            "BIAS current (CL current)", color="#413C58", size="20pt"
        )
        # Add Axis Labels
        styles = {"color": "#413C58", "font-size": "15px"}
        self.graphWidget.setLabel("left", "BIAS Current, mkA", **styles)
        self.graphWidget.setLabel("bottom", "CL Current, mA", **styles)
        # Add legend
        self.graphWidget.addLegend()
        # Add grid
        self.graphWidget.showGrid(x=True, y=True)
        # Set Range
        self.graphWidget.setXRange(0, 10)
        self.graphWidget.setYRange(20, 55)

        pen = pg.mkPen(color="#303036")
        self.graphWidget.plot(
            self.x,
            self.y,
            name="BIAS current(CL current)",
            pen=pen,
            symbolSize=10,
        )
