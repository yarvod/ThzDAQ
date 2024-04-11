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
from interface.components.ui.Lines import HLine
from store.state import state
from threads import Thread
from utils.functions import linear_fit


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

        current1 = current1_get[10]

        voltage2_range = np.linspace(self.voltage2 * 0.95, self.voltage2 * 1.05, 20)
        voltage2_get = []
        current2_get = []
        for voltage in voltage2_range:
            sis.set_bias_voltage(voltage)
            time.sleep(0.05)
            voltage2_get.append(sis.get_bias_voltage())
            current2_get.append(sis.get_bias_current())

        current2 = current2_get[10]

        rn1, _ = linear_fit(voltage1_get, current1_get)
        self.rn1.emit(rn1)
        rn2, _ = linear_fit(voltage2_get, current2_get)
        self.rn2.emit(rn2)

        self.finished.emit(0)


class SisRnPowerMeasureTabWidget(QScrollArea):
    def __init__(self, parent):
        super().__init__(parent)
        self.widget = QWidget()
        self.layout = QVBoxLayout(self)
        self.layout.addStretch()

        self.groupInitialCalibration = None
        self.createGroupInitialCalibration()
        self.layout.addWidget(self.groupInitialCalibration)

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

        self.rn1 = DoubleSpinBox(self)
        self.rn1.setRange(0, 100)
        self.rn1.setValue(0)

        self.rn2 = DoubleSpinBox(self)
        self.rn2.setRange(0, 100)
        self.rn2.setValue(0)

        self.frequencyStart = DoubleSpinBox(self)
        self.frequencyStart.setRange(3, 13)
        self.frequencyStart.setValue(3)

        self.frequencyStop = DoubleSpinBox(self)
        self.frequencyStop.setRange(3, 13)
        self.frequencyStop.setValue(13)

        self.frequencyPoints = QSpinBox(self)
        self.frequencyPoints.setRange(1, 5000)
        self.frequencyPoints.setValue(300)

        self.btnStartCalculateRn = Button("Start Calculate Rn", animate=True)
        self.btnStartCalculateRn.clicked.connect(self.start_initial_calibration)
        self.btnStopCalculateRn = Button("Start Calculate Rn")
        self.btnStopCalculateRn.clicked.connect(self.stop_initial_calibration)

        flayout.addRow("Voltage 1, mV", self.voltage1)
        flayout.addRow("Voltage 2, mV", self.voltage2)
        flayout.addRow("Rn 1, Ohm", self.rn1)
        flayout.addRow("Rn 2, Ohm", self.rn2)
        flayout.addRow(HLine(self))
        flayout.addRow("Frequency start, GHz", self.frequencyStart)
        flayout.addRow("Frequency stop, GHz", self.frequencyStop)
        flayout.addRow("Frequency points", self.frequencyPoints)

        hlayout.addWidget(self.btnStartCalculateRn)
        hlayout.addWidget(self.btnStopCalculateRn)

        layout.addLayout(flayout)
        layout.addLayout(hlayout)
        self.groupInitialCalibration.setLayout(layout)

    def start_initial_calibration(self):
        ...

    def stop_initial_calibration(self):
        ...
