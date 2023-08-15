import json
import logging
import time

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QGroupBox,
    QLabel,
    QPushButton,
    QGridLayout,
    QFileDialog,
)

from api.Arduino.step_motor import StepMotorManager
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components import CustomQDoubleSpinBox
from interface.windows.biasPowerGraphWindow import StepBiasPowerGraphWindow
from state import state


logger = logging.getLogger(__name__)


class StepBiasPowerThread(QThread):
    results = pyqtSignal(list)
    stream_results = pyqtSignal(dict)

    def run(self):
        motor = StepMotorManager(address=state.STEP_MOTOR_ADDRESS)
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
        results_list = []
        angle_range = np.arange(
            state.STEP_MOTOR_ANGLE_FROM,
            state.STEP_MOTOR_ANGLE_TO + state.STEP_MOTOR_ANGLE_STEP,
            state.STEP_MOTOR_ANGLE_STEP,
        )
        volt_range = np.linspace(
            state.BLOCK_BIAS_VOLT_FROM * 1e-3,
            state.BLOCK_BIAS_VOLT_TO * 1e-3,
            state.BLOCK_BIAS_VOLT_POINTS,
        )
        initial_v = block.get_bias_voltage()
        initial_time = time.time()
        motor.rotate(state.STEP_MOTOR_ANGLE_FROM)
        time.sleep(abs(state.STEP_MOTOR_ANGLE_FROM) / state.STEP_MOTOR_SPEED)
        for ind, angle in enumerate(angle_range):
            if not state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD:
                break

            results = {
                "id": ind,
                "step": state.STEP_MOTOR_ANGLE_STEP,
                "angle": angle,
                "current_get": [],
                "voltage_set": [],
                "voltage_get": [],
                "power": [],
                "time": [],
            }
            if ind != 0:
                motor.rotate(state.STEP_MOTOR_ANGLE_STEP)
            time.sleep(abs(state.STEP_MOTOR_ANGLE_STEP) / state.STEP_MOTOR_SPEED)

            for i, voltage_set in enumerate(volt_range):
                if not state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD:
                    break

                block.set_bias_voltage(voltage_set)
                if i == 0:  # block ned time to set first point
                    time.sleep(0.5)
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

                if i == 0:
                    results_list.append(results)
                else:
                    results_list[ind] = results

        block.set_bias_voltage(initial_v)
        self.results.emit(results_list)
        self.finished.emit()

    def terminate(self) -> None:
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False

    def quit(self) -> None:
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False


class StepMotorTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.stepBiasPowerGraphWindow = None
        self.createGroupStepMotor()
        self.createGroupStepBiasPowerScan()
        self.layout.addWidget(self.groupStepMotor)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupStepBiasPowerScan)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupStepMotor(self):
        self.groupStepMotor = QGroupBox("Step Motor")
        layout = QGridLayout()

        self.angleLabel = QLabel(self)
        self.angleLabel.setText("Angle, degree")
        self.angle = CustomQDoubleSpinBox(self)
        self.angle.setRange(-720, 720)
        self.angle.setValue(90)
        self.btnRotate = QPushButton("Rotate")
        self.btnRotate.clicked.connect(self.rotate)

        layout.addWidget(self.angleLabel, 1, 0)
        layout.addWidget(self.angle, 1, 1)
        layout.addWidget(self.btnRotate, 1, 2)

        self.groupStepMotor.setLayout(layout)

    def createGroupStepBiasPowerScan(self):
        self.groupStepBiasPowerScan = QGroupBox("Step Power Bias Scan")
        self.groupStepBiasPowerScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.angleStartLabel = QLabel(self)
        self.angleStartLabel.setText("Angle start, degree")
        self.angleStart = CustomQDoubleSpinBox(self)
        self.angleStart.setRange(-180, 180)
        self.angleStart.setValue(state.STEP_MOTOR_ANGLE_FROM)

        self.angleStopLabel = QLabel(self)
        self.angleStopLabel.setText("Angle stop, degree")
        self.angleStop = CustomQDoubleSpinBox(self)
        self.angleStop.setRange(-180, 180)
        self.angleStop.setValue(state.STEP_MOTOR_ANGLE_TO)

        self.angleStepLabel = QLabel(self)
        self.angleStepLabel.setText("Angle step, degree")
        self.angleStep = CustomQDoubleSpinBox(self)
        self.angleStep.setRange(-180, 180)
        self.angleStep.setValue(state.STEP_MOTOR_ANGLE_STEP)

        self.voltFromLabel = QLabel(self)
        self.voltFromLabel.setText("Bias voltage from, mV")
        self.voltFrom = CustomQDoubleSpinBox(self)
        self.voltFrom.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltToLabel = QLabel(self)
        self.voltToLabel.setText("Bias voltage to, mV")
        self.voltTo = CustomQDoubleSpinBox(self)
        self.voltTo.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltPointsLabel = QLabel(self)
        self.voltPointsLabel.setText("Bias voltage points")
        self.voltPoints = CustomQDoubleSpinBox(self)
        self.voltPoints.setMaximum(state.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(state.BLOCK_BIAS_VOLT_POINTS)

        self.voltStepDelayLabel = QLabel(self)
        self.voltStepDelayLabel.setText("Step delay, s")
        self.voltStepDelay = CustomQDoubleSpinBox(self)
        self.voltStepDelay.setRange(0.01, 10)
        self.voltStepDelay.setValue(state.BLOCK_BIAS_STEP_DELAY)

        self.btnStartBiasPowerScan = QPushButton("Start Scan")
        self.btnStartBiasPowerScan.clicked.connect(self.start_measure_step_bias_power)

        self.btnStopBiasPowerScan = QPushButton("Stop Scan")
        self.btnStopBiasPowerScan.clicked.connect(self.stop_measure_step_bias_power)
        self.btnStopBiasPowerScan.setEnabled(False)

        layout.addWidget(self.angleStartLabel, 1, 0)
        layout.addWidget(self.angleStart, 1, 1)
        layout.addWidget(self.angleStopLabel, 2, 0)
        layout.addWidget(self.angleStop, 2, 1)
        layout.addWidget(self.angleStepLabel, 3, 0)
        layout.addWidget(self.angleStep, 3, 1)
        layout.addWidget(self.voltFromLabel, 4, 0)
        layout.addWidget(self.voltFrom, 4, 1)
        layout.addWidget(self.voltToLabel, 5, 0)
        layout.addWidget(self.voltTo, 5, 1)
        layout.addWidget(self.voltPointsLabel, 6, 0)
        layout.addWidget(self.voltPoints, 6, 1)
        layout.addWidget(self.voltStepDelayLabel, 7, 0)
        layout.addWidget(self.voltStepDelay, 7, 1)
        layout.addWidget(self.btnStartBiasPowerScan, 8, 0)
        layout.addWidget(self.btnStopBiasPowerScan, 8, 1)

        self.groupStepBiasPowerScan.setLayout(layout)

    def start_measure_step_bias_power(self):
        self.bias_power_thread = StepBiasPowerThread()

        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = True
        state.STEP_MOTOR_ANGLE_FROM = self.angleStart.value()
        state.STEP_MOTOR_ANGLE_TO = self.angleStop.value()
        state.STEP_MOTOR_ANGLE_STEP = self.angleStep.value()
        state.BLOCK_BIAS_VOLT_FROM = self.voltFrom.value()
        state.BLOCK_BIAS_VOLT_TO = self.voltTo.value()
        state.BLOCK_BIAS_VOLT_POINTS = int(self.voltPoints.value())
        state.BLOCK_BIAS_STEP_DELAY = self.voltStepDelay.value()

        self.bias_power_thread.stream_results.connect(self.show_bias_power_graph)
        self.bias_power_thread.results.connect(self.save_bias_power_scan)
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
        self.bias_power_thread.quit()

    def save_bias_power_scan(self, results):
        try:
            filepath = QFileDialog.getSaveFileName(filter="*.json")[0]
            if not filepath.endswith(".json"):
                filepath += ".json"
            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(results, file, ensure_ascii=False, indent=4)
        except (IndexError, FileNotFoundError):
            pass

    def show_bias_power_graph(self, results):
        if self.stepBiasPowerGraphWindow is None:
            self.stepBiasPowerGraphWindow = StepBiasPowerGraphWindow()
        self.stepBiasPowerGraphWindow.plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
        )
        self.stepBiasPowerGraphWindow.show()

    def rotate(self):
        state.AGILENT_SIGNAL_GENERATOR_FREQUENCY = self.angle.value()
        motor = StepMotorManager(address=state.STEP_MOTOR_ADDRESS)
        motor.rotate(self.angle.value())
