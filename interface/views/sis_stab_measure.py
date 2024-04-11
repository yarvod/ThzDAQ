import time

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QScrollArea,
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QHBoxLayout,
)

from api.Scontel.sis_block import SisBlock
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store.state import state
from threads import Thread


class InitialCalibrationThread(Thread):
    rn1 = pyqtSignal(float)
    rn2 = pyqtSignal(float)

    def __init__(
        self,
        voltage1,
        voltage2,
        frequency_start,
        frequency_stop,
        frequency_points,
    ):
        super().__init__()
        self.voltage1 = voltage1
        self.voltage2 = voltage2
        self.frequency_start = frequency_start
        self.frequency_stop = frequency_stop
        self.frequency_points = frequency_points

    def run(self):
        sis = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            ctrl_dev=state.BLOCK_CTRL_DEV,
            bias_dev=state.BLOCK_BIAS_DEV,
        )
        sis.connect()

        # measure iv curve rn
        voltage1_range = np.linspace(self.voltage1 * 0.95, self.voltage1 * 1.05, 20)
        voltage1_get = []
        current1_get = []
        for voltage in voltage1_range:
            sis.set_bias_voltage(voltage)
            time.sleep(0.05)
            voltage1_get.append(sis.get_bias_voltage())
            current1_get.append(sis.get_bias_current())

        voltage2_range = np.linspace(self.voltage2 * 0.95, self.voltage2 * 1.05, 20)
        voltage2_get = []
        current2_get = []
        for voltage in voltage2_range:
            sis.set_bias_voltage(voltage)
            time.sleep(0.05)
            voltage2_get.append(sis.get_bias_voltage())
            current2_get.append(sis.get_bias_current())

        self.finished.emit(0)


class SisRnPowerMeasureTabWidget(QScrollArea):
    def __init__(self, parent):
        super().__init__(parent)
        self.widget = QWidget()
        self.layout = QVBoxLayout(self)
        self.layout.addStretch()
        self.widget.setLayout(self.layout)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setWidget(self.widget)

    def createGroupInitialCalibration(self):
        self.groupInitialCalibration = QGroupBox(self)
        self.groupInitialCalibration.setTitle("Initial calibration")

        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.voltage1 = DoubleSpinBox(self)
        self.voltage1.setRange(-30, 30)
        self.voltage1.setValue(15)

        self.voltage2 = DoubleSpinBox(self)
        self.voltage2.setRange(-30, 30)
        self.voltage2.setValue(20)

        self.frequencyStart = DoubleSpinBox(self)
        self.frequencyStart.setRange(3, 13)
        self.frequencyStart.setValue(3)

        self.frequencyStop = DoubleSpinBox(self)
        self.frequencyStop.setRange(3, 13)
        self.frequencyStop.setValue(13)

        self.frequencyPoints = QSpinBox(self)
        self.frequencyPoints.setRange(1, 5000)
        self.frequencyPoints.setValue(300)

        self.btnStartInitialCalibration = Button("Start", animate=True)
        self.btnStartInitialCalibration.clicked.connect(self.start_initial_calibration)
        self.btnStopInitialCalibration = Button("Stop")
        self.btnStopInitialCalibration.clicked.connect(self.stop_initial_calibration)

        flayout.addRow("Voltage 1, mV", self.voltage1)
        flayout.addRow("Voltage 2, mV", self.voltage2)
        flayout.addRow("Frequency start, GHz", self.frequencyStart)
        flayout.addRow("Frequency stop, GHz", self.frequencyStop)
        flayout.addRow("Frequency points", self.frequencyPoints)

        hlayout.addWidget(self.btnStartInitialCalibration)
        hlayout.addWidget(self.btnStopInitialCalibration)

        layout.addLayout(flayout)
        layout.addLayout(hlayout)

    def start_initial_calibration(self):
        ...

    def stop_initial_calibration(self):
        ...
