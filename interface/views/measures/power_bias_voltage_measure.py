import logging
import time
from typing import Dict

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtGui import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
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
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.ui.Lines import HLine
from store import ScontelSisBlockManager
from store.base import MeasureModel, MeasureType
from store.state import state
from threads import Thread
from utils.dock import Dock
from utils.exceptions import DeviceConnectionError
from utils.functions import get_voltage_tn

logger = logging.getLogger(__name__)


class PowerBiasVoltageThread(Thread):
    stream_pv = Signal(dict)
    stream_y_factor = Signal(dict)
    stream_iv = Signal(dict)
    stream_tn = Signal(dict)
    progress = Signal(int)

    def __init__(
        self,
        use_grid: bool,
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
        self.use_grid = use_grid
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

        self.measure = MeasureModel.objects.create(
            measure_type=self.get_measure_type(), data={}
        )
        self.measure.save(False)

        self.motor = GridManager(host=state.GRID_ADDRESS)

        self.nrx = NRXPowerMeter(
            host=state.NRX_IP,
            aperture_time=state.NRX_APER_TIME,
            delay=0,
        )

    def get_measure_type(self):
        if self.use_grid:
            if self.chopper_switch:
                return MeasureType.GRID_PV_CURVE_HOT_COLD
            else:
                return MeasureType.GRID_PV_CURVE

        if self.chopper_switch:
            return MeasureType.PV_CURVE_HOT_COLD

        return MeasureType.PV_CURVE

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
            if not state.POWER_BIAS_VOLTAGE_MEASURE_THREAD:
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
                    if not state.POWER_BIAS_VOLTAGE_MEASURE_THREAD:
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
        state.POWER_BIAS_VOLTAGE_MEASURE_THREAD = False


class PowerBiasVoltageMeasureWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.gridBiasPowerGraphWindow = None
        self.gridBiasCurrentGraphWindow = None
        self.gridBiasPowerDiffGraphWindow = None
        self.biasTnGraphWindow = None
        self.power_bias_thread = None

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.useGrid = QCheckBox("Use GRID", self)
        self.useGrid.checkStateChanged.connect(self.use_grid)
        self.useGrid.setChecked(False)

        self.angleStartLabel = QLabel("Angle start, degree", self)
        self.angleStartLabel.setHidden(~self.useGrid.isChecked())
        self.angleStart = DoubleSpinBox(self)
        self.angleStart.setRange(-720, 720)
        self.angleStart.setValue(state.GRID_ANGLE_START)
        self.angleStart.setHidden(~self.useGrid.isChecked())

        self.angleStopLabel = QLabel("Angle stop, degree", self)
        self.angleStopLabel.setHidden(~self.useGrid.isChecked())
        self.angleStop = DoubleSpinBox(self)
        self.angleStop.setRange(-720, 720)
        self.angleStop.setValue(state.GRID_ANGLE_STOP)
        self.angleStop.setHidden(~self.useGrid.isChecked())

        self.angleStepLabel = QLabel("Angle step, degree", self)
        self.angleStepLabel.setHidden(~self.useGrid.isChecked())
        self.angleStep = DoubleSpinBox(self)
        self.angleStep.setRange(-180, 180)
        self.angleStep.setValue(state.GRID_ANGLE_STEP)
        self.angleStep.setHidden(~self.useGrid.isChecked())

        self.useChopperSwitch = QCheckBox(self)
        self.useChopperSwitch.setText("Use chopper Hot/Cold switching")
        self.useChopperSwitch.setChecked(state.CHOPPER_SWITCH)

        self.sisConfigLabel = QLabel(self)
        self.sisConfigLabel.setText("SIS block device")
        self.sisConfig = QComboBox(self)
        ScontelSisBlockManager.event_manager.configs_updated.connect(
            lambda: ScontelSisBlockManager.update_sis_config(self)
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
        self.voltStepDelay.setRange(
            state.BLOCK_BIAS_STEP_DELAY_MIN, state.BLOCK_BIAS_STEP_DELAY_MAX
        )
        self.voltStepDelay.setValue(state.BLOCK_BIAS_STEP_DELAY)

        self.progress = QProgressBar(self)
        self.progress.setValue(0)

        self.btnStartBiasPowerScan = Button("Start Scan", animate=True)
        self.btnStartBiasPowerScan.clicked.connect(self.start_measure_step_bias_power)

        self.btnStopBiasPowerScan = Button("Stop Scan")
        self.btnStopBiasPowerScan.clicked.connect(self.stop_measure_step_bias_power)
        self.btnStopBiasPowerScan.setEnabled(False)

        form_layout.addRow(self.useGrid)
        form_layout.addRow(self.angleStartLabel, self.angleStart)
        form_layout.addRow(self.angleStopLabel, self.angleStop)
        form_layout.addRow(self.angleStepLabel, self.angleStep)
        form_layout.addRow(HLine(self))
        form_layout.addRow(self.useChopperSwitch)
        form_layout.addRow(HLine(self))
        form_layout.addRow(self.sisConfigLabel, self.sisConfig)
        form_layout.addRow(self.voltFromLabel, self.voltFrom)
        form_layout.addRow(self.voltToLabel, self.voltTo)
        form_layout.addRow(self.voltPointsLabel, self.voltPoints)
        form_layout.addRow(self.voltStepDelayLabel, self.voltStepDelay)
        form_layout.addRow(HLine(self))
        form_layout.addRow(self.progress)
        form_layout.addRow(self.btnStartBiasPowerScan)
        form_layout.addRow(self.btnStopBiasPowerScan)

        layout.addLayout(form_layout)
        layout.addStretch()

        self.setLayout(layout)

    def use_grid(self, check_state: Qt.CheckState):
        if check_state == Qt.CheckState.Checked:
            self.angleStartLabel.setHidden(False)
            self.angleStart.setHidden(False)
            self.angleStopLabel.setHidden(False)
            self.angleStop.setHidden(False)
            self.angleStepLabel.setHidden(False)
            self.angleStep.setHidden(False)
            return

        self.angleStartLabel.setHidden(True)
        self.angleStart.setHidden(True)
        self.angleStopLabel.setHidden(True)
        self.angleStop.setHidden(True)
        self.angleStepLabel.setHidden(True)
        self.angleStep.setHidden(True)

    def start_measure_step_bias_power(self):
        state.POWER_BIAS_VOLTAGE_MEASURE_THREAD = True

        self.power_bias_thread = PowerBiasVoltageThread(
            use_grid=self.useGrid.isChecked(),
            angle_start=self.angleStart.value(),
            angle_stop=self.angleStop.value(),
            angle_step=self.angleStep.value(),
            sis_cid=ScontelSisBlockManager.configs[self.sisConfig.currentIndex()].cid,
            voltage_start=self.voltFrom.value(),
            voltage_stop=self.voltTo.value(),
            voltage_points=int(self.voltPoints.value()),
            voltage_step_delay=self.voltStepDelay.value(),
            chopper_switch=self.useChopperSwitch.isChecked(),
        )

        self.gridBiasPowerGraphWindow = Dock.ex.dock_manager.findDockWidget("P-V curve")
        self.gridBiasCurrentGraphWindow = Dock.ex.dock_manager.findDockWidget(
            "I-V curve"
        )
        self.gridBiasPowerDiffGraphWindow = Dock.ex.dock_manager.findDockWidget(
            "Y-V curve"
        )
        self.biasTnGraphWindow = Dock.ex.dock_manager.findDockWidget("Tn-V curve")

        self.power_bias_thread.stream_pv.connect(self.show_bias_power_graph)
        self.power_bias_thread.stream_iv.connect(self.show_bias_current_graph)
        if self.useChopperSwitch.isChecked():
            self.power_bias_thread.stream_y_factor.connect(
                self.show_bias_power_diff_graph
            )
            self.power_bias_thread.stream_tn.connect(self.show_tn_graph)

        self.power_bias_thread.progress.connect(lambda x: self.progress.setValue(x))
        self.power_bias_thread.finished.connect(lambda: self.progress.setValue(0))
        self.power_bias_thread.start()

        self.btnStartBiasPowerScan.setEnabled(False)
        self.power_bias_thread.finished.connect(
            lambda: self.btnStartBiasPowerScan.setEnabled(True)
        )

        self.btnStopBiasPowerScan.setEnabled(True)
        self.power_bias_thread.finished.connect(
            lambda: self.btnStopBiasPowerScan.setEnabled(False)
        )

    def stop_measure_step_bias_power(self):
        state.POWER_BIAS_VOLTAGE_MEASURE_THREAD = False

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
