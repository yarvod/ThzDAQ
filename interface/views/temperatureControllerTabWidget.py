import time
from typing import Dict

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QGroupBox,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QCheckBox,
    QComboBox,
    QFormLayout,
)

from api.LakeShore.temperature_controller import TemperatureController
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store import LakeShoreTemperatureControllerManager
from store.base import MeasureModel, MeasureType
from threads import Thread
from utils.dock import Dock
from utils.exceptions import DeviceConnectionError


class MonitorThread(Thread):
    temperatures = pyqtSignal(dict)

    def __init__(
        self,
        cid: int,
        step_delay: float,
        store_data: bool,
    ):
        super().__init__()
        self.cid = cid
        self.step_delay = step_delay
        self.store_data = store_data
        self.config = LakeShoreTemperatureControllerManager.get_config(self.cid)
        self.tc = None
        if store_data:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureType.TEMPERATURE_STREAM,
                data={"temp_a": [], "temp_c": [], "temp_b": [], "time": []},
            )
            self.measure.save(finish=False)

    def run(self):
        try:
            self.tc = TemperatureController(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return
        start_time = time.time()
        i = 0
        while self.config.thread_stream:
            temp_a = self.tc.get_temperature_a()
            temp_c = self.tc.get_temperature_c()
            temp_b = self.tc.get_temperature_b()
            if self.store_data:
                self.measure.data["temp_a"].append(temp_a)
                self.measure.data["temp_c"].append(temp_c)
                self.measure.data["temp_b"].append(temp_b)
                self.measure.data["time"].append(time.time() - start_time)
            self.temperatures.emit(
                {
                    "temp_a": temp_a,
                    "temp_c": temp_c,
                    "temp_b": temp_b,
                    "time": time.time() - start_time,
                    "reset": i == 0,
                }
            )
            time.sleep(self.step_delay)
            i += 1

        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        if self.store_data:
            self.measure.save()


class SetHeaterThread(Thread):
    def __init__(
        self, cid: int, heater_range: int, manual_output: float, setup_point: float
    ):
        super().__init__()
        self.cid = cid
        self.heater_range = heater_range
        self.manual_output = manual_output
        self.setup_point = setup_point
        self.config = LakeShoreTemperatureControllerManager.get_config(self.cid)
        self.tc = None

    def run(self):
        try:
            self.tc = TemperatureController(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return
        self.tc.set_heater_range(output=1, value=self.heater_range)
        self.tc.set_manual_output(output=1, value=self.manual_output)
        self.tc.set_control_point(output=1, value=self.setup_point)
        del self.tc
        self.finished.emit()


class TemperatureControllerTabWidget(QWidget):
    def __init__(
        self,
        *args,
        cid,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.cid = cid
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
        layout = QVBoxLayout()
        control_layout = QGridLayout()
        monitor_layout = QGridLayout()

        self.tempALabel = QLabel(self)
        self.tempALabel.setText("Temp A, K")
        self.tempA = QLabel(self)
        self.tempA.setText("0")

        self.tempBLabel = QLabel(self)
        self.tempBLabel.setText("Temp B, K")
        self.tempB = QLabel(self)
        self.tempB.setText("0")

        self.tempCLabel = QLabel(self)
        self.tempCLabel.setText("Temp C, K")
        self.tempC = QLabel(self)
        self.tempC.setText("0")

        self.temperatureStreamStepDelayLabel = QLabel(self)
        self.temperatureStreamStepDelayLabel.setText("Step delay, s")
        self.temperatureStreamStepDelay = DoubleSpinBox(self)
        self.temperatureStreamStepDelay.setRange(0.01, 1)
        self.temperatureStreamStepDelay.setValue(0.2)

        self.checkTemperatureStreamPlot = QCheckBox(self)
        self.checkTemperatureStreamPlot.setText("Plot stream time line")

        self.checkTemperatureStoreData = QCheckBox(self)
        self.checkTemperatureStoreData.setText("Store stream data")

        self.temperatureStreamTimeLabel = QLabel(self)
        self.temperatureStreamTimeLabel.setText("Time window, s")
        self.temperatureStreamTime = DoubleSpinBox(self)
        self.temperatureStreamTime.setDecimals(0)
        self.temperatureStreamTime.setRange(10, 43200)
        self.temperatureStreamTime.setValue(30)

        self.btnStartMonitor = Button("Start", animate=True)
        self.btnStartMonitor.clicked.connect(self.startMonitor)

        self.btnStopMonitor = Button("Stop")
        self.btnStopMonitor.clicked.connect(self.stopMonitor)
        self.btnStopMonitor.setEnabled(False)

        monitor_layout.addWidget(self.tempALabel, 0, 0)
        monitor_layout.addWidget(self.tempBLabel, 0, 1)
        monitor_layout.addWidget(self.tempCLabel, 0, 2)
        monitor_layout.addWidget(self.tempA, 1, 0)
        monitor_layout.addWidget(self.tempB, 1, 1)
        monitor_layout.addWidget(self.tempC, 1, 2)
        layout.addLayout(monitor_layout)
        control_layout.addWidget(self.temperatureStreamStepDelayLabel, 2, 0)
        control_layout.addWidget(self.temperatureStreamStepDelay, 2, 1)
        control_layout.addWidget(self.checkTemperatureStreamPlot, 3, 0)
        control_layout.addWidget(self.checkTemperatureStoreData, 3, 1)
        control_layout.addWidget(self.temperatureStreamTimeLabel, 4, 0)
        control_layout.addWidget(self.temperatureStreamTime, 4, 1)
        control_layout.addWidget(self.btnStartMonitor, 5, 0)
        control_layout.addWidget(self.btnStopMonitor, 5, 1)
        layout.addLayout(control_layout)

        self.groupMonitor.setLayout(layout)

    def startMonitor(self):
        self.thread_monitor = MonitorThread(
            cid=self.cid,
            step_delay=self.temperatureStreamStepDelay.value(),
            store_data=self.checkTemperatureStoreData.isChecked(),
        )
        config = LakeShoreTemperatureControllerManager.get_config(self.cid)
        config.thread_stream = True

        self.temperatureStreamGraphWindow = Dock.ex.dock_manager.findDockWidget(
            "T-t curve"
        )
        self.temperatureStreamGraphWindow.widget().stream_window = (
            self.temperatureStreamTime.value()
        )
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
        config = LakeShoreTemperatureControllerManager.get_config(cid=self.cid)
        config.thread_stream = False
        self.thread_monitor.exit(0)

    def updateMonitor(self, measure: Dict):
        self.tempA.setText(f"{measure.get('temp_a')}")
        self.tempC.setText(f"{measure.get('temp_c')}")
        self.tempB.setText(f"{measure.get('temp_b')}")
        if self.checkTemperatureStreamPlot.isChecked():
            self.show_temperature_stream_graph(measure=measure)

    def show_temperature_stream_graph(self, measure: Dict):
        if self.temperatureStreamGraphWindow is None:
            return
        self.temperatureStreamGraphWindow.widget().plotNew(
            ds_id="A",
            x=measure.get("time"),
            y=measure.get("temp_a"),
            reset_data=measure.get("reset"),
        )
        self.temperatureStreamGraphWindow.widget().plotNew(
            ds_id="B",
            x=measure.get("time"),
            y=measure.get("temp_b"),
            reset_data=measure.get("reset"),
        )
        self.temperatureStreamGraphWindow.widget().plotNew(
            ds_id="C",
            x=measure.get("time"),
            y=measure.get("temp_c"),
            reset_data=measure.get("reset"),
        )

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

        self.btnSetHeater = Button("Set Heater", animate=True)
        self.btnSetHeater.clicked.connect(self.set_heater)

        layout.addRow(self.heaterRangeLabel, self.heaterRange)
        layout.addRow(self.manualOutputLabel, self.manualOutput)
        layout.addRow(self.setupPointLabel, self.setupPoint)
        layout.addRow(self.btnSetHeater)

        self.groupHeater.setLayout(layout)

    def set_heater(self):
        self.set_heater_thread = SetHeaterThread(
            cid=self.cid,
            heater_range=self.heaterRange.currentIndex(),
            manual_output=self.manualOutput.value(),
            setup_point=self.setupPoint.value(),
        )
        self.set_heater_thread.start()
        self.btnSetHeater.setEnabled(False)
        self.set_heater_thread.finished.connect(
            lambda: self.btnSetHeater.setEnabled(True)
        )
