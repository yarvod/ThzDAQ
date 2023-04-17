import logging

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QDoubleSpinBox,
    QFileDialog,
)
from PyQt6.QtCore import Qt

from config import (
    BLOCK_ADDRESS,
    BLOCK_PORT,
    BLOCK_CTRL_POINTS_MAX,
    BLOCK_CTRL_POINTS,
    BLOCK_BIAS_VOLT_POINTS,
    BLOCK_BIAS_VOLT_POINTS_MAX,
    BLOCK_BIAS_VOLT_MIN_VALUE,
    BLOCK_BIAS_VOLT_MAX_VALUE,
    BLOCK_CTRL_CURR_MAX_VALUE,
    BLOCK_CTRL_CURR_MIN_VALUE,
)
from interactors.block import Block
from ui.windows.biasGraphWindow import BiasGraphWindow
from ui.windows.clGraphWindow import CLGraphWindow

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
            voltage_to_set = float(self.voltage_s.value()) * 1e-3
        except ValueError:
            logger.warning(f"Value {self.voltage_s.value()} is not correct float")
            return
        self.block.set_bias_voltage(voltage_to_set)
        current = self.block.get_bias_current()
        self.current_g.setText(f"{round(current * 1e6, 3)}")
        voltage = self.block.get_bias_voltage()
        self.voltage_g.setText(f"{round(voltage * 1e3, 3)}")

    def set_ctrl_current(self):
        try:
            ctrlCurrentSet = float(self.ctrlCurrentSet.value()) * 1e-3
        except ValueError:
            logger.warning(f"Value {self.ctrlCurrentSet.value()} is not correct float")
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
            ctrl_i_from = float(self.ctrlCurrentFrom.value()) * 1e-3
            ctrl_i_to = float(self.ctrlCurrentTo.value()) * 1e-3
            points_num = int(self.ctrlPoints.value())
        except ValueError:
            logger.warning(f"Range values is not correct floats/ints")
            return
        results = self.block.scan_ctrl_current(ctrl_i_from, ctrl_i_to, points_num)
        self.show_ctrl_graph_window(x=results["ctrl_i_get"], y=results["bias_i"])

    def scan_bias_iv(self):
        try:
            bias_v_from = float(self.biasVoltageFrom.value()) * 1e-3
            bias_v_to = float(self.biasVoltageTo.value()) * 1e-3
            points_num = int(self.biasPoints.value())
        except ValueError:
            logger.warning(f"Range values is not correct floats/ints")
            return
        results = self.block.scan_bias(bias_v_from, bias_v_to, points_num)
        self.show_bias_graph_window(x=results["v_get"], y=results["i_get"])
        try:
            filepath = QFileDialog.getSaveFileName()[0]
            df = pd.DataFrame(
                dict(
                    v_set=results["v_set"],
                    v_get=results["v_get"],
                    i_get=results["i_get"],
                    time=results["time"],
                )
            )
            df.to_csv(filepath)
        except (IndexError, FileNotFoundError):
            pass


class BlockTabWidget(QWidget, UtilsMixin):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.ctrlGraphWindow = None
        self.biasGraphWindow = None
        self.createGroupValuesGet()
        self.createGroupValuesSet()
        self.createGroupCTRLScan()
        self.createGroupBiasScan()
        self.layout.addWidget(self.rowValuesGet)
        self.layout.addWidget(self.rowValuesSet)
        self.layout.addWidget(self.rowCTRLScan)
        self.layout.addWidget(self.rowBiasScan)
        self.setLayout(self.layout)

    def show_ctrl_graph_window(self, x: list, y: list):
        if self.ctrlGraphWindow is None:
            self.ctrlGraphWindow = CLGraphWindow(x=x, y=y)
        else:
            self.ctrlGraphWindow.plotNew(x, y)
        self.ctrlGraphWindow.show()

    def show_bias_graph_window(self, x: list, y: list):
        if self.biasGraphWindow is None:
            self.biasGraphWindow = BiasGraphWindow(x=x, y=y)
        else:
            self.biasGraphWindow.plotNew(x, y)
        self.biasGraphWindow.show()

    def createGroupValuesGet(self):
        self.rowValuesGet = QGroupBox("Get values")
        layout = QGridLayout()

        self.voltGLabel = QLabel(self)
        self.voltGLabel.setText("<h4>BIAS voltage, mV</h4>")
        self.voltage_g = QLabel(self)
        self.voltage_g.setText("0.0")
        self.voltage_g.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.currGLabel = QLabel(self)
        self.currGLabel.setText("<h4>BIAS current, mkA</h4>")
        self.current_g = QLabel(self)
        self.current_g.setText("0.0")
        self.current_g.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.ctrlCurrentGetLabel = QLabel(self)
        self.ctrlCurrentGetLabel.setText("<h4>CL current, mA</h4>")
        self.ctrlCurrentGet = QLabel(self)
        self.ctrlCurrentGet.setText("0.0")
        self.ctrlCurrentGet.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.btnUpdateValues = QPushButton("Update")
        self.btnUpdateValues.clicked.connect(self.updateValues)

        layout.addWidget(self.voltGLabel, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.currGLabel, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.ctrlCurrentGetLabel, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.voltage_g, 2, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.current_g, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.ctrlCurrentGet, 2, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.btnUpdateValues, 3, 0, 1, 3, alignment=Qt.AlignmentFlag.AlignCenter)

        self.rowValuesGet.setLayout(layout)

    def createGroupValuesSet(self):
        self.rowValuesSet = QGroupBox("Set values")
        layout = QGridLayout()

        self.voltSLabel = QLabel(self)
        self.voltSLabel.setText("BIAS voltage, mV:")
        self.voltage_s = QDoubleSpinBox(self)
        self.voltage_s.setRange(BLOCK_BIAS_VOLT_MIN_VALUE, BLOCK_BIAS_VOLT_MAX_VALUE)

        self.btn_set_voltage = QPushButton("Set BIAS voltage")
        self.btn_set_voltage.clicked.connect(lambda: self.set_voltage())

        self.ctrlCurrentSetLabel = QLabel(self)
        self.ctrlCurrentSetLabel.setText("CL current, mA")
        self.ctrlCurrentSet = QDoubleSpinBox(self)
        self.ctrlCurrentSet.setRange(
            BLOCK_CTRL_CURR_MIN_VALUE, BLOCK_CTRL_CURR_MAX_VALUE
        )

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
        self.ctrlCurrentFrom.setRange(
            BLOCK_CTRL_CURR_MIN_VALUE, BLOCK_CTRL_CURR_MAX_VALUE
        )
        self.ctrlCurrentToLabel = QLabel(self)
        self.ctrlCurrentToLabel.setText("CL Current to, mA")
        self.ctrlCurrentTo = QDoubleSpinBox(self)
        self.ctrlCurrentTo.setRange(
            BLOCK_CTRL_CURR_MIN_VALUE, BLOCK_CTRL_CURR_MAX_VALUE
        )
        self.ctrlPointsLabel = QLabel(self)
        self.ctrlPointsLabel.setText("Points num")
        self.ctrlPoints = QDoubleSpinBox(self)
        self.ctrlPoints.setDecimals(0)
        self.ctrlPoints.setMaximum(BLOCK_CTRL_POINTS_MAX)
        self.ctrlPoints.setValue(BLOCK_CTRL_POINTS)
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

    def createGroupBiasScan(self):
        self.rowBiasScan = QGroupBox("Scan Bias IV")
        layout = QGridLayout()

        self.biasVoltageFromLabel = QLabel(self)
        self.biasVoltageFromLabel.setText("Voltage from, mV")
        self.biasVoltageFrom = QDoubleSpinBox(self)
        self.biasVoltageFrom.setRange(
            BLOCK_BIAS_VOLT_MIN_VALUE, BLOCK_BIAS_VOLT_MAX_VALUE
        )
        self.biasVoltageToLabel = QLabel(self)
        self.biasVoltageToLabel.setText("Voltage to, mv")
        self.biasVoltageTo = QDoubleSpinBox(self)
        self.biasVoltageTo.setRange(
            BLOCK_BIAS_VOLT_MIN_VALUE, BLOCK_BIAS_VOLT_MAX_VALUE
        )
        self.biasPointsLabel = QLabel(self)
        self.biasPointsLabel.setText("Points num")
        self.biasPoints = QDoubleSpinBox(self)
        self.biasPoints.setDecimals(0)
        self.biasPoints.setMaximum(BLOCK_BIAS_VOLT_POINTS_MAX)
        self.biasPoints.setValue(BLOCK_BIAS_VOLT_POINTS)
        self.btnBiasScan = QPushButton("Scan Bias IV")
        self.btnBiasScan.clicked.connect(lambda: self.scan_bias_iv())

        layout.addWidget(self.biasVoltageFromLabel, 1, 0)
        layout.addWidget(self.biasVoltageFrom, 1, 1)
        layout.addWidget(self.biasVoltageToLabel, 2, 0)
        layout.addWidget(self.biasVoltageTo, 2, 1)
        layout.addWidget(self.biasPointsLabel, 3, 0)
        layout.addWidget(self.biasPoints, 3, 1)
        layout.addWidget(self.btnBiasScan, 4, 0, 1, 2)

        self.rowBiasScan.setLayout(layout)
