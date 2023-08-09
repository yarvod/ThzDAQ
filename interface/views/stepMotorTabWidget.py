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
)

from api.arduino.arduino import StepMotorManager
from api.block import Block
from api.rs_nrx import NRXBlock
from interface.components import CustomQDoubleSpinBox
from state import state


class BiasPowerThread(QThread):
    results = pyqtSignal(dict)
    stream_results = pyqtSignal(dict)

    def run(self):
        motor = StepMotorManager(address=state.STEP_MOTOR_ADDRESS)
        nrx = NRXBlock(
            ip=state.NRX_IP,
            filter_time=state.NRX_FILTER_TIME,
            aperture_time=state.NRX_APER_TIME,
        )
        block = Block(
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
        angle_range = np.linspace(
            state.STEP_MOTOR_ANGLE_FROM,
            state.STEP_MOTOR_ANGLE_TO,
            state.STEP_MOTOR_ANGLE_POINTS,
        )
        volt_range = np.linspace(
            state.BLOCK_BIAS_VOLT_FROM * 1e-3,
            state.BLOCK_BIAS_VOLT_TO * 1e-3,
            state.BLOCK_BIAS_VOLT_POINTS,
        )
        initial_v = block.get_bias_voltage()
        initial_time = time.time()
        for angle in angle_range:
            motor.rotate(angle)
            time.sleep(0.5)
            for i, voltage_set in enumerate(volt_range):
                if not state.BLOCK_BIAS_POWER_MEASURE_THREAD:
                    break

                block.set_bias_voltage(voltage_set)
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

        block.set_bias_voltage(initial_v)
        self.results.emit(results)
        self.finished.emit()


class StepMotorTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.createGroupStepMotor()
        self.layout.addWidget(self.groupStepMotor)
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

    def rotate(self):
        state.AGILENT_SIGNAL_GENERATOR_FREQUENCY = self.angle.value()
        motor = StepMotorManager(address=state.STEP_MOTOR_ADDRESS)
        motor.rotate(self.angle.value())
