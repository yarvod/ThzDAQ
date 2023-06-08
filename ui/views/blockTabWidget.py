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
    QFileDialog,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread

from config import config

from interactors.block import Block
from ui.components import CustomQDoubleSpinBox
from ui.windows.biasGraphWindow import BiasGraphWindow
from ui.windows.clGraphWindow import CLGraphWindow

logger = logging.getLogger(__name__)


class UtilsMixin:
    def set_voltage(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        try:
            voltage_to_set = float(self.sisVoltageSet.value()) * 1e-3
        except ValueError:
            logger.warning(f"Value {self.sisVoltageSet.value()} is not correct float")
            return
        block.set_bias_voltage(voltage_to_set)
        current = block.get_bias_current()
        self.sisCurrentGet.setText(f"{round(current * 1e6, 3)}")
        voltage = block.get_bias_voltage()
        self.sisVoltageGet.setText(f"{round(voltage * 1e3, 3)}")
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
            if not config.BLOCK_STREAM_THREAD:
                break
            time.sleep(0.1)
            bias_voltage = self.block.get_bias_voltage()
            if not bias_voltage:
                continue
            bias_current = self.block.get_bias_current()
            if not bias_current:
                continue
            cl_current = self.block.get_ctrl_current()
            if not cl_current:
                continue
            self.bias_voltage.emit(bias_voltage)
            self.bias_current.emit(bias_current)
            self.cl_current.emit(cl_current)

        self.block.disconnect()


class BlockCLScanWorker(QObject):
    finished = pyqtSignal()
    results = pyqtSignal(dict)
    stream_result = pyqtSignal(dict)

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
        i = 0
        for ctrl_i in ctrl_i_range:
            if not config.BLOCK_CTRL_SCAN_THREAD:
                break
            proc = round((i / config.BLOCK_CTRL_POINTS) * 100, 2)
            results["ctrl_i_set"].append(ctrl_i * 1e3)
            block.set_ctrl_current(ctrl_i)
            if i == 0:
                time.sleep(1)
            time.sleep(config.BLOCK_CTRL_STEP_DELAY)
            ctrl_current = block.get_ctrl_current() * 1e3
            if not ctrl_current:
                continue
            bias_current = block.get_bias_current() * 1e6
            if not bias_current:
                continue
            results["ctrl_i_get"].append(ctrl_current)
            results["bias_i"].append(bias_current)
            self.stream_result.emit(
                {
                    "x": [ctrl_current],
                    "y": [bias_current],
                    "new_plot": i == 0,
                }
            )
            delta_t = datetime.now() - start_t
            logger.info(
                f"[scan_ctrl_current] Proc {proc} %; Time {delta_t}; I set {ctrl_i * 1e3}"
            )
            i += 1
        block.set_ctrl_current(initial_ctrl_i)
        self.results.emit(results)
        block.disconnect()
        self.finished.emit()


class BlockBIASScanWorker(QObject):
    finished = pyqtSignal()
    results = pyqtSignal(dict)
    stream_result = pyqtSignal(dict)

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
            config.BLOCK_BIAS_VOLT_POINTS,
        )
        start_t = datetime.now()
        i = 0
        for v_set in v_range:
            if not config.BLOCK_BIAS_SCAN_THREAD:
                break
            proc = round((i / config.BLOCK_BIAS_VOLT_POINTS) * 100, 2)
            block.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            v_get = block.get_bias_voltage()
            if not v_get:
                continue
            i_get = block.get_bias_current()
            if not i_get:
                continue
            results["v_get"].append(v_get * 1e3)
            results["v_set"].append(v_set * 1e3)
            results["i_get"].append(i_get * 1e6)
            self.stream_result.emit(
                {
                    "x": [v_get * 1e3],
                    "y": [i_get * 1e6],
                    "new_plot": i == 0,
                }
            )
            delta_t = datetime.now() - start_t
            results["time"].append(delta_t)
            i += 1
            logger.info(f"[scan_bias] Proc {proc} %; Time {delta_t}; V_set {v_set}")
        block.set_bias_voltage(initial_v)
        block.disconnect()
        self.results.emit(results)
        self.finished.emit()


class BlockTabWidget(QWidget, UtilsMixin):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ctrlGraphWindow = None
        self.biasGraphWindow = None
        self.createGroupMonitor()
        self.createGroupValuesSet()
        self.createGroupCTRLScan()
        self.createGroupBiasScan()
        self.layout.addWidget(self.groupMonitor)
        self.layout.addWidget(self.rowValuesSet)
        self.layout.addWidget(self.groupCTRLScan)
        self.layout.addWidget(self.groupBiasScan)
        self.setLayout(self.layout)

    def show_ctrl_graph_window(self, results: dict):
        if self.ctrlGraphWindow is None:
            self.ctrlGraphWindow = CLGraphWindow()
        self.ctrlGraphWindow.plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
        )
        self.ctrlGraphWindow.show()

    def show_bias_graph_window(self, results):
        if self.biasGraphWindow is None:
            self.biasGraphWindow = BiasGraphWindow()
        self.biasGraphWindow.plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
        )
        self.biasGraphWindow.show()

    def scan_ctrl_current(self):
        self.sis_thread = QThread()
        self.sis_worker = BlockCLScanWorker()
        self.sis_worker.moveToThread(self.sis_thread)

        config.BLOCK_CTRL_CURR_FROM = self.ctrlCurrentFrom.value()
        config.BLOCK_CTRL_CURR_TO = self.ctrlCurrentTo.value()
        config.BLOCK_CTRL_POINTS = int(self.ctrlPoints.value())
        config.BLOCK_CTRL_SCAN_THREAD = True
        config.BLOCK_CTRL_STEP_DELAY = self.ctrlStepDelay.value()

        self.sis_thread.started.connect(self.sis_worker.run)
        self.sis_worker.finished.connect(self.sis_thread.quit)
        self.sis_worker.finished.connect(self.sis_worker.deleteLater)
        self.sis_thread.finished.connect(self.sis_thread.deleteLater)
        self.sis_worker.stream_result.connect(self.show_ctrl_graph_window)
        self.sis_thread.start()

        self.btnCTRLScan.setEnabled(False)
        self.sis_thread.finished.connect(lambda: self.btnCTRLScan.setEnabled(True))

    def stop_scan_ctrl_current(self):
        config.BLOCK_CTRL_SCAN_THREAD = False

    def set_block_bias_short_status(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        if config.BLOCK_BIAS_SHORT_STATUS == "1":
            status = "0"
        else:
            status = "1"
        block.set_bias_short_status(status)
        new_status = block.get_bias_short_status()
        config.BLOCK_BIAS_SHORT_STATUS = new_status
        self.btnSetBiasShortStatus.setText(
            f"{config.BLOCK_SHORT_STATUS_MAP.get(config.BLOCK_BIAS_SHORT_STATUS)}"
        )

    def set_block_ctrl_short_status(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        if config.BLOCK_CTRL_SHORT_STATUS == "1":
            status = "0"
        else:
            status = "1"
        block.set_ctrl_short_status(status)
        new_status = block.get_ctrl_short_status()
        config.BLOCK_CTRL_SHORT_STATUS = new_status
        self.btnSetCtrlShortStatus.setText(
            f"{config.BLOCK_SHORT_STATUS_MAP.get(config.BLOCK_CTRL_SHORT_STATUS)}"
        )

    def save_iv_data(self, results):
        try:
            filepath = QFileDialog.getSaveFileName(filter="*.csv")[0]
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

    def scan_bias_iv(self):
        self.sis_bias_thread = QThread()
        self.sis_bias_worker = BlockBIASScanWorker()
        self.sis_bias_worker.moveToThread(self.sis_bias_thread)

        config.BLOCK_BIAS_VOLT_FROM = self.biasVoltageFrom.value()
        config.BLOCK_BIAS_VOLT_TO = self.biasVoltageTo.value()
        config.BLOCK_BIAS_VOLT_POINTS = int(self.biasPoints.value())
        config.BLOCK_BIAS_SCAN_THREAD = True

        self.sis_bias_thread.started.connect(self.sis_bias_worker.run)
        self.sis_bias_worker.finished.connect(self.sis_bias_thread.quit)
        self.sis_bias_worker.finished.connect(self.sis_bias_worker.deleteLater)
        self.sis_bias_thread.finished.connect(self.sis_bias_thread.deleteLater)
        self.sis_bias_worker.stream_result.connect(self.show_bias_graph_window)
        self.sis_bias_worker.results.connect(self.save_iv_data)
        self.sis_bias_thread.start()

        self.btnBiasScan.setEnabled(False)
        self.sis_bias_thread.finished.connect(lambda: self.btnBiasScan.setEnabled(True))

    def stop_scan_bias_iv(self):
        config.BLOCK_BIAS_SCAN_THREAD = False

    def startStreamBlock(self):
        self.stream_thread = QThread()
        self.stream_worker = BlockStreamWorker()
        self.stream_worker.moveToThread(self.stream_thread)

        config.BLOCK_STREAM_THREAD = True

        self.stream_thread.started.connect(self.stream_worker.run)
        self.stream_worker.finished.connect(self.stream_thread.quit)
        self.stream_worker.finished.connect(self.stream_worker.deleteLater)
        self.stream_thread.finished.connect(self.stream_thread.deleteLater)
        self.stream_worker.cl_current.connect(
            lambda x: self.ctrlCurrentGet.setText(f"{round(x * 1e3, 3)}")
        )
        self.stream_worker.bias_current.connect(
            lambda x: self.sisCurrentGet.setText(f"{round(x * 1e6, 3)}")
        )
        self.stream_worker.bias_voltage.connect(
            lambda x: self.sisVoltageGet.setText(f"{round(x * 1e3, 3)}")
        )
        self.stream_thread.start()

        self.btnStartStreamBlock.setEnabled(False)
        self.stream_thread.finished.connect(
            lambda: self.btnStartStreamBlock.setEnabled(True)
        )

        self.btnStopStreamBlock.setEnabled(True)
        self.stream_thread.finished.connect(
            lambda: self.btnStopStreamBlock.setEnabled(False)
        )

    def stopStreamBlock(self):
        config.BLOCK_STREAM_THREAD = False
        self.stream_worker.finished.emit()

    def createGroupMonitor(self):
        self.groupMonitor = QGroupBox("Block Monitor")
        self.groupMonitor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.sisVoltageGetLabel = QLabel(self)
        self.sisVoltageGetLabel.setText("<h4>BIAS voltage, mV</h4>")
        self.sisVoltageGet = QLabel(self)
        self.sisVoltageGet.setText("0.0")
        self.sisVoltageGet.setStyleSheet("font-size: 23px; font-weight: bold;")

        self.sisCurrentGetLabel = QLabel(self)
        self.sisCurrentGetLabel.setText("<h4>BIAS current, mkA</h4>")
        self.sisCurrentGet = QLabel(self)
        self.sisCurrentGet.setText("0.0")
        self.sisCurrentGet.setStyleSheet("font-size: 23px; font-weight: bold;")

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

        layout.addWidget(
            self.sisVoltageGetLabel, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.sisCurrentGetLabel, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.ctrlCurrentGetLabel, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.sisVoltageGet, 2, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.sisCurrentGet, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.ctrlCurrentGet, 2, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.btnStartStreamBlock, 3, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.btnStopStreamBlock, 3, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.groupMonitor.setLayout(layout)

    def createGroupValuesSet(self):
        self.rowValuesSet = QGroupBox("Set block values")
        self.rowValuesSet.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.sisVoltageSetLabel = QLabel(self)
        self.sisVoltageSetLabel.setText("BIAS voltage, mV:")
        self.sisVoltageSet = CustomQDoubleSpinBox(self)
        self.sisVoltageSet.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.btn_set_voltage = QPushButton("Set BIAS voltage")
        self.btn_set_voltage.clicked.connect(lambda: self.set_voltage())

        self.ctrlCurrentSetLabel = QLabel(self)
        self.ctrlCurrentSetLabel.setText("CL current, mA")
        self.ctrlCurrentSet = CustomQDoubleSpinBox(self)
        self.ctrlCurrentSet.setRange(
            config.BLOCK_CTRL_CURR_MIN_VALUE, config.BLOCK_CTRL_CURR_MAX_VALUE
        )

        self.btnSetCTRLCurrent = QPushButton("Set CL current")
        self.btnSetCTRLCurrent.clicked.connect(self.set_ctrl_current)

        self.btnSetBiasShortStatusLabel = QLabel()
        self.btnSetBiasShortStatusLabel.setText("Bias Status:")
        self.btnSetBiasShortStatus = QPushButton(
            f"{config.BLOCK_SHORT_STATUS_MAP.get(config.BLOCK_BIAS_SHORT_STATUS)}"
        )
        self.btnSetBiasShortStatus.clicked.connect(self.set_block_bias_short_status)

        self.btnSetCtrlShortStatusLabel = QLabel()
        self.btnSetCtrlShortStatusLabel.setText("CTRL Status:")
        self.btnSetCtrlShortStatus = QPushButton(
            f"{config.BLOCK_SHORT_STATUS_MAP.get(config.BLOCK_CTRL_SHORT_STATUS)}"
        )
        self.btnSetCtrlShortStatus.clicked.connect(self.set_block_ctrl_short_status)

        layout.addWidget(self.sisVoltageSetLabel, 1, 0)
        layout.addWidget(self.sisVoltageSet, 1, 1)
        layout.addWidget(self.btn_set_voltage, 1, 2)
        layout.addWidget(self.ctrlCurrentSetLabel, 2, 0)
        layout.addWidget(self.ctrlCurrentSet, 2, 1)
        layout.addWidget(self.btnSetCTRLCurrent, 2, 2)
        layout.addWidget(self.btnSetBiasShortStatusLabel, 3, 0)
        layout.addWidget(self.btnSetBiasShortStatus, 3, 1)
        layout.addWidget(self.btnSetCtrlShortStatusLabel, 4, 0)
        layout.addWidget(self.btnSetCtrlShortStatus, 4, 1)

        self.rowValuesSet.setLayout(layout)

    def createGroupCTRLScan(self):
        self.groupCTRLScan = QGroupBox("Scan CTRL current")
        self.groupCTRLScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.ctrlCurrentFromLabel = QLabel(self)
        self.ctrlCurrentFromLabel.setText("CL Current from, mA")
        self.ctrlCurrentFrom = CustomQDoubleSpinBox(self)
        self.ctrlCurrentFrom.setRange(
            config.BLOCK_CTRL_CURR_MIN_VALUE, config.BLOCK_CTRL_CURR_MAX_VALUE
        )
        self.ctrlCurrentToLabel = QLabel(self)
        self.ctrlCurrentToLabel.setText("CL Current to, mA")
        self.ctrlCurrentTo = CustomQDoubleSpinBox(self)
        self.ctrlCurrentTo.setRange(
            config.BLOCK_CTRL_CURR_MIN_VALUE, config.BLOCK_CTRL_CURR_MAX_VALUE
        )
        self.ctrlPointsLabel = QLabel(self)
        self.ctrlPointsLabel.setText("Points count")
        self.ctrlPoints = CustomQDoubleSpinBox(self)
        self.ctrlPoints.setDecimals(0)
        self.ctrlPoints.setMaximum(config.BLOCK_CTRL_POINTS_MAX)
        self.ctrlPoints.setValue(config.BLOCK_CTRL_POINTS)
        self.ctrlStepDelayLabel = QLabel("Step delay, s")
        self.ctrlStepDelay = CustomQDoubleSpinBox(self)
        self.ctrlStepDelay.setRange(0, 10)
        self.ctrlStepDelay.setDecimals(2)
        self.ctrlStepDelay.setValue(config.BLOCK_CTRL_STEP_DELAY)
        self.btnCTRLScan = QPushButton("Scan CL Current")
        self.btnCTRLScan.clicked.connect(self.scan_ctrl_current)

        self.btnCTRLStopScan = QPushButton("Stop Scan")
        self.btnCTRLStopScan.clicked.connect(self.stop_scan_ctrl_current)

        layout.addWidget(self.ctrlCurrentFromLabel, 1, 0)
        layout.addWidget(self.ctrlCurrentFrom, 1, 1)
        layout.addWidget(self.ctrlCurrentToLabel, 2, 0)
        layout.addWidget(self.ctrlCurrentTo, 2, 1)
        layout.addWidget(self.ctrlPointsLabel, 3, 0)
        layout.addWidget(self.ctrlPoints, 3, 1)
        layout.addWidget(self.ctrlStepDelayLabel, 4, 0)
        layout.addWidget(self.ctrlStepDelay, 4, 1)
        layout.addWidget(self.btnCTRLScan, 5, 0)
        layout.addWidget(self.btnCTRLStopScan, 5, 1)

        self.groupCTRLScan.setLayout(layout)

    def createGroupBiasScan(self):
        self.groupBiasScan = QGroupBox("Scan Bias IV")
        self.groupBiasScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.biasVoltageFromLabel = QLabel(self)
        self.biasVoltageFromLabel.setText("Voltage from, mV")
        self.biasVoltageFrom = CustomQDoubleSpinBox(self)
        self.biasVoltageFrom.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )
        self.biasVoltageToLabel = QLabel(self)
        self.biasVoltageToLabel.setText("Voltage to, mv")
        self.biasVoltageTo = CustomQDoubleSpinBox(self)
        self.biasVoltageTo.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )
        self.biasPointsLabel = QLabel(self)
        self.biasPointsLabel.setText("Points count")
        self.biasPoints = CustomQDoubleSpinBox(self)
        self.biasPoints.setDecimals(0)
        self.biasPoints.setMaximum(config.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.biasPoints.setValue(config.BLOCK_BIAS_VOLT_POINTS)
        self.btnBiasScan = QPushButton("Scan Bias IV")
        self.btnBiasScan.clicked.connect(self.scan_bias_iv)

        self.btnBiasStopScan = QPushButton("Stop Scan")
        self.btnBiasStopScan.clicked.connect(self.stop_scan_bias_iv)

        layout.addWidget(self.biasVoltageFromLabel, 1, 0)
        layout.addWidget(self.biasVoltageFrom, 1, 1)
        layout.addWidget(self.biasVoltageToLabel, 2, 0)
        layout.addWidget(self.biasVoltageTo, 2, 1)
        layout.addWidget(self.biasPointsLabel, 3, 0)
        layout.addWidget(self.biasPoints, 3, 1)
        layout.addWidget(self.btnBiasScan, 4, 0, 1, 2)
        layout.addWidget(self.btnBiasStopScan, 5, 0, 1, 2)

        self.groupBiasScan.setLayout(layout)
