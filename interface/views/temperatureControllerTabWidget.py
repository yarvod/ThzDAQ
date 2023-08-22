import time
from typing import Tuple

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)

from api.LakeShore.temperature_controller import TemperatureController
from store.state import state


class MonitorThread(QThread):
    temperatures = pyqtSignal(tuple)

    def run(self):
        tc = TemperatureController(host=state.LAKE_SHORE_IP, port=state.LAKE_SHORE_PORT)
        while 1:
            temp_a = tc.get_temperature_a()
            temp_c = tc.get_temperature_c()
            self.temperatures.emit((temp_a, temp_c))
            time.sleep(0.2)


class TemperatureControllerTabWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.createGroupMonitor()

        self.layout.addWidget(self.groupMonitor)
        self.layout.addStretch()

        self.setLayout(self.layout)

    def createGroupMonitor(self):
        self.groupMonitor = QGroupBox("Monitor")
        self.groupMonitor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.tempALabel = QLabel(self)
        self.tempALabel.setText("Temp A, K")
        self.tempA = QLabel(self)
        self.tempA.setText("0")

        self.tempCLabel = QLabel(self)
        self.tempCLabel.setText("Temp C, K")
        self.tempC = QLabel(self)
        self.tempC.setText("0")

        self.btnStartMonitor = QPushButton("Start")
        self.btnStartMonitor.clicked.connect(self.startMonitor)

        self.btnStopMonitor = QPushButton("Stop")
        self.btnStopMonitor.clicked.connect(self.stopMonitor)
        self.btnStopMonitor.setEnabled(False)

        layout.addWidget(self.tempALabel, 0, 0)
        layout.addWidget(self.tempCLabel, 0, 1)
        layout.addWidget(self.tempA, 1, 0)
        layout.addWidget(self.tempC, 1, 1)
        layout.addWidget(self.btnStartMonitor, 2, 0)
        layout.addWidget(self.btnStopMonitor, 2, 1)

        self.groupMonitor.setLayout(layout)

    def startMonitor(self):
        self.thread_monitor = MonitorThread()
        self.thread_monitor.start()
        self.btnStartMonitor.setEnabled(False)
        self.btnStopMonitor.setEnabled(True)
        self.thread_monitor.finished.connect(
            lambda: self.btnStartMonitor.setEnabled(True)
        )
        self.thread_monitor.finished.connect(
            lambda: self.btnStopMonitor.setEnabled(False)
        )
        self.thread_monitor.temperatures.connect(self.updateMonitor)

    def stopMonitor(self):
        self.thread_monitor.terminate()

    def updateMonitor(self, temperatures: Tuple[float, float]):
        temp_a, temp_c = temperatures
        self.tempA.setText(f"{temp_a}")
        self.tempC.setText(f"{temp_c}")
