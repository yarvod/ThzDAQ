import logging
import time
from datetime import datetime

import numpy as np
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QProgressBar,
    QHBoxLayout,
    QCheckBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QSettings

from interface.components.Scontel.sisDemagnetisationWidget import (
    SisDemagnetisationWidget,
)
from interface.components.ui.Button import Button
from store import ScontelSisBlockManager
from store.state import state
from api.Scontel.sis_block import SisBlock
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store.base import MeasureModel, MeasureType
from threads import Thread
from utils.dock import Dock
from utils.exceptions import DeviceConnectionError

logger = logging.getLogger(__name__)


class BlockSetBiasVoltageThread(Thread):
    def __init__(self, cid: int, voltage: float):
        self.config = ScontelSisBlockManager.get_config(cid)
        self.voltage = voltage
        super().__init__()

    def run(self):
        try:
            block = SisBlock(**self.config.dict())
        except DeviceConnectionError as e:
            self.pre_exit()
            self.finished.emit()
            return
        block.set_bias_voltage(self.voltage)
        block.disconnect()
        self.pre_exit()
        self.finished.emit()


class BlockSetCtrlCurrentThread(Thread):
    def __init__(self, cid: int, current: float):
        self.config = ScontelSisBlockManager.get_config(cid)
        self.current = current
        super().__init__()

    def run(self):
        try:
            block = SisBlock(**self.config.dict())
        except DeviceConnectionError as e:
            self.pre_exit()
            self.finished.emit()
            return
        block.set_ctrl_current(self.current)
        block.disconnect()
        self.pre_exit()
        self.finished.emit()


class BlockCalibrateThread(Thread):
    def __init__(self, parent, cid: int):
        self.config = ScontelSisBlockManager.get_config(cid)
        self.block = None
        super().__init__(parent)

    def run(self):
        try:
            self.block = SisBlock(**self.config.dict())

            settings = QSettings("settings.ini", QSettings.IniFormat)

            vadc4 = settings.value("SIS_Block_Cals/vadc4", None)
            cadc4 = settings.value("SIS_Block_Cals/cadc4", None)
            vadc2 = settings.value("SIS_Block_Cals/vadc2", None)
            cadc2 = settings.value("SIS_Block_Cals/cadc2", None)

            if vadc4:
                vadc4 = [float(_) for _ in vadc4]
                self.block.adapter.query(f"BIAS:DEV4:VADC {vadc4}")
            if cadc4:
                cadc4 = [float(_) for _ in cadc4]
                self.block.adapter.query(f"BIAS:DEV4:CADC {cadc4}")

            if vadc2:
                vadc2 = [float(_) for _ in vadc2]
                self.block.adapter.query(f"BIAS:DEV2:VADC {vadc2}")
            if cadc2:
                cadc2 = [float(_) for _ in cadc2]
                self.block.adapter.query(f"BIAS:DEV2:CADC {cadc2}")

            self.block.adapter.query("GENeral:DEVice2:WriteEEProm")
            self.block.adapter.query("GENeral:DEVice4:WriteEEProm")
            del self.block
        except DeviceConnectionError as e:
            logger.exception(f"{e}", exc_info=True)
        self.finished.emit()


class BlockStreamThread(QThread):
    cl_current = pyqtSignal(float)
    bias_voltage = pyqtSignal(float)
    bias_current = pyqtSignal(float)
    plot_data = pyqtSignal(dict)

    def __init__(self, cid: int, stream_plot: bool = False):
        self.config = ScontelSisBlockManager.get_config(cid)
        self.config.thread_stream = True
        self.stream_plot = stream_plot
        super().__init__()

    def run(self):
        try:
            block = SisBlock(**self.config.dict())
        except DeviceConnectionError as e:
            self.pre_exit()
            self.finished.emit()
            return
        i = 1
        while 1:
            if not self.config.thread_stream:
                break
            time.sleep(0.2)

            bias_voltage = block.get_bias_voltage()
            if bias_voltage:
                self.bias_voltage.emit(bias_voltage)

            bias_current = block.get_bias_current()
            if bias_current:
                self.bias_current.emit(bias_current)

            if i % 2 == 0:
                cl_current = block.get_ctrl_current()
                if cl_current:
                    self.cl_current.emit(cl_current)

            if self.stream_plot and bias_voltage and bias_current:
                self.plot_data.emit(
                    {
                        "x": [bias_voltage * 1e3],
                        "y": [bias_current * 1e6],
                        "new_plot": i == 1,
                    }
                )

            i += 1

        block.disconnect()
        self.pre_exit()

    def pre_exit(self, *args, **kwargs):
        self.config.thread_stream = False


class BlockCLScanThread(Thread):
    results = pyqtSignal(dict)
    stream_result = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, cid: int):
        self.config = ScontelSisBlockManager.get_config(cid)
        super().__init__()

    def run(self):
        try:
            block = SisBlock(**self.config.dict())
        except DeviceConnectionError as e:
            self.pre_exit()
            self.finished.emit()
            return
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
        measure.save(False)
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
                    "measure_id": measure.id,
                }
            )
            delta_t = datetime.now() - start_t
            logger.info(
                f"[scan_ctrl_current] Proc {proc} %; Time {delta_t}; I set {ctrl_i * 1e3}"
            )
            measure.data = results
            i += 1
            self.progress.emit(int(proc))
        block.set_ctrl_current(initial_ctrl_i)
        self.results.emit(results)
        block.disconnect()
        self.pre_exit()
        measure.save()
        self.finished.emit()

    def pre_exit(self):
        self.config.thread_ctrl_scan = False


class BlockBIASScanThread(Thread):
    results = pyqtSignal(dict)
    stream_result = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, cid: int, voltage_start, voltage_stop, voltage_points):
        self.config = ScontelSisBlockManager.get_config(cid)
        self.config.thread_bias_scan = True
        self.voltage_start = voltage_start
        self.voltage_stop = voltage_stop
        self.voltage_stop = voltage_stop
        self.voltage_points = voltage_points
        super().__init__()

    def run(self):
        try:
            block = SisBlock(**self.config.dict())
        except DeviceConnectionError as e:
            self.pre_exit()
            self.finished.emit()
            return
        results = {
            "i_get": [],
            "v_set": [],
            "v_get": [],
            "time": [],
        }
        initial_v = block.get_bias_voltage()
        v_range = np.linspace(
            self.voltage_start * 1e-3,
            self.voltage_stop * 1e-3,
            self.voltage_points,
        )
        start_t = datetime.now()
        i = 0
        measure = MeasureModel.objects.create(
            measure_type=MeasureType.IV_CURVE, data={}
        )
        measure.save(False)
        for v_set in v_range:
            if not self.config.thread_bias_scan:
                break
            proc = round((i / state.BLOCK_BIAS_VOLT_POINTS) * 100, 2)
            block.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            time.sleep(state.BLOCK_CTRL_STEP_DELAY)
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
                    "measure_id": measure.id,
                }
            )
            delta_t = datetime.now() - start_t
            results["time"].append(delta_t.total_seconds())
            measure.data = results
            i += 1
            self.progress.emit(int(proc))
            logger.info(f"[scan_bias] Proc {proc} %; Time {delta_t}; V_set {v_set}")
        block.set_bias_voltage(initial_v)
        block.disconnect()
        measure.save()
        self.results.emit(results)
        self.finished.emit()

    def pre_exit(self):
        self.config.thread_bias_scan = False


class BlockTabWidget(QWidget):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        layout = QVBoxLayout(self)
        self.createGroupMonitor()
        self.createGroupValuesSet()
        self.createGroupBiasScan()
        self.createGroupCTRLScan()
        layout.addWidget(self.groupMonitor)
        layout.addSpacing(10)
        layout.addWidget(self.rowValuesSet)
        layout.addSpacing(10)
        layout.addWidget(self.groupBiasScan)
        layout.addSpacing(10)
        layout.addWidget(self.groupCTRLScan)
        layout.addWidget(SisDemagnetisationWidget(self))
        layout.addStretch()

        self.setLayout(layout)

        self.biasGraphDockWidget = None
        self.ctrlGraphDockWidget = None

    def show_ctrl_graph_window(self, results: dict):
        if self.ctrlGraphDockWidget is None:
            return
        self.ctrlGraphDockWidget.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
            measure_id=results.get("measure_id"),
        )
        self.ctrlGraphDockWidget.widget().show()

    def show_bias_graph_window(self, results):
        if self.biasGraphDockWidget is None:
            return
        self.biasGraphDockWidget.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
            measure_id=results.get("measure_id"),
        )
        self.biasGraphDockWidget.widget().show()

    def scan_ctrl_current(self):
        self.block_ctrl_scan_thread = BlockCLScanThread(cid=self.cid)
        self.block_ctrl_scan_thread.stream_result.connect(self.show_ctrl_graph_window)

        state.BLOCK_CTRL_CURR_FROM = self.ctrlCurrentFrom.value()
        state.BLOCK_CTRL_CURR_TO = self.ctrlCurrentTo.value()
        state.BLOCK_CTRL_POINTS = int(self.ctrlPoints.value())
        state.BLOCK_CTRL_SCAN_THREAD = True
        state.BLOCK_CTRL_STEP_DELAY = self.ctrlStepDelay.value()

        self.ctrlGraphDockWidget = Dock.ex.dock_manager.findDockWidget("I-CL curve")

        self.block_ctrl_scan_thread.start()

        self.btnCTRLScan.setEnabled(False)
        self.block_ctrl_scan_thread.finished.connect(
            lambda: self.btnCTRLScan.setEnabled(True)
        )
        self.btnCTRLStopScan.setEnabled(True)
        self.block_ctrl_scan_thread.finished.connect(
            lambda: self.btnCTRLStopScan.setEnabled(False)
        )
        self.block_ctrl_scan_thread.finished.connect(
            lambda: self.ctrlScanProgress.setValue(0)
        )
        self.block_ctrl_scan_thread.progress.connect(
            lambda x: self.ctrlScanProgress.setValue(x)
        )

    def stop_scan_ctrl_current(self):
        self.block_ctrl_scan_thread.quit()

    def set_block_bias_short_status(self):
        config = ScontelSisBlockManager.get_config(self.cid)
        try:
            block = SisBlock(**config.dict())
        except DeviceConnectionError:
            return

        if config.bias_short_status == "1":
            status = "0"
        else:
            status = "1"
        block.set_bias_short_status(status)
        new_status = block.get_bias_short_status()
        config.bias_short_status = new_status
        self.btnSetBiasShortStatus.setText(
            f"{state.BLOCK_SHORT_STATUS_MAP.get(config.bias_short_status)}"
        )
        block.disconnect()

    def set_block_ctrl_short_status(self):
        config = ScontelSisBlockManager.get_config(self.cid)
        try:
            block = SisBlock(**config.dict())
        except DeviceConnectionError:
            return

        if config.ctrl_short_status == "1":
            status = "0"
        else:
            status = "1"
        block.set_ctrl_short_status(status)
        new_status = block.get_ctrl_short_status()
        config.ctrl_short_status = new_status
        self.btnSetCtrlShortStatus.setText(
            f"{state.BLOCK_SHORT_STATUS_MAP.get(config.ctrl_short_status)}"
        )
        block.disconnect()

    def scan_bias_iv(self):
        self.block_bias_scan_thread = BlockBIASScanThread(
            cid=self.cid,
            voltage_start=self.biasVoltageFrom.value(),
            voltage_stop=self.biasVoltageTo.value(),
            voltage_points=int(self.biasPoints.value()),
        )
        self.block_bias_scan_thread.stream_result.connect(self.show_bias_graph_window)

        self.biasGraphDockWidget = Dock.ex.dock_manager.findDockWidget("I-V curve")

        self.block_bias_scan_thread.start()

        self.btnBiasScan.setEnabled(False)
        self.block_bias_scan_thread.finished.connect(
            lambda: self.btnBiasScan.setEnabled(True)
        )

        self.btnBiasStopScan.setEnabled(True)
        self.block_bias_scan_thread.finished.connect(
            lambda: self.btnBiasStopScan.setEnabled(False)
        )
        self.block_bias_scan_thread.progress.connect(
            lambda x: self.biasScanProgress.setValue(x)
        )
        self.block_bias_scan_thread.finished.connect(
            lambda: self.biasScanProgress.setValue(0)
        )

    def stop_scan_bias_iv(self):
        self.block_bias_scan_thread.quit()

    def startStreamBlock(self):
        self.stream_thread = BlockStreamThread(
            cid=self.cid, stream_plot=self.plotStream.isChecked()
        )

        self.stream_thread.cl_current.connect(
            lambda x: self.ctrlCurrentGet.setText(f"{round(x * 1e3, 3)}")
        )
        self.stream_thread.bias_current.connect(
            lambda x: self.sisCurrentGet.setText(f"{round(x * 1e6, 3)}")
        )
        self.stream_thread.bias_voltage.connect(
            lambda x: self.sisVoltageGet.setText(f"{round(x * 1e3, 3)}")
        )

        self.stream_thread.plot_data.connect(self.show_bias_graph_window)

        self.biasGraphDockWidget = Dock.ex.dock_manager.findDockWidget("I-V curve")

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
        vlayout = QVBoxLayout()
        layout = QGridLayout()
        hlayout = QHBoxLayout()

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

        self.btnStartStreamBlock = Button("Start Stream", animate=True)
        self.btnStartStreamBlock.clicked.connect(self.startStreamBlock)

        self.btnStopStreamBlock = Button("Stop Stream")
        self.btnStopStreamBlock.setEnabled(False)
        self.btnStopStreamBlock.clicked.connect(self.stopStreamBlock)

        self.plotStream = QCheckBox("Plot stream")
        self.plotStream.setChecked(False)

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

        hlayout.addWidget(self.btnStartStreamBlock)
        hlayout.addWidget(self.btnStopStreamBlock)
        hlayout.addWidget(self.plotStream)

        vlayout.addLayout(layout)
        vlayout.addLayout(hlayout)

        self.groupMonitor.setLayout(vlayout)

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

        self.btnSetBiasVoltage = Button("Set BIAS voltage", animate=True)
        self.btnSetBiasVoltage.clicked.connect(self.set_bias_voltage)

        self.ctrlCurrentSetLabel = QLabel(self)
        self.ctrlCurrentSetLabel.setText("CL current, mA")
        self.ctrlCurrentSet = DoubleSpinBox(self)
        self.ctrlCurrentSet.setRange(
            state.BLOCK_CTRL_CURR_MIN_VALUE, state.BLOCK_CTRL_CURR_MAX_VALUE
        )

        self.btnSetCTRLCurrent = Button("Set CL current", animate=True)
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

        self.btnCalibrateBlock = Button("Calibrate sis block", animate=True)
        self.btnCalibrateBlock.clicked.connect(self.calibrate_sis_block)

        layout.addWidget(self.sisVoltageSetLabel, 1, 0)
        layout.addWidget(self.sisVoltageSet, 1, 1)
        layout.addWidget(self.btnSetBiasVoltage, 1, 2)
        layout.addWidget(self.ctrlCurrentSetLabel, 2, 0)
        layout.addWidget(self.ctrlCurrentSet, 2, 1)
        layout.addWidget(self.btnSetCTRLCurrent, 2, 2)
        layout.addWidget(self.btnSetBiasShortStatusLabel, 3, 0)
        layout.addWidget(self.btnSetBiasShortStatus, 3, 1)
        layout.addWidget(self.btnSetCtrlShortStatusLabel, 4, 0)
        layout.addWidget(self.btnSetCtrlShortStatus, 4, 1)
        layout.addWidget(self.btnCalibrateBlock, 5, 0)

        self.rowValuesSet.setLayout(layout)

    def set_bias_voltage(self):
        self.thread_set_bias_voltage = BlockSetBiasVoltageThread(
            cid=self.cid, voltage=self.sisVoltageSet.value() * 1e-3
        )
        self.btnSetBiasVoltage.setEnabled(False)
        self.thread_set_bias_voltage.start()
        self.thread_set_bias_voltage.finished.connect(
            lambda: self.btnSetBiasVoltage.setEnabled(True)
        )

    def set_ctrl_current(self):
        self.thread_set_ctrl_current = BlockSetCtrlCurrentThread(
            cid=self.cid, current=self.ctrlCurrentSet.value() * 1e-3
        )
        self.btnSetCTRLCurrent.setEnabled(False)
        self.thread_set_ctrl_current.start()
        self.thread_set_ctrl_current.finished.connect(
            lambda: self.btnSetCTRLCurrent.setEnabled(True)
        )

    def calibrate_sis_block(self):
        self.calibrate_thread = BlockCalibrateThread(self, cid=self.cid)
        self.calibrate_thread.finished.connect(
            lambda: self.btnCalibrateBlock.setEnabled(True)
        )

        self.btnCalibrateBlock.setEnabled(False)
        self.calibrate_thread.start()

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

        self.ctrlScanProgress = QProgressBar(self)
        self.ctrlScanProgress.setValue(0)
        self.btnCTRLScan = Button("Scan CL Current", animate=True)
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
        layout.addWidget(self.ctrlScanProgress, 5, 0, 1, 2)
        layout.addWidget(self.btnCTRLScan, 6, 0)
        layout.addWidget(self.btnCTRLStopScan, 6, 1)

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

        self.biasScanProgress = QProgressBar(self)
        self.biasScanProgress.setValue(0)

        self.btnBiasScan = Button("Scan Bias IV", animate=True)
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
        layout.addWidget(self.biasScanProgress, 4, 0, 1, 2)
        layout.addWidget(self.btnBiasScan, 5, 0)
        layout.addWidget(self.btnBiasStopScan, 5, 1)

        self.groupBiasScan.setLayout(layout)
