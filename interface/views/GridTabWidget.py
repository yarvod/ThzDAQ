import logging
import time
from typing import Dict

import numpy as np
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QLabel,
    QFormLayout,
    QCheckBox,
    QProgressBar,
    QComboBox,
)

from api import SisBlock
from api.Arduino.grid import GridManager
from api.Chopper import chopper_manager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.grid.GridBiasCurrentAngleScan import GridBiasCurrentScan
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.grid.GridManagingGroup import GridManagingGroup
from interface.components.ui.Lines import HLine
from store import ScontelSisBlockManager
from store.base import MeasureModel, MeasureType
from store.state import state
from threads import Thread
from utils.dock import Dock
from utils.exceptions import DeviceConnectionError
from utils.functions import get_voltage_tn

logger = logging.getLogger(__name__)


class StepBiasPowerThread(Thread):
    stream_pv = pyqtSignal(dict)
    stream_y_factor = pyqtSignal(dict)
    stream_iv = pyqtSignal(dict)
    stream_tn = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(
        self,
        angle_start: float,
        angle_stop: float,
        angle_step: float,
        sis_cid: int,
        voltage_start: float,
        voltage_stop: float,
        voltage_points: int,
        voltage_step_delay: float,
        chopper_switch: bool,
    ):
        super().__init__()
        self.angle_start = angle_start
        self.angle_stop = angle_stop
        self.ange_step = angle_step
        self.config_sis = ScontelSisBlockManager.get_config(sis_cid)
        self.block = None
        self.voltage_start = voltage_start
        self.voltage_stop = voltage_stop
        self.voltage_points = voltage_points
        self.voltage_step_delay = voltage_step_delay
        self.chopper_switch = chopper_switch
        self.initial_v = 0
        self.initial_angle = float(state.GRID_ANGLE.val)

        if self.chopper_switch:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureType.GRID_PV_CURVE_HOT_COLD, data={}
            )
        else:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureType.GRID_PV_CURVE, data={}
            )
        self.measure.save(finish=False)

        self.motor = GridManager(host=state.GRID_ADDRESS)

        self.nrx = NRXPowerMeter(
            host=state.NRX_IP,
            aperture_time=state.NRX_APER_TIME,
            delay=0,
        )

    def get_results_format(self) -> Dict:
        if self.chopper_switch:
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
        try:
            self.block = SisBlock(**self.config_sis.dict())
        except DeviceConnectionError:
            self.measure.save(finish=True)
            self.finished.emit()
            return

        angle_range = np.arange(
            self.angle_start,
            self.angle_stop + self.ange_step,
            self.ange_step,
        )
        volt_range = np.linspace(
            self.voltage_start * 1e-3,
            self.voltage_stop * 1e-3,
            self.voltage_points,
        )
        chopper_range = range(2) if self.chopper_switch else range(1)
        total_steps = len(chopper_range) * len(angle_range) * len(volt_range)
        self.initial_v = self.block.get_bias_voltage()
        initial_time = time.time()
        if self.chopper_switch:
            # chopper_manager.chopper.align()
            chopper_manager.chopper.align_to_hot()
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
                    if self.chopper_switch:
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

                if self.chopper_switch:
                    chopper_manager.chopper.path0()
                    time.sleep(2)

            if self.chopper_switch:
                if len(results["hot"]["power"]) and len(results["cold"]["power"]):
                    volt_diff, power_diff, tn = get_voltage_tn(
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
        if self.chopper_switch:
            chopper_manager.chopper.align_to_cold()
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


class GridTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self.gridBiasPowerGraphWindow = None
        self.gridBiasCurrentGraphWindow = None
        self.gridBiasPowerDiffGraphWindow = None
        self.biasTnGraphWindow = None
        self.createGroupGridBiasPowerScan()
        self.gridAngleCurrentScan = GridBiasCurrentScan(self)
        self._layout.addWidget(GridManagingGroup(self))
        self._layout.addSpacing(10)
        self._layout.addWidget(self.groupGridBiasPowerScan)
        self._layout.addSpacing(10)
        self._layout.addWidget(self.gridAngleCurrentScan)
        self._layout.addStretch()

        self.setLayout(self._layout)

    def createGroupGridBiasPowerScan(self):
        self.groupGridBiasPowerScan = QGroupBox("Grid Power Bias Scan")
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

        self.sisConfigLabel = QLabel(self)
        self.sisConfigLabel.setText("SIS block device")
        self.sisConfig = QComboBox(self)
        ScontelSisBlockManager.event_manager.configs_updated.connect(
            self.update_sis_config
        )

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
        layout.addRow(self.sisConfigLabel, self.sisConfig)
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

        self.bias_power_thread = StepBiasPowerThread(
            angle_start=self.angleStart.value(),
            angle_stop=self.angleStop.value(),
            angle_step=self.angleStep.value(),
            sis_cid=ScontelSisBlockManager.configs[self.sisConfig.currentIndex()].cid,
            voltage_start=self.voltFrom.value(),
            voltage_stop=self.voltTo.value(),
            voltage_points=int(self.voltPoints.value()),
            voltage_step_delay=self.voltStepDelay.value(),
            chopper_switch=self.chopperSwitch.isChecked(),
        )

        self.gridBiasPowerGraphWindow = Dock.ex.dock_manager.findDockWidget("P-V curve")
        self.gridBiasCurrentGraphWindow = Dock.ex.dock_manager.findDockWidget(
            "I-V curve"
        )
        self.gridBiasPowerDiffGraphWindow = Dock.ex.dock_manager.findDockWidget(
            "Y-V curve"
        )
        self.biasTnGraphWindow = Dock.ex.dock_manager.findDockWidget("Tn-V curve")

        self.bias_power_thread.stream_pv.connect(self.show_bias_power_graph)
        self.bias_power_thread.stream_iv.connect(self.show_bias_current_graph)
        if self.chopperSwitch.isChecked():
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

    def update_sis_config(self):
        names = ScontelSisBlockManager.configs.list_of_names()
        for i in range(self.sisConfig.count()):
            self.sisConfig.removeItem(i)
        if len(names):
            self.sisConfig.insertItems(0, names)
