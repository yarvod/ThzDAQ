import time
from typing import Dict

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
    QComboBox,
    QFormLayout,
)

from api.LakeShore.temperature_controller import TemperatureController
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.windows.temperatureGraphWindow import TemperatureGraphWindow
from store.base import MeasureModel, MeasureType
from store.state import state


class MonitorThread(QThread):
    temperatures = pyqtSignal(dict)

    def run(self):
        tc = TemperatureController(host=state.LAKE_SHORE_IP, port=state.LAKE_SHORE_PORT)
        start_time = time.time()
        if state.LAKE_SHORE_STREAM_DATA:
            measure = MeasureModel.objects.create(
                measure_type=MeasureType.TEMPERATURE_STREAM,
                data={"temp_a": [], "temp_c": [], "time": []},
            )
            measure.save(finish=False)
        i = 0
        while state.LAKE_SHORE_STREAM_THREAD:
            temp_a = tc.get_temperature_a()
            temp_c = tc.get_temperature_c()
            if state.LAKE_SHORE_STREAM_DATA:
                measure.data["temp_a"].append(temp_a)
                measure.data["temp_c"].append(temp_c)
                measure.data["time"].append(time.time() - start_time)
                measure.save(finish=False)
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

        if state.LAKE_SHORE_STREAM_DATA:
            measure.save()
        self.finished.emit()


class SetHeaterThread(QThread):
    def run(self):
        tc = TemperatureController(host=state.LAKE_SHORE_IP, port=state.LAKE_SHORE_PORT)
        tc.set_heater_range(output=1, value=state.LAKE_SHORE_HEATER_RANGE)
        tc.set_manual_output(output=1, value=state.LAKE_SHORE_MANUAL_OUTPUT)
        tc.set_control_point(output=1, value=state.LAKE_SHORE_SETUP_POINT)
        self.finished.emit()


class TemperatureControllerTabWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.layout = QVBoxLayout(self)
        self.temperatureStreamGraphWindow = None

        self.createGroupMonitor()
        self.createGroupHeater()

        self.layout.addWidget(self.groupMonitor)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupHeater)
        self.layout.addStretch()

        self.setLayout(self.layout)

    def createGroupMonitor(self):
        self.groupMonitor = QGroupBox(self)
        self.groupMonitor.setTitle("Monitor")
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

        self.checkTemperatureStoreData = QCheckBox(self)
        self.checkTemperatureStoreData.setText("Store stream data")

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
        layout.addWidget(self.checkTemperatureStoreData, 3, 1)
        layout.addWidget(self.temperatureStreamTimeLabel, 4, 0)
        layout.addWidget(self.temperatureStreamTime, 4, 1)
        layout.addWidget(self.btnStartMonitor, 5, 0)
        layout.addWidget(self.btnStopMonitor, 5, 1)

        self.groupMonitor.setLayout(layout)

    def startMonitor(self):
        self.thread_monitor = MonitorThread()
        state.LAKE_SHORE_STREAM_THREAD = True
        state.LAKE_SHORE_STREAM_TIME = self.temperatureStreamTime.value()
        state.LAKE_SHORE_STREAM_PLOT_GRAPH = self.checkTemperatureStreamPlot.isChecked()
        state.LAKE_SHORE_STREAM_DATA = self.checkTemperatureStoreData.isChecked()
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
        state.LAKE_SHORE_STREAM_THREAD = False
        self.thread_monitor.quit()
        self.thread_monitor.exit(0)

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

    def createGroupHeater(self):
        self.groupHeater = QGroupBox(self)
        self.groupHeater.setTitle("Heater")
        layout = QFormLayout()

        self.heaterRangeLabel = QLabel(self)
        self.heaterRangeLabel.setText("Heater Range")
        self.heaterRange = QComboBox(self)
        self.heaterRange.addItems(["Off", "Low", "Medium", "High"])

        self.manualOutputLabel = QLabel(self)
        self.manualOutputLabel.setText("Manual Output, %")
        self.manualOutput = DoubleSpinBox(self)
        self.manualOutput.setRange(0, 100)
        self.manualOutput.setValue(100)

        self.setupPointLabel = QLabel(self)
        self.setupPointLabel.setText("Setup Point, K")
        self.setupPoint = DoubleSpinBox(self)
        self.setupPoint.setRange(0.1, 300)
        self.setupPoint.setValue(292)

        self.btnSetHeater = QPushButton("Set Heater")
        self.btnSetHeater.clicked.connect(self.set_heater)

        layout.addRow(self.heaterRangeLabel, self.heaterRange)
        layout.addRow(self.manualOutputLabel, self.manualOutput)
        layout.addRow(self.setupPointLabel, self.setupPoint)
        layout.addRow(self.btnSetHeater)

        self.groupHeater.setLayout(layout)

    def set_heater(self):
        state.LAKE_SHORE_HEATER_RANGE = self.heaterRange.currentIndex()
        state.LAKE_SHORE_MANUAL_OUTPUT = self.manualOutput.value()
        state.LAKE_SHORE_SETUP_POINT = self.setupPoint.value()

        self.set_heater_thread = SetHeaterThread()
        self.set_heater_thread.start()
        self.btnSetHeater.setEnabled(False)
        self.set_heater_thread.finished.connect(
            lambda: self.btnSetHeater.setEnabled(True)
        )
