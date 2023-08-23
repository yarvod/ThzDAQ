import time
from typing import Tuple, Dict

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QCheckBox,
)

from api.LakeShore.temperature_controller import TemperatureController
from interface.components.DoubleSpinBox import DoubleSpinBox
from interface.windows.temperatureGraphWindow import TemperatureGraphWindow
from store.state import state


class MonitorThread(QThread):
    temperatures = pyqtSignal(dict)

    def run(self):
        tc = TemperatureController(host=state.LAKE_SHORE_IP, port=state.LAKE_SHORE_PORT)
        start_time = time.time()
        i = 0
        while 1:
            temp_a = tc.get_temperature_a()
            temp_c = tc.get_temperature_c()
            self.temperatures.emit(
                {
                    "temp_a": temp_a,
                    "temp_c": temp_c,
                    "time": time.time() - start_time,
                    "reset": i == 0,
                }
            )
            time.sleep(state.LAKE_SHORE_STREAM_STEP_DELAY)
            i += 1


class TemperatureControllerTabWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.temperatureStreamGraphWindow = None

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

        self.temperatureStreamStepDelayLabel = QLabel(self)
        self.temperatureStreamStepDelayLabel.setText("Step delay, s")
        self.temperatureStreamStepDelay = DoubleSpinBox(self)
        self.temperatureStreamStepDelay.setRange(0.01, 1)
        self.temperatureStreamStepDelay.setValue(state.LAKE_SHORE_STREAM_STEP_DELAY)

        self.checkTemperatureStreamPlot = QCheckBox(self)
        self.checkTemperatureStreamPlot.setText("Plot stream time line")

        self.temperatureStreamTimeLabel = QLabel(self)
        self.temperatureStreamTimeLabel.setText("Time window, s")
        self.temperatureStreamTime = DoubleSpinBox(self)
        self.temperatureStreamTime.setDecimals(0)
        self.temperatureStreamTime.setRange(10, 43200)
        self.temperatureStreamTime.setValue(state.LAKE_SHORE_STREAM_TIME)

        self.btnStartMonitor = QPushButton("Start")
        self.btnStartMonitor.clicked.connect(self.startMonitor)

        self.btnStopMonitor = QPushButton("Stop")
        self.btnStopMonitor.clicked.connect(self.stopMonitor)
        self.btnStopMonitor.setEnabled(False)

        layout.addWidget(self.tempALabel, 0, 0)
        layout.addWidget(self.tempCLabel, 0, 1)
        layout.addWidget(self.tempA, 1, 0)
        layout.addWidget(self.tempC, 1, 1)
        layout.addWidget(self.temperatureStreamStepDelayLabel, 2, 0)
        layout.addWidget(self.temperatureStreamStepDelay, 2, 1)
        layout.addWidget(self.checkTemperatureStreamPlot, 3, 0)
        layout.addWidget(self.temperatureStreamTimeLabel, 4, 0)
        layout.addWidget(self.temperatureStreamTime, 4, 1)
        layout.addWidget(self.btnStartMonitor, 5, 0)
        layout.addWidget(self.btnStopMonitor, 5, 1)

        self.groupMonitor.setLayout(layout)

    def startMonitor(self):
        self.thread_monitor = MonitorThread()
        state.LAKE_SHORE_STREAM_TIME = self.temperatureStreamTime.value()
        state.LAKE_SHORE_STREAM_PLOT_GRAPH = self.checkTemperatureStreamPlot.isChecked()
        state.LAKE_SHORE_STREAM_STEP_DELAY = self.temperatureStreamStepDelay.value()
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

    def updateMonitor(self, measure: Dict):
        self.tempA.setText(f"{measure.get('temp_a')}")
        self.tempC.setText(f"{measure.get('temp_c')}")
        if state.LAKE_SHORE_STREAM_PLOT_GRAPH:
            self.show_temperature_stream_graph(measure=measure)

    def show_temperature_stream_graph(self, measure: Dict):
        if self.temperatureStreamGraphWindow is None:
            self.temperatureStreamGraphWindow = TemperatureGraphWindow()
        self.temperatureStreamGraphWindow.plotNew(
            ds_id="A",
            x=measure.get("time"),
            y=measure.get("temp_a"),
            reset_data=measure.get("reset"),
        )
        self.temperatureStreamGraphWindow.plotNew(
            ds_id="C",
            x=measure.get("time"),
            y=measure.get("temp_c"),
            reset_data=measure.get("reset"),
        )
        self.temperatureStreamGraphWindow.show()
