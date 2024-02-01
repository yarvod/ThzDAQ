import logging
import time
from typing import Dict

import numpy as np
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QGroupBox,
    QLabel,
    QFormLayout,
    QScrollArea,
    QCheckBox,
    QProgressBar,
)

from api.Arduino.grid import GridManager
from api.Chopper import chopper_manager
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.grid.GridBiasCurrentAngleScan import GridBiasCurrentScan
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.grid.GridManagingGroup import GridManagingGroup
from interface.components.ui.Lines import HLine
from store.base import MeasureModel, MeasureType
from store.state import state
from threads import Thread
from utils.functions import get_y_tn

logger = logging.getLogger(__name__)


class StepBiasPowerThread(Thread):
    stream_pv = pyqtSignal(dict)
    stream_y_factor = pyqtSignal(dict)
    stream_iv = pyqtSignal(dict)
    stream_tn = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.initial_v = 0
        self.initial_angle = float(state.GRID_ANGLE.val)

        if state.CHOPPER_SWITCH:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureType.GRID_CHOPPER_BIAS_POWER, data={}
            )
        else:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureType.GRID_BIAS_POWER, data={}
            )
        self.measure.save(finish=False)

        self.motor = GridManager(host=state.GRID_ADDRESS)

        self.block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        self.block.connect()

        self.nrx = NRXPowerMeter(
            host=state.NRX_IP,
            aperture_time=state.NRX_APER_TIME,
            delay=0,
        )

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
                "y_factor": [],
                "t_noise": [],
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
                    power = self.nrx.get_power()
                    time_step = time.time() - initial_time

                    step = (
                        (angle_step * len(chopper_range) + chopper_step)
                        * len(volt_range)
                        + voltage_step
                        + 1
                    )
                    progress = int(step / total_steps * 100)
                    self.progress.emit(progress)

                    self.stream_pv.emit(
                        {
                            "x": [voltage_get * 1e3],
                            "y": [power],
                            "new_plot": voltage_step == 0,
                            "measure_id": self.measure.id,
                            "legend_postfix": f"angle {angle} °",
                        }
                    )
                    self.stream_iv.emit(
                        {
                            "x": [voltage_get * 1e3],
                            "y": [current_get * 1e6],
                            "new_plot": voltage_step == 0,
                            "measure_id": self.measure.id,
                            "legend_postfix": f"angle {angle} °",
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
                            "measure_id": self.measure.id,
                            "legend_postfix": f"angle {angle} °",
                        }
                    )
                    self.stream_tn.emit(
                        {
                            "x": volt_diff_mv,
                            "y": tn,
                            "measure_id": self.measure.id,
                            "legend_postfix": f"angle {angle} °",
                        }
                    )

        self.pre_exit()
        self.finished.emit()

    def pre_exit(self):
        self.motor.rotate(self.initial_angle, finish=True)
        logger.info(
            f"[{self.__class__.__name__}.pre_exit] Setting SIS block initial voltage ..."
        )
        self.block.set_bias_voltage(self.initial_v)
        logger.info(
            f"[{self.__class__.__name__}.pre_exit] Finish setting SIS block initial voltage"
        )
        self.measure.save()
        self.block.disconnect()
        self.nrx.adapter.close()
        self.progress.emit(0)
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False


class GridTabWidget(QScrollArea):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.widget = QWidget()
        self.layout = QVBoxLayout(self)
        self.gridBiasPowerGraphWindow = None
        self.gridBiasCurrentGraphWindow = None
        self.gridBiasPowerDiffGraphWindow = None
        self.biasTnGraphWindow = None
        self.createGroupGridBiasPowerScan()
        self.gridAngleCurrentScan = GridBiasCurrentScan(self)
        self.layout.addWidget(GridManagingGroup(self))
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupGridBiasPowerScan)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.gridAngleCurrentScan)
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
        state.CHOPPER_SWITCH = self.chopperSwitch.isChecked()

        self.bias_power_thread = StepBiasPowerThread()

        self.bias_power_thread.stream_pv.connect(self.show_bias_power_graph)
        self.bias_power_thread.stream_iv.connect(self.show_bias_current_graph)
        if state.CHOPPER_SWITCH:
            self.bias_power_thread.stream_y_factor.connect(
                self.show_bias_power_diff_graph
            )
            self.bias_power_thread.stream_tn.connect(self.show_tn_graph)

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
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False

    def show_bias_power_graph(self, results):
        if self.gridBiasPowerGraphWindow is None:
            return
        self.gridBiasPowerGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
            measure_id=results.get("measure_id"),
            legend_postfix=results.get("legend_postfix"),
        )
        self.gridBiasPowerGraphWindow.widget().show()

    def show_bias_current_graph(self, results):
        if self.gridBiasCurrentGraphWindow is None:
            return
        self.gridBiasCurrentGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
            measure_id=results.get("measure_id"),
            legend_postfix=results.get("legend_postfix"),
        )
        self.gridBiasCurrentGraphWindow.widget().show()

    def show_bias_power_diff_graph(self, results):
        if self.gridBiasPowerDiffGraphWindow is None:
            return
        self.gridBiasPowerDiffGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            measure_id=results.get("measure_id"),
            legend_postfix=results.get("legend_postfix"),
        )
        self.gridBiasPowerDiffGraphWindow.widget().show()

    def show_tn_graph(self, results):
        if self.biasTnGraphWindow is None:
            return
        self.biasTnGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            measure_id=results.get("measure_id"),
            legend_postfix=results.get("legend_postfix"),
        )
        self.biasTnGraphWindow.widget().show()
