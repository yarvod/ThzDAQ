import sys
import logging

from PyQt6.QtWidgets import *
import pyqtgraph as pg

from block import Block
from config import BLOCK_ADDRESS, BLOCK_PORT, BLOCK_BIAS_DEV, BLOCK_CTRL_DEV


logger = logging.getLogger(__name__)


def update_block(block_ip, block_port):
    block = Block(block_ip, block_port)
    block.host = block_ip
    block.port = int(block_port)
    result = block.get_bias_data()
    logger.info(f"Health check bias {result}")


class UtilsMixin:
    @property
    def block(self):
        return Block(BLOCK_ADDRESS, BLOCK_PORT)

    def updateValues(self):
        current = self.block.get_bias_current()
        self.current_g.setText(f"{round(current * 1e6, 3)}")
        voltage = self.block.get_bias_voltage()
        self.voltage_g.setText(f"{round(voltage * 1e3, 3)}")
        ctrlCurrentGet = self.block.get_ctrl_current()
        self.ctrlCurrentGet.setText(f"{round(ctrlCurrentGet * 1e3, 3)}")

    def set_voltage(self):
        try:
            voltage_to_set = float(self.voltage_s.text().replace(",", ".")) * 1e-3
        except ValueError:
            logger.warning(f"Value {self.voltage_s.text()} is not correct float")
            return
        self.block.set_bias_voltage(voltage_to_set)
        current = self.block.get_bias_current()
        self.current_g.setText(f"{round(current * 1e6, 3)}")
        voltage = self.block.get_bias_voltage()
        self.voltage_g.setText(f"{round(voltage * 1e3, 3)}")

    def set_ctrl_current(self):
        try:
            ctrlCurrentSet = float(self.ctrlCurrentSet.text().replace(",", ".")) * 1e-3
        except ValueError:
            logger.warning(f"Value {self.ctrlCurrentSet.text()} is not correct float")
            return
        self.block.set_ctrl_current(ctrlCurrentSet)
        ctrlCurrentGet = self.block.get_ctrl_current()
        self.ctrlCurrentGet.setText(f"{round(ctrlCurrentGet * 1e3, 3)}")

    def get_voltage_current(self):
        current = self.block.get_bias_current()
        self.current_g.setText(f"{round(current * 1e6, 3)}")
        voltage = self.block.get_bias_voltage()
        self.voltage_g.setText(f"{round(voltage * 1e3, 3)}")

    def scan_ctrl_current(self):
        try:
            ctrl_i_from = float(self.ctrlCurrentFrom.text().replace(",", ".")) * 1e-3
            ctrl_i_to = float(self.ctrlCurrentTo.text().replace(",", ".")) * 1e-3
            points_num = int(self.ctrlPoints.text())
        except ValueError:
            logger.warning(f"Range values is not correct floats/ints")
            return
        results = self.block.scan_ctrl_current(ctrl_i_from, ctrl_i_to, points_num)
        self.show_graph_window(x=results["ctrl_i_get"], y=results["bias_i"])


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.title = "CL manager"
        self.left = 0
        self.top = 0
        self.width = 400
        self.height = 300
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

        self.table_widget = TabsWidget(self)
        self.setCentralWidget(self.table_widget)

        self.show()


class TabsWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)

        # Initialize tab screen
        self.tabs = QTabWidget(self)
        self.tab_setup = SetUpTabWidget(self)
        self.tab_block = BlockTabWidget(self)
        self.tabs.resize(300, 200)

        # Add tabs
        self.tabs.addTab(self.tab_setup, "Set Up")
        self.tabs.addTab(self.tab_block, "SIS Block")

        # Add tabs to widget
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)


class SetUpTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.createGridGroupBox()
        self.layout.addWidget(self.gridGroupBox)
        self.setLayout(self.layout)

    def createGridGroupBox(self):
        self.gridGroupBox = QGroupBox("Block config")
        layout = QGridLayout()

        self.blockIPLabel = QLabel(self)
        self.blockIPLabel.setText("Block IP:")
        self.block_ip = QLineEdit(self)
        self.block_ip.setText(BLOCK_ADDRESS)

        self.blockPortLabel = QLabel(self)
        self.blockPortLabel.setText("Block Port:")
        self.block_port = QLineEdit(self)
        self.block_port.setText(str(BLOCK_PORT))

        self.ctrlDevLabel = QLabel(self)
        self.biasDevLabel = QLabel(self)
        self.ctrlDev = QLineEdit(self)
        self.biasDev = QLineEdit(self)
        self.ctrlDevLabel.setText("CTRL Device:")
        self.biasDevLabel.setText("BIAS Device:")
        self.ctrlDev.setText(BLOCK_CTRL_DEV)
        self.biasDev.setText(BLOCK_BIAS_DEV)

        self.btnCheck = QPushButton("Check connection")
        self.btnCheck.clicked.connect(
            lambda: update_block(self.block_ip.text(), self.block_port.text())
        )

        layout.addWidget(self.blockIPLabel, 1, 0)
        layout.addWidget(self.block_ip, 1, 1)
        layout.addWidget(self.blockPortLabel, 2, 0)
        layout.addWidget(self.block_port, 2, 1)
        layout.addWidget(self.ctrlDevLabel, 3, 0)
        layout.addWidget(self.ctrlDev, 3, 1)
        layout.addWidget(self.biasDevLabel, 4, 0)
        layout.addWidget(self.biasDev, 4, 1)
        layout.addWidget(self.btnCheck, 5, 0, 1, 2)

        self.gridGroupBox.setLayout(layout)


class BlockTabWidget(QWidget, UtilsMixin):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.graphWindow = None
        self.createGroupValuesGet()
        self.createGroupValuesSet()
        self.createGroupCTRLScan()
        self.layout.addWidget(self.rowValuesGet)
        self.layout.addWidget(self.rowValuesSet)
        self.layout.addWidget(self.rowCTRLScan)
        self.setLayout(self.layout)

    def show_graph_window(self, x: list, y: list):
        self.graphWindow = GraphWindow(x=x, y=y)
        self.graphWindow.show()

    def createGroupValuesGet(self):
        self.rowValuesGet = QGroupBox("Get values")
        layout = QGridLayout()

        self.voltGLabel = QLabel(self)
        self.voltGLabel.setText("BIAS voltage, mV:")
        self.voltage_g = QLabel(self)

        self.currGLabel = QLabel(self)
        self.currGLabel.setText("BIAS current, mkA:")
        self.current_g = QLabel(self)

        self.ctrlCurrentGetLabel = QLabel(self)
        self.ctrlCurrentGetLabel.setText("CL current, mA:")
        self.ctrlCurrentGet = QLabel(self)

        self.btnUpdateValues = QPushButton("Update")
        self.btnUpdateValues.clicked.connect(self.updateValues)

        layout.addWidget(self.voltGLabel, 1, 0)
        layout.addWidget(self.voltage_g, 1, 1)
        layout.addWidget(self.currGLabel, 2, 0)
        layout.addWidget(self.current_g, 2, 1)
        layout.addWidget(self.ctrlCurrentGetLabel, 3, 0)
        layout.addWidget(self.ctrlCurrentGet, 3, 1)
        layout.addWidget(self.btnUpdateValues, 4, 0, 1, 2)

        self.rowValuesGet.setLayout(layout)

    def createGroupValuesSet(self):
        self.rowValuesSet = QGroupBox("Set values")
        layout = QGridLayout()

        self.voltSLabel = QLabel(self)
        self.voltSLabel.setText("BIAS voltage, mV:")
        self.voltage_s = QDoubleSpinBox(self)

        self.btn_set_voltage = QPushButton("Set BIAS voltage")
        self.btn_set_voltage.clicked.connect(lambda: self.set_voltage())

        self.ctrlCurrentSetLabel = QLabel(self)
        self.ctrlCurrentSetLabel.setText("CL current, mA")
        self.ctrlCurrentSet = QDoubleSpinBox(self)

        self.btnSetCTRLCurrent = QPushButton("Set CL current")
        self.btnSetCTRLCurrent.clicked.connect(self.set_ctrl_current)

        layout.addWidget(self.voltSLabel, 1, 0)
        layout.addWidget(self.voltage_s, 1, 1)
        layout.addWidget(self.btn_set_voltage, 1, 2)
        layout.addWidget(self.ctrlCurrentSetLabel, 2, 0)
        layout.addWidget(self.ctrlCurrentSet, 2, 1)
        layout.addWidget(self.btnSetCTRLCurrent, 2, 2)

        self.rowValuesSet.setLayout(layout)

    def createGroupCTRLScan(self):
        self.rowCTRLScan = QGroupBox("Scan CTRL current")
        layout = QGridLayout()

        self.ctrlCurrentFromLabel = QLabel(self)
        self.ctrlCurrentFromLabel.setText("CL Current from, mA")
        self.ctrlCurrentFrom = QDoubleSpinBox(self)
        self.ctrlCurrentToLabel = QLabel(self)
        self.ctrlCurrentToLabel.setText("CL Current to, mA")
        self.ctrlCurrentTo = QDoubleSpinBox(self)
        self.ctrlPointsLabel = QLabel(self)
        self.ctrlPointsLabel.setText("Points num")
        self.ctrlPoints = QLineEdit(self)
        self.ctrlPoints.setText("50")
        self.btnCTRLScan = QPushButton("Scan CL Current")
        self.btnCTRLScan.clicked.connect(lambda: self.scan_ctrl_current())

        layout.addWidget(self.ctrlCurrentFromLabel, 1, 0)
        layout.addWidget(self.ctrlCurrentFrom, 1, 1)
        layout.addWidget(self.ctrlCurrentToLabel, 2, 0)
        layout.addWidget(self.ctrlCurrentTo, 2, 1)
        layout.addWidget(self.ctrlPointsLabel, 3, 0)
        layout.addWidget(self.ctrlPoints, 3, 1)
        layout.addWidget(self.btnCTRLScan, 4, 0, 1, 2)

        self.rowCTRLScan.setLayout(layout)


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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = App()
    sys.exit(app.exec())
