import time

import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QThread
from PyQt6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QVBoxLayout,
    QWidget,
    QLabel,
    QPushButton,
    QSizePolicy,
    QDoubleSpinBox,
    QFileDialog,
)

from config import config
from interactors.block import Block
from interactors.rs_nrx import NRXBlock
from ui.windows.biasPowerGraphWindow import BiasPowerGraphWindow


class NRXBlockStreamWorker(QObject):
    finished = pyqtSignal()
    power = pyqtSignal(float)

    def run(self):
        block = NRXBlock(
            ip=config.NRX_IP,
            filter_time=config.NRX_FILTER_TIME,
            aperture_time=config.NRX_APER_TIME,
        )
        while config.NRX_STREAM:
            power = block.get_power()
            self.power.emit(power)
        block.close()
        self.finished.emit()


class BiasPowerWorker(QObject):
    finished = pyqtSignal()
    results = pyqtSignal(dict)
    stream_results = pyqtSignal(dict)

    def run(self):
        nrx = NRXBlock(
            ip=config.NRX_IP,
            filter_time=config.NRX_FILTER_TIME,
            aperture_time=config.NRX_APER_TIME,
        )
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
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
            config.BLOCK_BIAS_VOLT_FROM * 1e-3,
            config.BLOCK_BIAS_VOLT_TO * 1e-3,
            config.BLOCK_BIAS_VOLT_POINTS,
        )
        initial_v = block.get_bias_voltage()
        initial_time = time.time()
        for i, voltage_set in enumerate(v_range):
            if not config.BLOCK_BIAS_POWER_MEASURE:
                break

            if i == 0:
                time.sleep(0.5)
                initial_time = time.time()

            block.set_bias_voltage(voltage_set)
            time.sleep(config.BLOCK_BIAS_STEP_DELAY)
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
                    "x": [voltage_get],
                    "y": [power],
                    "new_plot": i == 0,
                }
            )

            results["voltage_set"].append(voltage_set)
            results["voltage_get"].append(voltage_get)
            results["current_get"].append(current_get)
            results["power"].append(power)
            results["time"].append(time_step)

        block.set_bias_voltage(initial_v)
        block.disconnect()
        nrx.close()
        self.results.emit(results)
        self.finished.emit()


class NRXTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.biasPowerGraphWindow = None
        self.createGroupNRX()
        self.createGroupBiasPowerScan()
        self.layout.addWidget(self.groupNRX, alignment=Qt.AlignmentFlag.AlignTop)
        self.layout.addWidget(self.groupBiasPowerScan)
        self.setLayout(self.layout)

    def createGroupNRX(self):
        self.groupNRX = QGroupBox("NRX monitor")
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

        self.groupNRX.setLayout(layout)

    def start_stream_nrx(self):
        self.nrx_stream_thread = QThread()
        self.nrx_stream_worker = NRXBlockStreamWorker()
        self.nrx_stream_worker.moveToThread(self.nrx_stream_thread)

        config.NRX_STREAM = True

        self.nrx_stream_thread.started.connect(self.nrx_stream_worker.run)
        self.nrx_stream_worker.finished.connect(self.nrx_stream_thread.quit)
        self.nrx_stream_worker.finished.connect(self.nrx_stream_worker.deleteLater)
        self.nrx_stream_thread.finished.connect(self.nrx_stream_thread.deleteLater)
        self.nrx_stream_worker.power.connect(
            lambda x: self.nrxPower.setText(f"{round(x, 3)}")
        )
        self.nrx_stream_thread.start()

        self.btnStartStreamNRX.setEnabled(False)
        self.nrx_stream_thread.finished.connect(
            lambda: self.btnStartStreamNRX.setEnabled(True)
        )

        self.btnStopStreamNRX.setEnabled(True)
        self.nrx_stream_thread.finished.connect(
            lambda: self.btnStopStreamNRX.setEnabled(False)
        )

    def stop_stream_nrx(self):
        config.NRX_STREAM = False

    def createGroupBiasPowerScan(self):
        self.groupBiasPowerScan = QGroupBox("Scan Bias Power")
        self.groupBiasPowerScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.voltFromLabel = QLabel(self)
        self.voltFromLabel.setText("Bias voltage from, mV")
        self.voltFrom = QDoubleSpinBox(self)
        self.voltFrom.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltToLabel = QLabel(self)
        self.voltToLabel.setText("Bias voltage to, mV")
        self.voltTo = QDoubleSpinBox(self)
        self.voltTo.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltPointsLabel = QLabel(self)
        self.voltPointsLabel.setText("Points count")
        self.voltPoints = QDoubleSpinBox(self)
        self.voltPoints.setMaximum(config.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(config.BLOCK_BIAS_VOLT_POINTS)

        self.voltStepDelayLabel = QLabel(self)
        self.voltStepDelayLabel.setText("Step delay, s")
        self.voltStepDelay = QDoubleSpinBox(self)
        self.voltStepDelay.setRange(0, 10)
        self.voltStepDelay.setValue(config.BLOCK_BIAS_STEP_DELAY)

        self.btnStartBiasPowerScan = QPushButton("Start Scan")
        self.btnStartBiasPowerScan.clicked.connect(self.start_measure_bias_power)

        self.btnStopBiasPowerScan = QPushButton("Stop Scan")
        self.btnStopBiasPowerScan.clicked.connect(self.stop_measure_bias_power)

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
        self.bias_power_thread = QThread()
        self.bias_power_worker = BiasPowerWorker()
        self.bias_power_worker.moveToThread(self.bias_power_thread)

        config.BLOCK_BIAS_POWER_MEASURE = True
        config.BLOCK_BIAS_VOLT_FROM = self.voltFrom.value()
        config.BLOCK_BIAS_VOLT_TO = self.voltTo.value()
        config.BLOCK_BIAS_VOLT_POINTS = int(self.voltPoints.value())
        config.BLOCK_BIAS_STEP_DELAY = self.voltStepDelay.value()

        self.bias_power_thread.started.connect(self.bias_power_worker.run)
        self.bias_power_worker.finished.connect(self.bias_power_thread.quit)
        self.bias_power_worker.finished.connect(self.bias_power_worker.deleteLater)
        self.bias_power_thread.finished.connect(self.bias_power_thread.deleteLater)
        self.bias_power_worker.stream_results.connect(self.show_bias_power_graph)
        self.bias_power_worker.results.connect(self.save_bias_power_scan)
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
        config.BLOCK_BIAS_POWER_MEASURE = False

    def show_bias_power_graph(self, results):
        if self.biasPowerGraphWindow is None:
            self.biasPowerGraphWindow = BiasPowerGraphWindow()
        self.biasPowerGraphWindow.plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
        )
        self.biasPowerGraphWindow.show()

    def save_bias_power_scan(self, results):
        try:
            filepath = QFileDialog.getSaveFileName()[0]
            df = pd.DataFrame(results)
            df.to_csv(filepath, index=False)
        except (IndexError, FileNotFoundError):
            pass
