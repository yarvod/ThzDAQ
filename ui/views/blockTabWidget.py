import logging
import time
from datetime import datetime

import numpy as np
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
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread

from config import config

from interactors.block import Block
from ui.windows.biasGraphWindow import BiasGraphWindow
from ui.windows.clGraphWindow import CLGraphWindow

logger = logging.getLogger(__name__)


class UtilsMixin:
    def updateValues(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        current = block.get_bias_current()
        self.current_g.setText(f"{round(current * 1e6, 3)}")
        voltage = block.get_bias_voltage()
        self.voltage_g.setText(f"{round(voltage * 1e3, 3)}")
        ctrlCurrentGet = block.get_ctrl_current()
        self.ctrlCurrentGet.setText(f"{round(ctrlCurrentGet * 1e3, 3)}")
        block.disconnect()

    def set_voltage(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        try:
            voltage_to_set = float(self.voltage_s.value()) * 1e-3
        except ValueError:
            logger.warning(f"Value {self.voltage_s.value()} is not correct float")
            return
        block.set_bias_voltage(voltage_to_set)
        current = block.get_bias_current()
        self.current_g.setText(f"{round(current * 1e6, 3)}")
        voltage = block.get_bias_voltage()
        self.voltage_g.setText(f"{round(voltage * 1e3, 3)}")
        block.disconnect()

    def set_ctrl_current(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        try:
            ctrlCurrentSet = float(self.ctrlCurrentSet.value()) * 1e-3
        except ValueError:
            logger.warning(f"Value {self.ctrlCurrentSet.value()} is not correct float")
            return
        block.set_ctrl_current(ctrlCurrentSet)
        ctrlCurrentGet = block.get_ctrl_current()
        block.disconnect()
        self.ctrlCurrentGet.setText(f"{round(ctrlCurrentGet * 1e3, 3)}")

    def get_voltage_current(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        current = block.get_bias_current()
        self.current_g.setText(f"{round(current * 1e6, 3)}")
        voltage = block.get_bias_voltage()
        self.voltage_g.setText(f"{round(voltage * 1e3, 3)}")
        block.disconnect()

    def scan_bias_iv(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        try:
            bias_v_from = float(self.biasVoltageFrom.value()) * 1e-3
            bias_v_to = float(self.biasVoltageTo.value()) * 1e-3
            points_num = int(self.biasPoints.value())
        except ValueError:
            logger.warning(f"Range values is not correct floats/ints")
            return
        results = block.scan_bias(bias_v_from, bias_v_to, points_num)
        block.disconnect()
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


class BlockStreamWorker(QObject):
    finished = pyqtSignal()
    cl_current = pyqtSignal(float)
    bias_voltage = pyqtSignal(float)
    bias_current = pyqtSignal(float)

    def run(self):
        self.block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        self.block.connect()
        while 1:
            time.sleep(0.25)
            bias_voltage = self.block.get_bias_voltage()
            bias_current = self.block.get_bias_current()
            cl_current = self.block.get_ctrl_current()
            self.bias_voltage.emit(bias_voltage)
            self.bias_current.emit(bias_current)
            self.cl_current.emit(cl_current)


class BlockCLScanWorker(QObject):
    finished = pyqtSignal()
    results = pyqtSignal(dict)

    def run(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        results = {
            "ctrl_i_set": [],
            "ctrl_i_get": [],
            "bias_i": [],
        }
        ctrl_i_range = np.linspace(
            config.BLOCK_CTRL_CURR_FROM / 1e3,
            config.BLOCK_CTRL_CURR_TO / 1e3,
            config.BLOCK_CTRL_POINTS,
        )
        initial_ctrl_i = block.get_ctrl_current()
        start_t = datetime.now()
        for i, ctrl_i in enumerate(ctrl_i_range):
            if i == 0:
                time.sleep(0.1)
            proc = round((i / config.BLOCK_CTRL_POINTS) * 100, 2)
            results["ctrl_i_set"].append(ctrl_i * 1e3)
            block.set_ctrl_current(ctrl_i)
            results["ctrl_i_get"].append(block.get_ctrl_current() * 1e3)
            results["bias_i"].append(block.get_bias_current() * 1e6)
            delta_t = datetime.now() - start_t
            logger.info(
                f"[scan_ctrl_current] Proc {proc} %; Time {delta_t}; I set {ctrl_i * 1e3}"
            )
        block.set_ctrl_current(initial_ctrl_i)
        self.results.emit(results)
        block.disconnect()
        self.finished.emit()


class BlockBIASScanWorker(QObject):
    finished = pyqtSignal()
    results = pyqtSignal(dict)

    def run(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        results = {
            "i_get": [],
            "v_set": [],
            "v_get": [],
            "time": [],
        }
        initial_v = block.get_bias_voltage()
        v_range = np.linspace(
            config.BLOCK_BIAS_VOLT_FROM * 1e-3,
            config.BLOCK_BIAS_VOLT_TO * 1e-3,
            config.BLOCK_BIAS_VOLT_POINTS
        )
        start_t = datetime.now()
        for i, v_set in enumerate(v_range):
            proc = round((i / config.BLOCK_BIAS_VOLT_POINTS) * 100, 2)
            block.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            v_get = block.get_bias_voltage()
            i_get = block.get_bias_current()
            results["v_get"].append(v_get * 1e3)
            results["v_set"].append(v_set * 1e3)
            results["i_get"].append(i_get * 1e6)
            delta_t = datetime.now() - start_t
            results["time"].append(delta_t)
            logger.info(f"[scan_bias] Proc {proc} %; Time {delta_t}; V_set {v_set}")
        block.set_bias_voltage(initial_v)
        block.disconnect()
        self.results.emit(results)
        self.finished.emit()


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

    def show_ctrl_graph_window(self, results: dict):
        if self.ctrlGraphWindow is None:
            self.ctrlGraphWindow = CLGraphWindow()
        self.ctrlGraphWindow.plotNew(x=results["ctrl_i_get"], y=results["bias_i"])
        self.ctrlGraphWindow.show()

    def show_bias_graph_window(self, results):
        if self.biasGraphWindow is None:
            self.biasGraphWindow = BiasGraphWindow()
        self.biasGraphWindow.plotNew(results["v_get"], results["i_get"])
        self.biasGraphWindow.show()

    def scan_ctrl_current_v2(self):
        self.sis_thread = QThread()
        self.sis_worker = BlockCLScanWorker()
        self.sis_worker.moveToThread(self.sis_thread)

        config.BLOCK_CTRL_CURR_FROM = self.ctrlCurrentFrom.value()
        config.BLOCK_CTRL_CURR_TO = self.ctrlCurrentTo.value()
        config.BLOCK_CTRL_POINTS = int(self.ctrlPoints.value())

        self.sis_thread.started.connect(self.sis_worker.run)
        self.sis_worker.finished.connect(self.sis_thread.quit)
        self.sis_worker.finished.connect(self.sis_worker.deleteLater)
        self.sis_thread.finished.connect(self.sis_thread.deleteLater)
        self.sis_worker.results.connect(self.show_ctrl_graph_window)
        self.sis_thread.start()

        self.btnCTRLScan.setEnabled(False)
        self.sis_thread.finished.connect(lambda: self.btnCTRLScan.setEnabled(True))

    def scan_bias_iv_v2(self):
        self.sis_bias_thread = QThread()
        self.sis_bias_worker = BlockBIASScanWorker()
        self.sis_bias_worker.moveToThread(self.sis_bias_thread)

        config.BLOCK_BIAS_VOLT_FROM = self.biasVoltageFrom.value()
        config.BLOCK_BIAS_VOLT_TO = self.biasVoltageTo.value()
        config.BLOCK_BIAS_VOLT_POINTS = int(self.biasPoints.value())

        self.sis_bias_thread.started.connect(self.sis_bias_worker.run)
        self.sis_bias_worker.finished.connect(self.sis_bias_thread.quit)
        self.sis_bias_worker.finished.connect(self.sis_bias_worker.deleteLater)
        self.sis_bias_thread.finished.connect(self.sis_bias_thread.deleteLater)
        self.sis_bias_worker.results.connect(self.show_bias_graph_window)
        self.sis_bias_thread.start()

        self.btnBiasScan.setEnabled(False)
        self.sis_bias_thread.finished.connect(lambda: self.btnBiasScan.setEnabled(True))

    def startStreamBlock(self):
        self.stream_thread = QThread()
        self.stream_worker = BlockStreamWorker()
        self.stream_worker.moveToThread(self.stream_thread)

        self.stream_thread.started.connect(self.stream_worker.run)
        self.stream_worker.finished.connect(self.stream_thread.quit)
        self.stream_worker.finished.connect(self.stream_worker.deleteLater)
        self.stream_thread.finished.connect(self.stream_thread.deleteLater)
        self.stream_worker.cl_current.connect(lambda x: self.ctrlCurrentGet.setText(f"{round(x * 1e3, 3)}"))
        self.stream_worker.bias_current.connect(lambda x: self.current_g.setText(f"{round(x * 1e6, 3)}"))
        self.stream_worker.bias_voltage.connect(lambda x: self.voltage_g.setText(f"{round(x * 1e3, 3)}"))
        self.stream_thread.start()

        self.btnStartStreamBlock.setEnabled(False)
        self.stream_thread.finished.connect(lambda: self.btnStartStreamBlock.setEnabled(True))

        self.btnStopStreamBlock.setEnabled(True)
        self.stream_thread.finished.connect(lambda: self.btnStopStreamBlock.setEnabled(False))

    def stopStreamBlock(self):
        self.stream_worker.block.disconnect()
        self.stream_worker.finished.emit()

    def createGroupValuesGet(self):
        self.rowValuesGet = QGroupBox("Get values")
        layout = QGridLayout()

        self.voltGLabel = QLabel(self)
        self.voltGLabel.setText("<h4>BIAS voltage, mV</h4>")
        self.voltage_g = QLabel(self)
        self.voltage_g.setText("0.0")
        self.voltage_g.setStyleSheet("font-size: 23px; font-weight: bold;")

        self.currGLabel = QLabel(self)
        self.currGLabel.setText("<h4>BIAS current, mkA</h4>")
        self.current_g = QLabel(self)
        self.current_g.setText("0.0")
        self.current_g.setStyleSheet("font-size: 23px; font-weight: bold;")

        self.ctrlCurrentGetLabel = QLabel(self)
        self.ctrlCurrentGetLabel.setText("<h4>CL current, mA</h4>")
        self.ctrlCurrentGet = QLabel(self)
        self.ctrlCurrentGet.setText("0.0")
        self.ctrlCurrentGet.setStyleSheet("font-size: 23px; font-weight: bold;")

        self.btnStartStreamBlock = QPushButton("Start Stream")
        self.btnStartStreamBlock.clicked.connect(self.startStreamBlock)

        self.btnStopStreamBlock = QPushButton("Stop Stream")
        self.btnStopStreamBlock.setEnabled(False)
        self.btnStopStreamBlock.clicked.connect(self.stopStreamBlock)

        layout.addWidget(self.voltGLabel, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.currGLabel, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            self.ctrlCurrentGetLabel, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(self.voltage_g, 2, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.current_g, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            self.ctrlCurrentGet, 2, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.btnStartStreamBlock, 3, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.btnStopStreamBlock, 3, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.rowValuesGet.setLayout(layout)

    def createGroupValuesSet(self):
        self.rowValuesSet = QGroupBox("Set values")
        layout = QGridLayout()

        self.voltSLabel = QLabel(self)
        self.voltSLabel.setText("BIAS voltage, mV:")
        self.voltage_s = QDoubleSpinBox(self)
        self.voltage_s.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.btn_set_voltage = QPushButton("Set BIAS voltage")
        self.btn_set_voltage.clicked.connect(lambda: self.set_voltage())

        self.ctrlCurrentSetLabel = QLabel(self)
        self.ctrlCurrentSetLabel.setText("CL current, mA")
        self.ctrlCurrentSet = QDoubleSpinBox(self)
        self.ctrlCurrentSet.setRange(
            config.BLOCK_CTRL_CURR_MIN_VALUE, config.BLOCK_CTRL_CURR_MAX_VALUE
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
            config.BLOCK_CTRL_CURR_MIN_VALUE, config.BLOCK_CTRL_CURR_MAX_VALUE
        )
        self.ctrlCurrentToLabel = QLabel(self)
        self.ctrlCurrentToLabel.setText("CL Current to, mA")
        self.ctrlCurrentTo = QDoubleSpinBox(self)
        self.ctrlCurrentTo.setRange(
            config.BLOCK_CTRL_CURR_MIN_VALUE, config.BLOCK_CTRL_CURR_MAX_VALUE
        )
        self.ctrlPointsLabel = QLabel(self)
        self.ctrlPointsLabel.setText("Points num")
        self.ctrlPoints = QDoubleSpinBox(self)
        self.ctrlPoints.setDecimals(0)
        self.ctrlPoints.setMaximum(config.BLOCK_CTRL_POINTS_MAX)
        self.ctrlPoints.setValue(config.BLOCK_CTRL_POINTS)
        self.btnCTRLScan = QPushButton("Scan CL Current")
        self.btnCTRLScan.clicked.connect(self.scan_ctrl_current_v2)

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
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )
        self.biasVoltageToLabel = QLabel(self)
        self.biasVoltageToLabel.setText("Voltage to, mv")
        self.biasVoltageTo = QDoubleSpinBox(self)
        self.biasVoltageTo.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )
        self.biasPointsLabel = QLabel(self)
        self.biasPointsLabel.setText("Points num")
        self.biasPoints = QDoubleSpinBox(self)
        self.biasPoints.setDecimals(0)
        self.biasPoints.setMaximum(config.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.biasPoints.setValue(config.BLOCK_BIAS_VOLT_POINTS)
        self.btnBiasScan = QPushButton("Scan Bias IV")
        self.btnBiasScan.clicked.connect(self.scan_bias_iv_v2)

        layout.addWidget(self.biasVoltageFromLabel, 1, 0)
        layout.addWidget(self.biasVoltageFrom, 1, 1)
        layout.addWidget(self.biasVoltageToLabel, 2, 0)
        layout.addWidget(self.biasVoltageTo, 2, 1)
        layout.addWidget(self.biasPointsLabel, 3, 0)
        layout.addWidget(self.biasPoints, 3, 1)
        layout.addWidget(self.btnBiasScan, 4, 0, 1, 2)

        self.rowBiasScan.setLayout(layout)
