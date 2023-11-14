import time

import numpy as np
from PyQt5.QtCore import pyqtSignal, Qt, QThread
from PyQt5.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QVBoxLayout,
    QWidget,
    QLabel,
    QSizePolicy,
    QCheckBox,
)

from api.Chopper import chopper_manager
from interface.components.ui.Button import Button
from store.base import MeasureModel, MeasureType
from store.state import state
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from utils.functions import get_y_tn
from utils.logger import logger


class NRXBlockStreamThread(QThread):
    meas = pyqtSignal(dict)

    def run(self):
        nrx = NRXPowerMeter(
            ip=state.NRX_IP,
            filter_time=state.NRX_FILTER_TIME,
            aperture_time=state.NRX_APER_TIME,
        )
        data = {"power": [], "time": []}
        if state.NRX_STREAM_STORE_DATA:
            measure = MeasureModel.objects.create(
                measure_type=MeasureType.POWER_STREAM, data=data
            )
            measure.save(False)
        i = 0
        start_time = time.time()
        while state.NRX_STREAM_THREAD:
            power = nrx.get_power()
            meas_time = time.time() - start_time
            if not power:
                time.sleep(2)
                continue

            self.meas.emit({"power": power, "time": meas_time, "reset": i == 0})
            if state.NRX_STREAM_STORE_DATA:
                measure.data["power"].append(power)
                measure.data["time"].append(meas_time)
            i += 1

        if state.NRX_STREAM_STORE_DATA:
            measure.data = data
            measure.save(finish=True)
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
    stream_power = pyqtSignal(dict)
    stream_y_factor = pyqtSignal(dict)
    stream_tn = pyqtSignal(dict)

    def get_results_format(self):
        if state.CHOPPER_SWITCH:
            return {
                "hot": {
                    "current_get": [],
                    "voltage_set": [],
                    "voltage_get": [],
                    "power": [],
                    "time": [],
                },
                "cold": {
                    "current_get": [],
                    "voltage_set": [],
                    "voltage_get": [],
                    "power": [],
                    "time": [],
                },
                "y_factor": [],
                "t_noise": [],
            }
        else:
            return {
                "current_get": [],
                "voltage_set": [],
                "voltage_get": [],
                "power": [],
                "time": [],
            }

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
        results = self.get_results_format()
        v_range = np.linspace(
            state.BLOCK_BIAS_VOLT_FROM * 1e-3,
            state.BLOCK_BIAS_VOLT_TO * 1e-3,
            state.BLOCK_BIAS_VOLT_POINTS,
        )
        measure_type = (
            MeasureType.BIAS_POWER
            if not state.CHOPPER_SWITCH
            else MeasureType.CHOPPER_BIAS_POWER
        )
        measure = MeasureModel.objects.create(measure_type=measure_type, data={})
        measure.save(False)
        initial_v = block.get_bias_voltage()
        initial_time = time.time()
        for switcher in range(2):
            if not state.CHOPPER_SWITCH and switcher == 0:
                continue
            chopper_state = None
            if state.CHOPPER_SWITCH:
                chopper_state = "hot" if switcher == 0 else "cold"
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

                self.stream_power.emit(
                    {
                        "x": [voltage_get * 1e3],
                        "y": [power],
                        "new_plot": i == 0,
                    }
                )

                if state.CHOPPER_SWITCH:
                    results[chopper_state]["voltage_set"].append(voltage_set)
                    results[chopper_state]["voltage_get"].append(voltage_get)
                    results[chopper_state]["current_get"].append(current_get)
                    results[chopper_state]["power"].append(power)
                    results[chopper_state]["time"].append(time_step)
                else:
                    results["voltage_set"].append(voltage_set)
                    results["voltage_get"].append(voltage_get)
                    results["current_get"].append(current_get)
                    results["power"].append(power)
                    results["time"].append(time_step)

                measure.data = results

            if state.CHOPPER_SWITCH:
                chopper_manager.chopper.path0()
                time.sleep(2)

        if state.CHOPPER_SWITCH:
            if len(results["hot"]["power"]) and len(results["cold"]["power"]):
                volt_diff, power_diff, tn = get_y_tn(
                    hot_power=results["hot"]["power"],
                    cold_power=results["cold"]["power"],
                    hot_voltage=results["hot"]["voltage_get"],
                    cold_voltage=results["cold"]["voltage_get"],
                )
                volt_diff_mv = [volt * 1e3 for volt in volt_diff]
                results["y_factor"] = power_diff
                results["t_noise"] = tn
                self.stream_y_factor.emit(
                    {
                        "x": volt_diff_mv,
                        "y": power_diff,
                    }
                )
                self.stream_tn.emit(
                    {
                        "x": volt_diff_mv,
                        "y": tn,
                    }
                )

        block.set_bias_voltage(initial_v)
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
        self.biasPowerGraphWindow = None
        self.powerStreamGraphDockWidget = None
        self.biasPowerDiffGraphWindow = None
        self.biasTnGraphWindow = None
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

        self.btnStartStreamNRX = Button("Start Stream", animate=True)
        self.btnStartStreamNRX.clicked.connect(self.start_stream_nrx)

        self.btnStopStreamNRX = Button("Stop Stream")
        self.btnStopStreamNRX.setEnabled(False)
        self.btnStopStreamNRX.clicked.connect(self.stop_stream_nrx)

        self.checkNRXStreamPlot = QCheckBox(self)
        self.checkNRXStreamPlot.setText("Plot stream time line")

        self.checkNRXStoreStream = QCheckBox(self)
        self.checkNRXStoreStream.setText("Store stream data")

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
        layout.addWidget(self.checkNRXStreamPlot, 3, 0)
        layout.addWidget(self.checkNRXStoreStream, 3, 1)
        layout.addWidget(self.nrxStreamWindowTimeLabel, 4, 0)
        layout.addWidget(self.nrxStreamWindowTime, 4, 1)
        self.groupNRX.setLayout(layout)

    def start_stream_nrx(self):
        self.nrx_stream_thread = NRXBlockStreamThread()

        state.NRX_STREAM_THREAD = True
        state.NRX_STREAM_PLOT_GRAPH = self.checkNRXStreamPlot.isChecked()
        state.NRX_STREAM_GRAPH_TIME = self.nrxStreamWindowTime.value()
        state.NRX_STREAM_STORE_DATA = self.checkNRXStoreStream.isChecked()

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
        if self.powerStreamGraphDockWidget is None:
            return
        self.powerStreamGraphDockWidget.widget().plotNew(x=x, y=y, reset_data=reset)
        self.powerStreamGraphDockWidget.widget().show()

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

        self.chopperSwitch = QCheckBox(self)
        self.chopperSwitch.setText("Enable chopper Hot/Cold switching")
        self.chopperSwitch.setChecked(state.CHOPPER_SWITCH)

        self.btnStartBiasPowerScan = Button("Start Scan", animate=True)
        self.btnStartBiasPowerScan.clicked.connect(self.start_measure_bias_power)

        self.btnStopBiasPowerScan = Button("Stop Scan")
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
        layout.addWidget(self.chopperSwitch, 5, 0)
        layout.addWidget(self.btnStartBiasPowerScan, 6, 0)
        layout.addWidget(self.btnStopBiasPowerScan, 6, 1)

        self.groupBiasPowerScan.setLayout(layout)

    def start_measure_bias_power(self):
        self.bias_power_thread = BiasPowerThread()

        state.BLOCK_BIAS_POWER_MEASURE_THREAD = True
        state.BLOCK_BIAS_VOLT_FROM = self.voltFrom.value()
        state.BLOCK_BIAS_VOLT_TO = self.voltTo.value()
        state.BLOCK_BIAS_VOLT_POINTS = int(self.voltPoints.value())
        state.BLOCK_BIAS_STEP_DELAY = self.voltStepDelay.value()
        state.CHOPPER_SWITCH = self.chopperSwitch.isChecked()

        self.bias_power_thread.stream_power.connect(self.show_bias_power_graph)
        if state.CHOPPER_SWITCH:
            self.bias_power_thread.stream_y_factor.connect(
                self.show_bias_power_diff_graph
            )
            self.bias_power_thread.stream_tn.connect(self.show_tn_graph)
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
            return
        self.biasPowerGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
        )
        self.biasPowerGraphWindow.widget().show()

    def show_bias_power_diff_graph(self, results):
        if self.biasPowerDiffGraphWindow is None:
            return
        self.biasPowerDiffGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
        )
        self.biasPowerDiffGraphWindow.widget().show()

    def show_tn_graph(self, results):
        if self.biasTnGraphWindow is None:
            return
        self.biasTnGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
        )
        self.biasTnGraphWindow.widget().show()
