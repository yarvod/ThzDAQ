import logging

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QDoubleSpinBox,
    QLineEdit,
)

from config import BLOCK_ADDRESS, BLOCK_PORT
from interactors.block import Block
from ui.windows.graphWindow import GraphWindow

logger = logging.getLogger(__name__)


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
