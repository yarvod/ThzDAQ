import logging
import time
from typing import Dict

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QGroupBox,
    QLabel,
    QComboBox,
    QFormLayout,
    QScrollArea,
    QCheckBox,
    QProgressBar,
)

from api.Arduino.grid import GridManager
from api.Chopper import chopper_manager
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.grid.GridManagingGroup import GridManagingGroup
from interface.components.ui.Lines import HLine
from interface.windows.biasPowerGraphWindow import (
    GridBiasPowerGraphWindow,
    GridBiasGraphWindow,
    GridBiasPowerDiffGraphWindow,
)
from settings import GridPlotTypes
from store.base import MeasureModel, MeasureType
from store.state import state


logger = logging.getLogger(__name__)


class StepBiasPowerThread(QThread):
    results = pyqtSignal(list)
    stream_results = pyqtSignal(dict)
    stream_diff_results = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.initial_v = 0
        self.initial_angle = state.GRID_ANGLE

        if state.CHOPPER_SWITCH:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureType.GRID_CHOPPER_BIAS_POWER, data={}
            )
        else:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureType.GRID_BIAS_POWER, data={}
            )

        self.motor = GridManager(host=state.GRID_ADDRESS)

        self.block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        self.block.connect()

    def get_results_format(self) -> Dict:
        if state.CHOPPER_SWITCH:
            return {
                "id": 0,
                "step": state.GRID_ANGLE_STEP,
                "angle": 0,
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
            }
        return {
            "id": 0,
            "step": state.GRID_ANGLE_STEP,
            "angle": 0,
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

        results_list = []
        angle_range = np.arange(
            state.GRID_ANGLE_START,
            state.GRID_ANGLE_STOP + state.GRID_ANGLE_STEP,
            state.GRID_ANGLE_STEP,
        )
        volt_range = np.linspace(
            state.BLOCK_BIAS_VOLT_FROM * 1e-3,
            state.BLOCK_BIAS_VOLT_TO * 1e-3,
            state.BLOCK_BIAS_VOLT_POINTS,
        )
        chopper_range = range(2) if state.CHOPPER_SWITCH else range(1)
        total_steps = len(chopper_range) * len(angle_range) * len(volt_range)
        self.initial_v = self.block.get_bias_voltage()
        initial_time = time.time()
        if state.CHOPPER_SWITCH:
            chopper_manager.chopper.align()
        self.motor.rotate(state.GRID_ANGLE_START)
        time.sleep(abs(state.GRID_ANGLE_START) / state.GRID_SPEED)
        for angle_step, angle in enumerate(angle_range):
            if not state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD:
                break

            results = self.get_results_format()
            results["id"] = angle_step
            results["angle"] = angle

            if angle_step != 0:
                self.motor.rotate(angle)
            time.sleep(abs(state.GRID_ANGLE_STEP) / state.GRID_SPEED)
            for chopper_step in chopper_range:
                chopper_state = None
                if state.CHOPPER_SWITCH:
                    chopper_state = "hot" if chopper_step == 0 else "cold"
                for voltage_step, voltage_set in enumerate(volt_range):
                    if not state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD:
                        break

                    self.block.set_bias_voltage(voltage_set)
                    if voltage_step == 0:  # self.block need time to set first point
                        time.sleep(0.5)
                    time.sleep(state.BLOCK_BIAS_STEP_DELAY)
                    voltage_get = self.block.get_bias_voltage()
                    if not voltage_get:
                        continue
                    current_get = self.block.get_bias_current()
                    if not current_get:
                        continue
                    power = nrx.get_power()
                    time_step = time.time() - initial_time

                    step = (
                        (angle_step * len(chopper_range) + chopper_step)
                        * len(volt_range)
                        + voltage_step
                        + 1
                    )
                    progress = int(step / total_steps * 100)
                    self.progress.emit(progress)

                    self.stream_results.emit(
                        {
                            "x": [voltage_get * 1e3],
                            "y": [power]
                            if state.GRID_PLOT_TYPE == GridPlotTypes.PV_CURVE
                            else [current_get * 1e6],
                            "new_plot": voltage_step == 0,
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

                    self.measure.data[angle_step] = results

                if state.CHOPPER_SWITCH:
                    chopper_manager.chopper.path0()
                    time.sleep(2)

            if state.CHOPPER_SWITCH:
                hot = np.array(results["hot"]["power"])
                cold = np.array(results["cold"]["power"])
                if not len(hot) or not len(cold):
                    continue
                min_ind = min([len(cold), len(hot)])
                power_diff = hot[:min_ind] - cold[:min_ind]
                self.stream_diff_results.emit(
                    {
                        "x": [volt * 1e3 for volt in results["hot"]["voltage_get"]],
                        "y": power_diff.tolist(),
                    }
                )

        self.pre_exit()
        self.results.emit(results_list)
        self.finished.emit()

    def pre_exit(self):
        self.motor.rotate(self.initial_angle, finish=True)
        self.block.set_bias_voltage(self.initial_v)
        self.measure.save()
        self.progress.emit(0)
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False

    def terminate(self) -> None:
        self.pre_exit()
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")

    def quit(self) -> None:
        self.pre_exit()
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")

    def exit(self, returnCode: int = ...):
        self.pre_exit()
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")


class GridTabWidget(QScrollArea):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.widget = QWidget()
        self.layout = QVBoxLayout(self)
        self.gridBiasPowerGraphWindow = None
        self.gridBiasGraphWindow = None
        self.gridBiasPowerDiffGraphWindow = None
        self.createGroupGridBiasPowerScan()
        self.layout.addWidget(GridManagingGroup(self))
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupGridBiasPowerScan)
        self.layout.addStretch()

        self.widget.setLayout(self.layout)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setWidget(self.widget)

    def createGroupGridBiasPowerScan(self):
        self.groupGridBiasPowerScan = QGroupBox("Grid Power Bias Scan")
        self.groupGridBiasPowerScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QFormLayout()

        self.angleStartLabel = QLabel(self)
        self.angleStartLabel.setText("Angle start, degree")
        self.angleStart = DoubleSpinBox(self)
        self.angleStart.setRange(-720, 720)
        self.angleStart.setValue(state.GRID_ANGLE_START)

        self.angleStopLabel = QLabel(self)
        self.angleStopLabel.setText("Angle stop, degree")
        self.angleStop = DoubleSpinBox(self)
        self.angleStop.setRange(-720, 720)
        self.angleStop.setValue(state.GRID_ANGLE_STOP)

        self.angleStepLabel = QLabel(self)
        self.angleStepLabel.setText("Angle step, degree")
        self.angleStep = DoubleSpinBox(self)
        self.angleStep.setRange(-180, 180)
        self.angleStep.setValue(state.GRID_ANGLE_STEP)

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
        self.voltPointsLabel.setText("Bias voltage points")
        self.voltPoints = DoubleSpinBox(self)
        self.voltPoints.setMaximum(state.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(state.BLOCK_BIAS_VOLT_POINTS)

        self.voltStepDelayLabel = QLabel(self)
        self.voltStepDelayLabel.setText("Bias step delay, s")
        self.voltStepDelay = DoubleSpinBox(self)
        self.voltStepDelay.setRange(0.01, 10)
        self.voltStepDelay.setValue(state.BLOCK_BIAS_STEP_DELAY)

        self.gridPlotTypeLabel = QLabel(self)
        self.gridPlotTypeLabel.setText("Plot type")
        self.gridPlotType = QComboBox(self)
        self.gridPlotType.addItems(GridPlotTypes.CHOICES)

        self.chopperSwitch = QCheckBox(self)
        self.chopperSwitch.setText("Enable chopper Hot/Cold switching")
        self.chopperSwitch.setChecked(state.CHOPPER_SWITCH)

        self.progress = QProgressBar(self)
        self.progress.setValue(0)

        self.btnStartBiasPowerScan = Button("Start Scan", animate=True)
        self.btnStartBiasPowerScan.clicked.connect(self.start_measure_step_bias_power)

        self.btnStopBiasPowerScan = Button("Stop Scan")
        self.btnStopBiasPowerScan.clicked.connect(self.stop_measure_step_bias_power)
        self.btnStopBiasPowerScan.setEnabled(False)

        layout.addRow(self.angleStartLabel, self.angleStart)
        layout.addRow(self.angleStopLabel, self.angleStop)
        layout.addRow(self.angleStepLabel, self.angleStep)
        layout.addRow(HLine(self))
        layout.addRow(self.voltFromLabel, self.voltFrom)
        layout.addRow(self.voltToLabel, self.voltTo)
        layout.addRow(self.voltPointsLabel, self.voltPoints)
        layout.addRow(self.voltStepDelayLabel, self.voltStepDelay)
        layout.addRow(HLine(self))
        layout.addRow(self.gridPlotTypeLabel, self.gridPlotType)
        layout.addRow(self.chopperSwitch)
        layout.addRow(self.progress)
        layout.addRow(self.btnStartBiasPowerScan)
        layout.addRow(self.btnStopBiasPowerScan)

        self.groupGridBiasPowerScan.setLayout(layout)

    def start_measure_step_bias_power(self):
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = True
        state.GRID_ANGLE_START = self.angleStart.value()
        state.GRID_ANGLE_STOP = self.angleStop.value()
        state.GRID_ANGLE_STEP = self.angleStep.value()
        state.BLOCK_BIAS_VOLT_FROM = self.voltFrom.value()
        state.BLOCK_BIAS_VOLT_TO = self.voltTo.value()
        state.BLOCK_BIAS_VOLT_POINTS = int(self.voltPoints.value())
        state.BLOCK_BIAS_STEP_DELAY = self.voltStepDelay.value()
        state.GRID_PLOT_TYPE = self.gridPlotType.currentIndex()
        state.CHOPPER_SWITCH = self.chopperSwitch.isChecked()

        self.bias_power_thread = StepBiasPowerThread()

        self.bias_power_thread.stream_results.connect(self.show_bias_power_graph)
        if state.CHOPPER_SWITCH:
            self.bias_power_thread.stream_diff_results.connect(
                self.show_bias_power_diff_graph
            )

        self.bias_power_thread.progress.connect(lambda x: self.progress.setValue(x))
        self.bias_power_thread.finished.connect(lambda: self.progress.setValue(0))
        self.bias_power_thread.start()

        self.btnStartBiasPowerScan.setEnabled(False)
        self.bias_power_thread.finished.connect(
            lambda: self.btnStartBiasPowerScan.setEnabled(True)
        )

        self.btnStopBiasPowerScan.setEnabled(True)
        self.bias_power_thread.finished.connect(
            lambda: self.btnStopBiasPowerScan.setEnabled(False)
        )

    def stop_measure_step_bias_power(self):
        self.bias_power_thread.terminate()

    def show_bias_power_graph(self, results):
        if state.GRID_PLOT_TYPE == GridPlotTypes.IV_CURVE:
            if self.gridBiasGraphWindow is None:
                self.gridBiasGraphWindow = GridBiasGraphWindow()
            self.gridBiasGraphWindow.plotNew(
                x=results.get("x", []),
                y=results.get("y", []),
                new_plot=results.get("new_plot", True),
            )
            self.gridBiasGraphWindow.show()

        if state.GRID_PLOT_TYPE == GridPlotTypes.PV_CURVE:
            if self.gridBiasPowerGraphWindow is None:
                self.gridBiasPowerGraphWindow = GridBiasPowerGraphWindow()
            self.gridBiasPowerGraphWindow.plotNew(
                x=results.get("x", []),
                y=results.get("y", []),
                new_plot=results.get("new_plot", True),
            )
            self.gridBiasPowerGraphWindow.show()

    def show_bias_power_diff_graph(self, results):
        if self.gridBiasPowerDiffGraphWindow is None:
            self.gridBiasPowerDiffGraphWindow = GridBiasPowerDiffGraphWindow()
        self.gridBiasPowerDiffGraphWindow.plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
        )
        self.gridBiasPowerDiffGraphWindow.show()
