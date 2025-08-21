import time

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QFormLayout,
    QLabel,
    QProgressBar,
    QHBoxLayout,
    QVBoxLayout,
    QComboBox,
)

from api.Arduino.grid import GridDevice
from api.Scontel.sis_block import SisBlock
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store import ScontelSisBlockManager, GridManager, GridConfig
from store.base import MeasureModel
from store.state import state
from threads import Thread
from utils.dock import Dock
from utils.exceptions import DeviceConnectionError


class MeasureThread(Thread):
    progress = Signal(int)
    stream_ia = Signal(dict)

    def __init__(
        self,
        sis_cid: int,
        grid_cid: int,
        angle_start: float,
        angle_stop: float,
        angle_step: float,
    ):
        super().__init__()
        self.block = None
        self.grid = None
        self.sis_config = ScontelSisBlockManager.get_config(sis_cid)
        self.grid_config: GridConfig = GridManager.get_config(grid_cid)
        self.grid_config.thread_sis_current_scan = True
        self.initial_angle = self.grid_config.current_angle.value
        self.angle_start = angle_start
        self.angle_stop = angle_stop
        self.angle_step = angle_step
        self.measure = MeasureModel.objects.create(
            measure_type=MeasureModel.type_class.GRID_IA_CURVE, data={}
        )
        self.measure.save(False)

    def run(self):
        try:
            self.block = SisBlock(**self.sis_config.dict())
            self.grid = GridDevice(**self.grid_config.dict())
        except DeviceConnectionError as e:
            self.pre_exit()
            self.finished.emit()
            return

        angle_range = np.arange(
            self.angle_start,
            self.angle_stop + self.angle_step,
            self.angle_step,
        )

        angle_success = self.grid.rotate(
            self.angle_start, self.grid_config.current_angle.value
        )
        self.grid_config.current_angle.value = angle_success
        time.sleep(abs(self.angle_start) / state.GRID_SPEED)

        results = {
            "angle": [],
            "current_get": [],
            "voltage_get": [],
        }

        for i, angle in enumerate(angle_range):
            if not self.grid_config.thread_sis_current_scan:
                break

            if i != 0:
                angle_success = self.grid.rotate(
                    angle, self.grid_config.current_angle.value
                )
                self.grid_config.current_angle.value = angle_success
                time.sleep(abs(self.angle_step) / state.GRID_SPEED)

            voltage = self.block.get_bias_voltage()
            if not voltage:
                continue
            current = self.block.get_bias_current()
            if not current:
                continue

            results["angle"].append(angle)
            results["voltage_get"].append(voltage)
            results["current_get"].append(current)
            self.measure.data = results

            self.stream_ia.emit(
                {
                    "x": [angle],
                    "y": [current * 1e6],
                    "new_plot": i == 0,
                }
            )
            progress = int((i + 1) / len(angle_range) * 100)
            self.progress.emit(progress)

        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        angle_success = self.grid.rotate(
            self.initial_angle, self.grid_config.current_angle.value
        )
        self.grid_config.current_angle.value = angle_success
        self.measure.save()
        self.progress.emit(0)
        self.grid_config.thread_sis_current_scan = False


class GridBiasCurrentScan(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self.setTitle("Grid Sis current angle scan")
        self.gridBiasCurrentAngleGraphWindow = None
        self.plot_number = 1

        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.sisConfigLabel = QLabel(self)
        self.sisConfigLabel.setText("SIS block device")
        self.sisConfig = QComboBox(self)
        ScontelSisBlockManager.event_manager.configs_updated.connect(
            lambda: ScontelSisBlockManager.update_sis_config(self)
        )

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

        self.progress = QProgressBar(self)
        self.progress.setValue(0)

        self.btnStart = Button("Start Scan", animate=True)
        self.btnStart.clicked.connect(self.start_measure)

        self.btnStop = Button("Stop Scan")
        self.btnStop.clicked.connect(self.stop_measure)
        self.btnStop.setEnabled(False)

        flayout.addRow(self.sisConfigLabel, self.sisConfig)
        flayout.addRow(self.angleStartLabel, self.angleStart)
        flayout.addRow(self.angleStopLabel, self.angleStop)
        flayout.addRow(self.angleStepLabel, self.angleStep)
        flayout.addRow(self.progress)
        hlayout.addWidget(self.btnStart)
        hlayout.addWidget(self.btnStop)
        layout.addLayout(flayout)
        layout.addLayout(hlayout)
        self.setLayout(layout)

        ScontelSisBlockManager.update_sis_config(self)

    def start_measure(self):
        sis_cid = ScontelSisBlockManager.configs[self.sisConfig.currentIndex()].cid

        self.thread = MeasureThread(
            sis_cid=sis_cid,
            grid_cid=self.cid,
            angle_start=self.angleStart.value(),
            angle_stop=self.angleStop.value(),
            angle_step=self.angleStep.value(),
        )

        self.thread.stream_ia.connect(self.show_graph)

        self.thread.progress.connect(lambda x: self.progress.setValue(x))
        self.thread.finished.connect(lambda: self.progress.setValue(0))

        self.gridBiasCurrentAngleGraphWindow = Dock.ex.dock_manager.findDockWidget(
            "GRID I-A curve"
        )
        self.thread.start()

        self.btnStart.setEnabled(False)
        self.thread.finished.connect(lambda: self.btnStart.setEnabled(True))

        self.btnStop.setEnabled(True)
        self.thread.finished.connect(lambda: self.btnStop.setEnabled(False))

    def stop_measure(self):
        grid_config = GridManager.get_config(self.cid)
        grid_config.thread_sis_current_scan = False

    def show_graph(self, results):
        if self.gridBiasCurrentAngleGraphWindow is None:
            return
        if results.get("new_plot"):
            self.plot_number = (
                self.gridBiasCurrentAngleGraphWindow.widget().get_last_plot_number() + 1
            )
        self.gridBiasCurrentAngleGraphWindow.widget().plot(
            x=results.get("x", []),
            y=results.get("y", []),
            plot_num=self.plot_number,
        )
        self.gridBiasCurrentAngleGraphWindow.widget().show()
