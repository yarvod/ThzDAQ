import time
from datetime import datetime

import numpy as np
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QVBoxLayout,
    QWidget,
    QLabel,
    QPushButton,
    QSizePolicy,
    QCheckBox,
)

from interface.windows.nrxStreamGraph import NRXStreamGraphWindow
from store.base import MeasureModel, MeasureType
from store.state import state
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.DoubleSpinBox import DoubleSpinBox
from interface.windows.biasPowerGraphWindow import BiasPowerGraphWindow
from utils.logger import logger


class NRXBlockStreamThread(QThread):
    meas = pyqtSignal(dict)

    def run(self):
        nrx = NRXPowerMeter(
            ip=state.NRX_IP,
            filter_time=state.NRX_FILTER_TIME,
            aperture_time=state.NRX_APER_TIME,
        )
        i = 0
        start_time = time.time()
        while state.NRX_STREAM_THREAD:
            power = nrx.get_power()
            meas_time = time.time() - start_time
            if not power:
                time.sleep(2)
                continue

            self.meas.emit({"power": power, "time": meas_time, "reset": i == 0})
            i += 1
        self.finished.emit()

    def terminate(self) -> None:
        state.NRX_STREAM_THREAD = False
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")

    def exit(self, returnCode: int = ...) -> None:
        state.NRX_STREAM_THREAD = False
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")

    def quit(self) -> None:
        state.NRX_STREAM_THREAD = False
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")


class BiasPowerThread(QThread):
    results = pyqtSignal(dict)
    stream_results = pyqtSignal(dict)

    def run(self):
        nrx = NRXPowerMeter(
            ip=state.NRX_IP,
            filter_time=state.NRX_FILTER_TIME,
            aperture_time=state.NRX_APER_TIME,
        )
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()
        results = {
            "current_get": [],
            "voltage_set": [],
            "voltage_get": [],
            "power": [],
            "time": [],
        }
        v_range = np.linspace(
            state.BLOCK_BIAS_VOLT_FROM * 1e-3,
            state.BLOCK_BIAS_VOLT_TO * 1e-3,
            state.BLOCK_BIAS_VOLT_POINTS,
        )
        measure = MeasureModel.objects.create(
            measure_type=MeasureType.BIAS_POWER, data={}
        )
        initial_v = block.get_bias_voltage()
        initial_time = time.time()
        for i, voltage_set in enumerate(v_range):
            if not state.BLOCK_BIAS_POWER_MEASURE_THREAD:
                break

            block.set_bias_voltage(voltage_set)

            if i == 0:
                time.sleep(0.5)
                initial_time = time.time()

            time.sleep(state.BLOCK_BIAS_STEP_DELAY)
            voltage_get = block.get_bias_voltage()
            if not voltage_get:
                continue
            current_get = block.get_bias_current()
            if not current_get:
                continue
            power = nrx.get_power()
            time_step = time.time() - initial_time

            self.stream_results.emit(
                {
                    "x": [voltage_get * 1e3],
                    "y": [power],
                    "new_plot": i == 0,
                }
            )

            results["voltage_set"].append(voltage_set)
            results["voltage_get"].append(voltage_get)
            results["current_get"].append(current_get)
            results["power"].append(power)
            results["time"].append(time_step)
            measure.data = results

        block.set_bias_voltage(initial_v)
        measure.finished = datetime.now()
        measure.save()
        self.results.emit(results)
        self.finished.emit()

    def terminate(self) -> None:
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")
        state.BLOCK_BIAS_POWER_MEASURE_THREAD = False

    def quit(self) -> None:
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")
        state.BLOCK_BIAS_POWER_MEASURE_THREAD = False

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")
        state.BLOCK_BIAS_POWER_MEASURE_THREAD = False


class NRXTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.biasPowerGraphWindow = None
        self.powerStreamGraphWindow = None
        self.createGroupNRX()
        self.createGroupBiasPowerScan()
        self.layout.addWidget(self.groupNRX)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupBiasPowerScan)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupNRX(self):
        self.groupNRX = QGroupBox("Power meter monitor")
        self.groupNRX.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.nrxPowerLabel = QLabel("<h4>Power, dBm</h4>")
        self.nrxPower = QLabel(self)
        self.nrxPower.setText("0.0")
        self.nrxPower.setStyleSheet("font-size: 23px; font-weight: bold;")

        self.btnStartStreamNRX = QPushButton("Start Stream")
        self.btnStartStreamNRX.clicked.connect(self.start_stream_nrx)

        self.btnStopStreamNRX = QPushButton("Stop Stream")
        self.btnStopStreamNRX.setEnabled(False)
        self.btnStopStreamNRX.clicked.connect(self.stop_stream_nrx)

        self.checkNRXStreamPlot = QCheckBox(self)
        self.checkNRXStreamPlot.setText("Plot stream time line")

        self.nrxStreamWindowTimeLabel = QLabel(self)
        self.nrxStreamWindowTimeLabel.setText("Time window, s")
        self.nrxStreamWindowTime = DoubleSpinBox(self)
        self.nrxStreamWindowTime.setRange(10, 3600)
        self.nrxStreamWindowTime.setDecimals(0)
        self.nrxStreamWindowTime.setValue(state.NRX_STREAM_GRAPH_TIME)

        layout.addWidget(
            self.nrxPowerLabel, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(self.nrxPower, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            self.btnStartStreamNRX, 2, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.btnStopStreamNRX, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.checkNRXStreamPlot, 3, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.nrxStreamWindowTimeLabel, 4, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.nrxStreamWindowTime, 4, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.groupNRX.setLayout(layout)

    def start_stream_nrx(self):
        self.nrx_stream_thread = NRXBlockStreamThread()

        state.NRX_STREAM_THREAD = True
        state.NRX_STREAM_PLOT_GRAPH = self.checkNRXStreamPlot.isChecked()
        state.NRX_STREAM_GRAPH_TIME = self.nrxStreamWindowTime.value()

        self.nrx_stream_thread.meas.connect(self.update_nrx_stream_values)
        self.nrx_stream_thread.start()

        self.btnStartStreamNRX.setEnabled(False)
        self.nrx_stream_thread.finished.connect(
            lambda: self.btnStartStreamNRX.setEnabled(True)
        )

        self.btnStopStreamNRX.setEnabled(True)
        self.nrx_stream_thread.finished.connect(
            lambda: self.btnStopStreamNRX.setEnabled(False)
        )

    def show_power_stream_graph(self, x: float, y: float, reset: bool = True):
        if self.powerStreamGraphWindow is None:
            self.powerStreamGraphWindow = NRXStreamGraphWindow()
        self.powerStreamGraphWindow.plotNew(x=x, y=y, reset_data=reset)
        self.powerStreamGraphWindow.show()

    def update_nrx_stream_values(self, measure: dict):
        self.nrxPower.setText(f"{round(measure.get('power'), 3)}")
        if state.NRX_STREAM_PLOT_GRAPH:
            self.show_power_stream_graph(
                x=measure.get("time"),
                y=measure.get("power"),
                reset=measure.get("reset"),
            )

    def stop_stream_nrx(self):
        self.nrx_stream_thread.quit()
        self.nrx_stream_thread.exit(0)

    def createGroupBiasPowerScan(self):
        self.groupBiasPowerScan = QGroupBox("Scan Bias Power")
        self.groupBiasPowerScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.voltFromLabel = QLabel(self)
        self.voltFromLabel.setText("Bias voltage from, mV")
        self.voltFrom = DoubleSpinBox(self)
        self.voltFrom.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltToLabel = QLabel(self)
        self.voltToLabel.setText("Bias voltage to, mV")
        self.voltTo = DoubleSpinBox(self)
        self.voltTo.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltPointsLabel = QLabel(self)
        self.voltPointsLabel.setText("Points count")
        self.voltPoints = DoubleSpinBox(self)
        self.voltPoints.setMaximum(state.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(state.BLOCK_BIAS_VOLT_POINTS)

        self.voltStepDelayLabel = QLabel(self)
        self.voltStepDelayLabel.setText("Step delay, s")
        self.voltStepDelay = DoubleSpinBox(self)
        self.voltStepDelay.setRange(0.01, 10)
        self.voltStepDelay.setValue(state.BLOCK_BIAS_STEP_DELAY)

        self.btnStartBiasPowerScan = QPushButton("Start Scan")
        self.btnStartBiasPowerScan.clicked.connect(self.start_measure_bias_power)

        self.btnStopBiasPowerScan = QPushButton("Stop Scan")
        self.btnStopBiasPowerScan.clicked.connect(self.stop_measure_bias_power)
        self.btnStopBiasPowerScan.setEnabled(False)

        layout.addWidget(self.voltFromLabel, 1, 0)
        layout.addWidget(self.voltFrom, 1, 1)
        layout.addWidget(self.voltToLabel, 2, 0)
        layout.addWidget(self.voltTo, 2, 1)
        layout.addWidget(self.voltPointsLabel, 3, 0)
        layout.addWidget(self.voltPoints, 3, 1)
        layout.addWidget(self.voltStepDelayLabel, 4, 0)
        layout.addWidget(self.voltStepDelay, 4, 1)
        layout.addWidget(self.btnStartBiasPowerScan, 5, 0)
        layout.addWidget(self.btnStopBiasPowerScan, 5, 1)

        self.groupBiasPowerScan.setLayout(layout)

    def start_measure_bias_power(self):
        self.bias_power_thread = BiasPowerThread()

        state.BLOCK_BIAS_POWER_MEASURE_THREAD = True
        state.BLOCK_BIAS_VOLT_FROM = self.voltFrom.value()
        state.BLOCK_BIAS_VOLT_TO = self.voltTo.value()
        state.BLOCK_BIAS_VOLT_POINTS = int(self.voltPoints.value())
        state.BLOCK_BIAS_STEP_DELAY = self.voltStepDelay.value()

        self.bias_power_thread.stream_results.connect(self.show_bias_power_graph)
        self.bias_power_thread.start()

        self.btnStartBiasPowerScan.setEnabled(False)
        self.bias_power_thread.finished.connect(
            lambda: self.btnStartBiasPowerScan.setEnabled(True)
        )

        self.btnStopBiasPowerScan.setEnabled(True)
        self.bias_power_thread.finished.connect(
            lambda: self.btnStopBiasPowerScan.setEnabled(False)
        )

    def stop_measure_bias_power(self):
        self.bias_power_thread.exit(0)

    def show_bias_power_graph(self, results):
        if self.biasPowerGraphWindow is None:
            self.biasPowerGraphWindow = BiasPowerGraphWindow()
        self.biasPowerGraphWindow.plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
        )
        self.biasPowerGraphWindow.show()
