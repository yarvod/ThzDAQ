import logging
import json
import time
from datetime import datetime

import numpy as np
from PySide6.QtWidgets import (
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
    QDialog,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from interface.components.Scontel.sisDemagnetisationWidget import (
    SisDemagnetisationWidget,
)
from interface.components.Scontel.sisCalibrationDialog import SisCalibrationDialog
from interface.components.ui.Button import Button
from store import ScontelSisBlockManager
from store.sisCalibration import evaluate_sis_calibration
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
            calibration_coefficients = evaluate_sis_calibration(
                self.config.calibration_coefficients
            )
            payload = json.dumps(
                calibration_coefficients,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            self.block.adapter.query(f"BIAS:{self.config.bias_dev}:EEPR {payload}")
            logger.info(
                "Calibration coefficients written to SIS block %s (%s)",
                self.config.cid,
                self.config.bias_dev,
            )
        except DeviceConnectionError as e:
            logger.exception(f"{e}", exc_info=True)
        except Exception:
            logger.exception(
                "Unable to calibrate SIS block %s", self.config.cid, exc_info=True
            )
        finally:
            if self.block is not None:
                try:
                    self.block.disconnect()
                except Exception:
                    logger.exception(
                        "Unable to disconnect SIS block %s after calibration",
                        self.config.cid,
                    )
            self.finished.emit()


class BlockStreamThread(Thread):
    cl_current = Signal(float)
    bias_voltage = Signal(float)
    bias_current = Signal(float)
    plot_data = Signal(dict)

    def __init__(
        self,
        cid: int,
        polling_interval: float,
        stream_plot: bool = False,
        store_data: bool = False,
    ):
        self.config = ScontelSisBlockManager.get_config(cid)
        self.cid = cid
        self.polling_interval = float(polling_interval)
        if not 0 <= self.polling_interval <= 5:
            raise ValueError("Polling interval must be between 0 and 5 seconds")
        self.config.thread_stream = True
        self.stream_plot = stream_plot
        self.store_data = store_data
        self.measure = None
        if self.store_data:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureType.SIS_BLOCK_STREAM,
                data={
                    "block_cid": self.cid,
                    "polling_interval_s": self.polling_interval,
                    "time_s": [],
                    "bias_voltage_mV": [],
                    "bias_current_uA": [],
                    "ctrl_current_mA": [],
                },
            )
            self.measure.save(finish=False)
        super().__init__()

    def run(self):
        block = None
        try:
            block = SisBlock(**self.config.dict())
            start_time = time.monotonic()
            plot_started = False

            while self.config.thread_stream:
                sample_started = time.monotonic()
                bias_voltage = block.get_bias_voltage()
                bias_current = block.get_bias_current()
                cl_current = block.get_ctrl_current()

                if bias_voltage is not None:
                    self.bias_voltage.emit(bias_voltage)
                if bias_current is not None:
                    self.bias_current.emit(bias_current)
                if cl_current is not None:
                    self.cl_current.emit(cl_current)

                elapsed = time.monotonic() - start_time
                bias_voltage_mv = None if bias_voltage is None else bias_voltage * 1e3
                bias_current_ua = None if bias_current is None else bias_current * 1e6
                ctrl_current_ma = None if cl_current is None else cl_current * 1e3

                if self.measure is not None:
                    self.measure.data["time_s"].append(elapsed)
                    self.measure.data["bias_voltage_mV"].append(bias_voltage_mv)
                    self.measure.data["bias_current_uA"].append(bias_current_ua)
                    self.measure.data["ctrl_current_mA"].append(ctrl_current_ma)

                if (
                    self.stream_plot
                    and bias_voltage_mv is not None
                    and bias_current_ua is not None
                ):
                    self.plot_data.emit(
                        {
                            "x": [bias_voltage_mv],
                            "y": [bias_current_ua],
                            "new_plot": not plot_started,
                            "measure_id": (
                                self.measure.id if self.measure is not None else None
                            ),
                        }
                    )
                    plot_started = True

                if not self._wait_for_next_poll(sample_started):
                    break
        except DeviceConnectionError:
            logger.exception("Unable to connect to SIS block %s", self.cid)
        except Exception:
            logger.exception("SIS block %s monitoring failed", self.cid)
        finally:
            if block is not None:
                try:
                    block.disconnect()
                except Exception:
                    logger.exception(
                        "Unable to disconnect SIS block %s after monitoring",
                        self.cid,
                    )
            if self.measure is not None:
                self.measure.save()
            self.pre_exit()

    def _wait_for_next_poll(self, sample_started: float) -> bool:
        deadline = sample_started + self.polling_interval
        while self.config.thread_stream:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.05, remaining))
        return False

    def pre_exit(self, *args, **kwargs):
        self.config.thread_stream = False


class BlockCLScanThread(Thread):
    results = Signal(dict)
    stream_result = Signal(dict)
    progress = Signal(int)

    def __init__(
        self,
        cid: int,
        current_start: float,
        current_stop: float,
        current_points: int,
        step_delay: float,
    ):
        self.config = ScontelSisBlockManager.get_config(cid)
        self.current_start = current_start
        self.current_stop = current_stop
        self.current_points = current_points
        self.step_delay = step_delay
        self.config.thread_ctrl_scan = True
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
            self.current_start,
            self.current_stop,
            self.current_points,
        )
        initial_ctrl_i = block.get_ctrl_current()
        start_t = datetime.now()
        i = 0
        measure = MeasureModel.objects.create(
            measure_type=MeasureType.CL_CURVE, data={}
        )
        measure.save(False)
        for ctrl_i in ctrl_i_range:
            if not self.config.thread_ctrl_scan:
                break
            proc = round((i / self.current_points) * 100, 2)
            results["ctrl_i_set"].append(ctrl_i * 1e3)
            block.set_ctrl_current(ctrl_i)
            if i == 0:
                time.sleep(1)
            time.sleep(self.step_delay)
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
    results = Signal(dict)
    stream_result = Signal(dict)
    progress = Signal(int)

    def __init__(
        self,
        cid: int,
        voltage_start: float,
        voltage_stop: float,
        voltage_points: int,
        step_delay: float,
    ):
        self.config = ScontelSisBlockManager.get_config(cid)
        self.config.thread_bias_scan = True
        self.voltage_start = voltage_start
        self.voltage_stop = voltage_stop
        self.voltage_stop = voltage_stop
        self.voltage_points = voltage_points
        self.step_delay = step_delay
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
            proc = round((i / self.voltage_points) * 100, 2)
            block.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            time.sleep(self.step_delay)
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
        self.biasGraphDockWidget = Dock.ex.dock_manager.findDockWidget("I-V curve")
        self.ctrlGraphDockWidget = Dock.ex.dock_manager.findDockWidget("I-CL curve")
        self.iv_plot_number = 1
        self.icl_plot_number = 1
        self.block_bias_scan_thread = None
        self.stream_thread = None

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
        layout.addWidget(SisDemagnetisationWidget(self, cid=cid))
        layout.addStretch()

        self.setLayout(layout)

    def show_ctrl_graph_window(self, results: dict):
        if results.get("new_plot"):
            self.icl_plot_number = (
                self.ctrlGraphDockWidget.widget().get_last_plot_number() + 1
            )
        self.ctrlGraphDockWidget.widget().plot(
            x=results.get("x", []),
            y=results.get("y", []),
            plot_num=self.icl_plot_number,
            measure_id=results.get("measure_id"),
        )
        self.ctrlGraphDockWidget.widget().show()

    def show_bias_graph_window(self, results):
        if results.get("new_plot"):
            self.iv_plot_number = (
                self.biasGraphDockWidget.widget().get_last_plot_number() + 1
            )
        self.biasGraphDockWidget.widget().plot(
            x=results.get("x", []),
            y=results.get("y", []),
            plot_num=self.iv_plot_number,
            measure_id=results.get("measure_id"),
        )
        self.biasGraphDockWidget.widget().show()

    def scan_ctrl_current(self):
        self.block_ctrl_scan_thread = BlockCLScanThread(
            cid=self.cid,
            current_start=self.ctrlCurrentFrom.value() / 1e3,
            current_stop=self.ctrlCurrentTo.value() / 1e3,
            current_points=int(self.ctrlPoints.value()),
            step_delay=self.ctrlStepDelay.value(),
        )
        self.block_ctrl_scan_thread.stream_result.connect(self.show_ctrl_graph_window)

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
            step_delay=self.biasStepDelay.value(),
        )
        self.block_bias_scan_thread.stream_result.connect(self.show_bias_graph_window)

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
            cid=self.cid,
            polling_interval=self.streamPollingInterval.value(),
            stream_plot=self.plotStream.isChecked(),
            store_data=self.storeStreamData.isChecked(),
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
        self.plotStream.setEnabled(False)
        self.storeStreamData.setEnabled(False)
        self.streamPollingInterval.setEnabled(False)
        self.stream_thread.finished.connect(lambda: self.plotStream.setEnabled(True))
        self.stream_thread.finished.connect(
            lambda: self.storeStreamData.setEnabled(True)
        )
        self.stream_thread.finished.connect(
            lambda: self.streamPollingInterval.setEnabled(True)
        )

    def stopStreamBlock(self):
        if self.stream_thread is not None:
            self.stream_thread.quit()

    def createGroupMonitor(self):
        self.groupMonitor = QGroupBox("Block Monitor")
        self.groupMonitor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        vlayout = QVBoxLayout()
        layout = QGridLayout()
        options_layout = QGridLayout()
        buttons_layout = QHBoxLayout()

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

        self.storeStreamData = QCheckBox("Store stream data")
        self.storeStreamData.setChecked(False)

        self.streamPollingIntervalLabel = QLabel("Polling interval, s")
        self.streamPollingInterval = DoubleSpinBox(self)
        self.streamPollingInterval.setRange(0, 5)
        self.streamPollingInterval.setDecimals(2)
        self.streamPollingInterval.setValue(0.2)
        self.streamPollingInterval.setMinimumWidth(180)
        self.streamPollingInterval.setToolTip(
            "Delay between SIS block polling cycles, from 0 to 5 seconds"
        )

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

        options_layout.addWidget(self.plotStream, 0, 0)
        options_layout.addWidget(self.storeStreamData, 0, 1)
        options_layout.addWidget(self.streamPollingIntervalLabel, 1, 0)
        options_layout.addWidget(self.streamPollingInterval, 1, 1)
        options_layout.setColumnStretch(1, 1)

        buttons_layout.addWidget(self.btnStartStreamBlock)
        buttons_layout.addWidget(self.btnStopStreamBlock)

        vlayout.addLayout(layout)
        vlayout.addSpacing(6)
        vlayout.addLayout(options_layout)
        vlayout.addLayout(buttons_layout)

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
        self.btnCalibrationCoefficients = Button("Coefficients")
        self.btnCalibrationCoefficients.clicked.connect(
            self.edit_calibration_coefficients
        )

        self.offsetVoltageLabel = QLabel("Voltage offset, mV", self)
        self.offsetVoltage = DoubleSpinBox(self)
        self.offsetVoltage.setDecimals(3)
        self.offsetVoltage.setRange(-10, 10)
        self.offsetVoltage.setValue(
            ScontelSisBlockManager.get_config(self.cid).offset_voltage * 1e3
        )
        self.btnSetOffsetVoltage = Button("Set")
        self.btnSetOffsetVoltage.clicked.connect(self.set_offset_voltage)

        self.offsetCurrentLabel = QLabel("Current offset, mkA", self)
        self.offsetCurrent = DoubleSpinBox(self)
        self.offsetCurrent.setDecimals(3)
        self.offsetCurrent.setRange(-10, 10)
        self.offsetCurrent.setValue(
            ScontelSisBlockManager.get_config(self.cid).offset_current * 1e6
        )
        self.btnSetOffsetCurrent = Button("Set")
        self.btnSetOffsetCurrent.clicked.connect(self.set_offset_current)

        layout.addWidget(self.sisVoltageSetLabel, 0, 0)
        layout.addWidget(self.sisVoltageSet, 0, 1)
        layout.addWidget(self.btnSetBiasVoltage, 0, 2)
        layout.addWidget(self.ctrlCurrentSetLabel, 1, 0)
        layout.addWidget(self.ctrlCurrentSet, 1, 1)
        layout.addWidget(self.btnSetCTRLCurrent, 1, 2)
        layout.addWidget(self.btnSetBiasShortStatusLabel, 2, 0)
        layout.addWidget(self.btnSetBiasShortStatus, 2, 1)
        layout.addWidget(self.btnSetCtrlShortStatusLabel, 3, 0)
        layout.addWidget(self.btnSetCtrlShortStatus, 3, 1)
        layout.addWidget(self.offsetVoltageLabel, 4, 0)
        layout.addWidget(self.offsetVoltage, 4, 1)
        layout.addWidget(self.btnSetOffsetVoltage, 4, 2)
        layout.addWidget(self.offsetCurrentLabel, 5, 0)
        layout.addWidget(self.offsetCurrent, 5, 1)
        layout.addWidget(self.btnSetOffsetCurrent, 5, 2)
        layout.addWidget(self.btnCalibrateBlock, 6, 0)
        layout.addWidget(self.btnCalibrationCoefficients, 6, 1)

        self.rowValuesSet.setLayout(layout)

    def set_offset_voltage(self):
        ScontelSisBlockManager.get_config(self.cid).offset_voltage = (
            self.offsetVoltage.value() / 1e3
        )

    def set_offset_current(self):
        ScontelSisBlockManager.get_config(self.cid).offset_current = (
            self.offsetCurrent.value() / 1e6
        )

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
        self.calibrate_thread.finished.connect(
            lambda: self.btnCalibrationCoefficients.setEnabled(True)
        )

        self.btnCalibrateBlock.setEnabled(False)
        self.btnCalibrationCoefficients.setEnabled(False)
        self.calibrate_thread.start()

    def edit_calibration_coefficients(self):
        config = ScontelSisBlockManager.get_config(self.cid)
        dialog = SisCalibrationDialog(
            self,
            block_name=config.name,
            bias_dev=config.bias_dev,
            calibration_coefficients=config.calibration_coefficients,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ScontelSisBlockManager.save_calibration_coefficients(
                self.cid, dialog.calibration_coefficients
            )
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self,
                "Unable to save calibration coefficients",
                str(error),
            )

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

        self.biasStepDelayLabel = QLabel(self)
        self.biasStepDelayLabel.setText("Step delay, s")
        self.biasStepDelay = DoubleSpinBox(self)
        self.biasStepDelay.setDecimals(2)
        self.biasStepDelay.setRange(0, 10)
        self.biasStepDelay.setValue(0.01)

        self.biasScanProgress = QProgressBar(self)
        self.biasScanProgress.setValue(0)

        self.btnBiasScan = Button("Scan Bias IV", animate=True)
        self.btnBiasScan.clicked.connect(self.scan_bias_iv)

        self.btnBiasStopScan = QPushButton("Stop Scan")
        self.btnBiasStopScan.clicked.connect(self.stop_scan_bias_iv)
        self.btnBiasStopScan.setEnabled(False)

        layout.addWidget(self.biasVoltageFromLabel, 0, 0)
        layout.addWidget(self.biasVoltageFrom, 0, 1)
        layout.addWidget(self.biasVoltageToLabel, 1, 0)
        layout.addWidget(self.biasVoltageTo, 1, 1)
        layout.addWidget(self.biasPointsLabel, 2, 0)
        layout.addWidget(self.biasPoints, 2, 1)
        layout.addWidget(self.biasStepDelayLabel, 3, 0)
        layout.addWidget(self.biasStepDelay, 3, 1)
        layout.addWidget(self.biasScanProgress, 4, 0, 1, 2)
        layout.addWidget(self.btnBiasScan, 5, 0)
        layout.addWidget(self.btnBiasStopScan, 5, 1)

        self.groupBiasScan.setLayout(layout)
