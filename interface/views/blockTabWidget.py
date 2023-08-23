import logging
import time
from datetime import datetime

import numpy as np
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QSizePolicy,
    QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from store.state import state

from api.Scontel.sis_block import SisBlock
from interface.components.DoubleSpinBox import DoubleSpinBox
from interface.windows.biasGraphWindow import BiasGraphWindow
from interface.windows.clGraphWindow import CLGraphWindow
from store.base import MeasureModel, MeasureType

logger = logging.getLogger(__name__)


class UtilsMixin:
    def set_voltage(self):
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
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
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
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


class BlockStreamThread(QThread):
    cl_current = pyqtSignal(float)
    bias_voltage = pyqtSignal(float)
    bias_current = pyqtSignal(float)

    def run(self):
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()
        while 1:
            if not state.BLOCK_STREAM_THREAD:
                break
            time.sleep(0.2)
            bias_voltage = block.get_bias_voltage()
            time.sleep(0.01)
            if not bias_voltage:
                continue
            bias_current = block.get_bias_current()
            time.sleep(0.01)
            if not bias_current:
                continue
            cl_current = block.get_ctrl_current()
            time.sleep(0.01)
            if not cl_current:
                continue
            self.bias_voltage.emit(bias_voltage)
            self.bias_current.emit(bias_current)
            self.cl_current.emit(cl_current)

        block.disconnect()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")
        state.BLOCK_STREAM_THREAD = False


class BlockCLScanThread(QThread):
    results = pyqtSignal(dict)
    stream_result = pyqtSignal(dict)

    def run(self):
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()
        results = {
            "ctrl_i_set": [],
            "ctrl_i_get": [],
            "bias_i": [],
        }
        ctrl_i_range = np.linspace(
            state.BLOCK_CTRL_CURR_FROM / 1e3,
            state.BLOCK_CTRL_CURR_TO / 1e3,
            state.BLOCK_CTRL_POINTS,
        )
        initial_ctrl_i = block.get_ctrl_current()
        start_t = datetime.now()
        i = 0
        measure = MeasureModel.objects.create(
            measure_type=MeasureType.CL_CURVE, data={}
        )
        for ctrl_i in ctrl_i_range:
            if not state.BLOCK_CTRL_SCAN_THREAD:
                break
            proc = round((i / state.BLOCK_CTRL_POINTS) * 100, 2)
            results["ctrl_i_set"].append(ctrl_i * 1e3)
            block.set_ctrl_current(ctrl_i)
            if i == 0:
                time.sleep(1)
            time.sleep(state.BLOCK_CTRL_STEP_DELAY)
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
            measure.data = results
            i += 1
        block.set_ctrl_current(initial_ctrl_i)
        self.results.emit(results)
        block.disconnect()
        measure.finished = datetime.now()
        measure.save()
        self.finished.emit()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")
        state.BLOCK_CTRL_SCAN_THREAD = False

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")
        state.BLOCK_CTRL_SCAN_THREAD = False

    def quit(
        self,
    ):
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")
        state.BLOCK_CTRL_SCAN_THREAD = False


class BlockBIASScanThread(QThread):
    results = pyqtSignal(dict)
    stream_result = pyqtSignal(dict)

    def run(self):
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
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
            state.BLOCK_BIAS_VOLT_FROM * 1e-3,
            state.BLOCK_BIAS_VOLT_TO * 1e-3,
            state.BLOCK_BIAS_VOLT_POINTS,
        )
        start_t = datetime.now()
        i = 0
        measure = MeasureModel.objects.create(
            measure_type=MeasureType.IV_CURVE, data={}
        )
        for v_set in v_range:
            if not state.BLOCK_BIAS_SCAN_THREAD:
                break
            proc = round((i / state.BLOCK_BIAS_VOLT_POINTS) * 100, 2)
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
            results["time"].append(delta_t.total_seconds())
            measure.data = results
            i += 1
            logger.info(f"[scan_bias] Proc {proc} %; Time {delta_t}; V_set {v_set}")
        block.set_bias_voltage(initial_v)
        block.disconnect()
        measure.finished = datetime.now()
        measure.save()
        self.results.emit(results)
        self.finished.emit()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")
        state.BLOCK_BIAS_SCAN_THREAD = False

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")
        state.BLOCK_BIAS_SCAN_THREAD = False

    def quit(
        self,
    ):
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")
        state.BLOCK_BIAS_SCAN_THREAD = False


class BlockTabWidget(QScrollArea, UtilsMixin):
    def __init__(self, parent):
        super().__init__(parent)
        self.widget = QWidget()
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ctrlGraphWindow = None
        self.biasGraphWindow = None
        self.createGroupMonitor()
        self.createGroupValuesSet()
        self.createGroupCTRLScan()
        self.createGroupBiasScan()
        self.layout.addWidget(self.groupMonitor)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.rowValuesSet)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupCTRLScan)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupBiasScan)
        self.layout.addStretch()

        self.widget.setLayout(self.layout)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setWidget(self.widget)

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
        self.block_ctrl_scan_thread = BlockCLScanThread()
        self.block_ctrl_scan_thread.stream_result.connect(self.show_ctrl_graph_window)

        state.BLOCK_CTRL_CURR_FROM = self.ctrlCurrentFrom.value()
        state.BLOCK_CTRL_CURR_TO = self.ctrlCurrentTo.value()
        state.BLOCK_CTRL_POINTS = int(self.ctrlPoints.value())
        state.BLOCK_CTRL_SCAN_THREAD = True
        state.BLOCK_CTRL_STEP_DELAY = self.ctrlStepDelay.value()

        self.block_ctrl_scan_thread.start()

        self.btnCTRLScan.setEnabled(False)
        self.block_ctrl_scan_thread.finished.connect(
            lambda: self.btnCTRLScan.setEnabled(True)
        )
        self.btnCTRLStopScan.setEnabled(True)
        self.block_ctrl_scan_thread.finished.connect(
            lambda: self.btnCTRLStopScan.setEnabled(False)
        )

    def stop_scan_ctrl_current(self):
        self.block_ctrl_scan_thread.quit()

    def set_block_bias_short_status(self):
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()
        if state.BLOCK_BIAS_SHORT_STATUS == "1":
            status = "0"
        else:
            status = "1"
        block.set_bias_short_status(status)
        new_status = block.get_bias_short_status()
        state.BLOCK_BIAS_SHORT_STATUS = new_status
        self.btnSetBiasShortStatus.setText(
            f"{state.BLOCK_SHORT_STATUS_MAP.get(state.BLOCK_BIAS_SHORT_STATUS)}"
        )
        block.disconnect()

    def set_block_ctrl_short_status(self):
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()
        if state.BLOCK_CTRL_SHORT_STATUS == "1":
            status = "0"
        else:
            status = "1"
        block.set_ctrl_short_status(status)
        new_status = block.get_ctrl_short_status()
        state.BLOCK_CTRL_SHORT_STATUS = new_status
        self.btnSetCtrlShortStatus.setText(
            f"{state.BLOCK_SHORT_STATUS_MAP.get(state.BLOCK_CTRL_SHORT_STATUS)}"
        )
        block.disconnect()

    def scan_bias_iv(self):
        self.block_bias_scan_thread = BlockBIASScanThread()
        self.block_bias_scan_thread.stream_result.connect(self.show_bias_graph_window)

        state.BLOCK_BIAS_VOLT_FROM = self.biasVoltageFrom.value()
        state.BLOCK_BIAS_VOLT_TO = self.biasVoltageTo.value()
        state.BLOCK_BIAS_VOLT_POINTS = int(self.biasPoints.value())
        state.BLOCK_BIAS_SCAN_THREAD = True

        self.block_bias_scan_thread.start()

        self.btnBiasScan.setEnabled(False)
        self.block_bias_scan_thread.finished.connect(
            lambda: self.btnBiasScan.setEnabled(True)
        )

        self.btnBiasStopScan.setEnabled(True)
        self.block_bias_scan_thread.finished.connect(
            lambda: self.btnBiasStopScan.setEnabled(False)
        )

    def stop_scan_bias_iv(self):
        self.block_bias_scan_thread.quit()

    def startStreamBlock(self):
        self.stream_thread = BlockStreamThread()

        self.stream_thread.cl_current.connect(
            lambda x: self.ctrlCurrentGet.setText(f"{round(x * 1e3, 3)}")
        )
        self.stream_thread.bias_current.connect(
            lambda x: self.sisCurrentGet.setText(f"{round(x * 1e6, 3)}")
        )
        self.stream_thread.bias_voltage.connect(
            lambda x: self.sisVoltageGet.setText(f"{round(x * 1e3, 3)}")
        )

        state.BLOCK_STREAM_THREAD = True
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
        self.stream_thread.terminate()

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
        self.sisVoltageSet = DoubleSpinBox(self)
        self.sisVoltageSet.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.btn_set_voltage = QPushButton("Set BIAS voltage")
        self.btn_set_voltage.clicked.connect(lambda: self.set_voltage())

        self.ctrlCurrentSetLabel = QLabel(self)
        self.ctrlCurrentSetLabel.setText("CL current, mA")
        self.ctrlCurrentSet = DoubleSpinBox(self)
        self.ctrlCurrentSet.setRange(
            state.BLOCK_CTRL_CURR_MIN_VALUE, state.BLOCK_CTRL_CURR_MAX_VALUE
        )

        self.btnSetCTRLCurrent = QPushButton("Set CL current")
        self.btnSetCTRLCurrent.clicked.connect(self.set_ctrl_current)

        self.btnSetBiasShortStatusLabel = QLabel()
        self.btnSetBiasShortStatusLabel.setText("Bias Status:")
        self.btnSetBiasShortStatus = QPushButton(
            f"{state.BLOCK_SHORT_STATUS_MAP.get(state.BLOCK_BIAS_SHORT_STATUS)}"
        )
        self.btnSetBiasShortStatus.clicked.connect(self.set_block_bias_short_status)

        self.btnSetCtrlShortStatusLabel = QLabel()
        self.btnSetCtrlShortStatusLabel.setText("CTRL Status:")
        self.btnSetCtrlShortStatus = QPushButton(
            f"{state.BLOCK_SHORT_STATUS_MAP.get(state.BLOCK_CTRL_SHORT_STATUS)}"
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
        self.ctrlCurrentFrom = DoubleSpinBox(self)
        self.ctrlCurrentFrom.setRange(
            state.BLOCK_CTRL_CURR_MIN_VALUE, state.BLOCK_CTRL_CURR_MAX_VALUE
        )
        self.ctrlCurrentToLabel = QLabel(self)
        self.ctrlCurrentToLabel.setText("CL Current to, mA")
        self.ctrlCurrentTo = DoubleSpinBox(self)
        self.ctrlCurrentTo.setRange(
            state.BLOCK_CTRL_CURR_MIN_VALUE, state.BLOCK_CTRL_CURR_MAX_VALUE
        )
        self.ctrlPointsLabel = QLabel(self)
        self.ctrlPointsLabel.setText("Points count")
        self.ctrlPoints = DoubleSpinBox(self)
        self.ctrlPoints.setDecimals(0)
        self.ctrlPoints.setMaximum(state.BLOCK_CTRL_POINTS_MAX)
        self.ctrlPoints.setValue(state.BLOCK_CTRL_POINTS)
        self.ctrlStepDelayLabel = QLabel("Step delay, s")
        self.ctrlStepDelay = DoubleSpinBox(self)
        self.ctrlStepDelay.setRange(0, 10)
        self.ctrlStepDelay.setDecimals(2)
        self.ctrlStepDelay.setValue(state.BLOCK_CTRL_STEP_DELAY)
        self.btnCTRLScan = QPushButton("Scan CL Current")
        self.btnCTRLScan.clicked.connect(self.scan_ctrl_current)

        self.btnCTRLStopScan = QPushButton("Stop Scan")
        self.btnCTRLStopScan.clicked.connect(self.stop_scan_ctrl_current)
        self.btnCTRLStopScan.setEnabled(False)

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
        self.biasVoltageFrom = DoubleSpinBox(self)
        self.biasVoltageFrom.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )
        self.biasVoltageToLabel = QLabel(self)
        self.biasVoltageToLabel.setText("Voltage to, mv")
        self.biasVoltageTo = DoubleSpinBox(self)
        self.biasVoltageTo.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )
        self.biasPointsLabel = QLabel(self)
        self.biasPointsLabel.setText("Points count")
        self.biasPoints = DoubleSpinBox(self)
        self.biasPoints.setDecimals(0)
        self.biasPoints.setMaximum(state.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.biasPoints.setValue(state.BLOCK_BIAS_VOLT_POINTS)
        self.btnBiasScan = QPushButton("Scan Bias IV")
        self.btnBiasScan.clicked.connect(self.scan_bias_iv)

        self.btnBiasStopScan = QPushButton("Stop Scan")
        self.btnBiasStopScan.clicked.connect(self.stop_scan_bias_iv)
        self.btnBiasStopScan.setEnabled(False)

        layout.addWidget(self.biasVoltageFromLabel, 1, 0)
        layout.addWidget(self.biasVoltageFrom, 1, 1)
        layout.addWidget(self.biasVoltageToLabel, 2, 0)
        layout.addWidget(self.biasVoltageTo, 2, 1)
        layout.addWidget(self.biasPointsLabel, 3, 0)
        layout.addWidget(self.biasPoints, 3, 1)
        layout.addWidget(self.btnBiasScan, 4, 0)
        layout.addWidget(self.btnBiasStopScan, 4, 1)

        self.groupBiasScan.setLayout(layout)
