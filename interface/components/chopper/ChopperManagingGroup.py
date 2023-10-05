import asyncio
import logging

from PyQt6.QtCore import QThread, Qt, QTimer, QObject, pyqtSlot, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QGridLayout,
    QSlider,
    QLabel,
    QHBoxLayout,
)

from api.Chopper import chopper_manager
from interface.components.ui.Button import Button
from store.state import state


logger = logging.getLogger(__name__)


class ChopperRotateCwThread(QThread):
    timeout = 10

    def run(self):
        state.EVENT_LOOP.run_until_complete(self.process())

    async def process(self):
        chopper = await chopper_manager.async_chopper
        await chopper.path0()
        self.finished.emit()
        await asyncio.sleep(0.1)


class ChopperStartContinuesRotationThread(QThread):
    def run(self):
        if not chopper_manager.chopper.client.connected:
            self.finished.emit()
            return
        chopper_manager.chopper.set_frequency(state.CHOPPER_FREQ)
        chopper_manager.chopper.path1()
        self.finished.emit()


class ChopperStopContinuesRotationThread(QThread):
    def run(self):
        if not chopper_manager.chopper.client.connected:
            self.finished.emit()
            return
        chopper_manager.chopper.path2()
        self.finished.emit()


class ChopperAlignThread(QThread):
    def run(self):
        if not chopper_manager.chopper.client.connected:
            self.finished.emit()
            return
        chopper_manager.chopper.align()
        self.finished.emit()


class ChopperManagingGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Managing")
        layout = QVBoxLayout(self)
        grid_layout = QGridLayout()
        horizontal_layout = QHBoxLayout()
        horizontal_layout2 = QHBoxLayout()

        self.btnRotateCw = Button("Rotate Hot/Cold", animate=True)
        self.btnRotateCw.clicked.connect(lambda: self.rotateCw(90))
        self.btnAlign = Button("Align", animate=True)
        self.btnAlign.clicked.connect(self.chopperAlign)

        horizontal_layout.addWidget(self.btnRotateCw)
        horizontal_layout.addWidget(self.btnAlign)
        layout.addLayout(horizontal_layout)

        self.speedSliderLabel = QLabel(self)
        self.speedSliderLabel.setText(f"Speed {state.CHOPPER_FREQ} Hz")
        self.speedSlider = QSlider(self)
        self.speedSlider.setMinimum(1)
        self.speedSlider.setMaximum(20)
        self.speedSlider.setValue(state.CHOPPER_FREQ)
        self.speedSlider.setOrientation(Qt.Orientation.Horizontal)
        self.speedSlider.setInvertedControls(False)
        self.speedSlider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.speedSlider.setTickInterval(1)
        self.speedSlider.valueChanged.connect(self.updateChopperFreq)

        grid_layout.addWidget(self.speedSliderLabel, 1, 0)
        grid_layout.addWidget(self.speedSlider, 1, 1)
        layout.addLayout(grid_layout)

        self.btnStartContinuesRotate = Button("Continues rotate", animate=True)
        self.btnStartContinuesRotate.clicked.connect(self.startContinuesRotation)
        self.btnStopContinuesRotate = Button("Stop rotate", animate=True)
        self.btnStopContinuesRotate.clicked.connect(self.stopContinuesRotation)

        horizontal_layout2.addWidget(self.btnStartContinuesRotate)
        horizontal_layout2.addWidget(self.btnStopContinuesRotate)
        layout.addLayout(horizontal_layout2)

        self.setLayout(layout)

    # Events methods
    def updateChopperFreq(self):
        state.CHOPPER_FREQ = self.speedSlider.value()
        self.speedSliderLabel.setText(f"Speed {state.CHOPPER_FREQ} Hz")

    # Buttons methods
    def rotateCw(self, angle: float):
        self.btnRotateCw.setEnabled(False)
        self.chopper_rotate_cw_thread = ChopperRotateCwThread()
        logic = Logic()
        logic.moveToThread(self.chopper_rotate_cw_thread)
        logic.finished.connect(self.chopper_rotate_cw_thread.quit)
        self.chopper_rotate_cw_thread.finished.connect(
            lambda: self.btnRotateCw.setEnabled(True)
        )
        self.chopper_rotate_cw_thread.start()

        self.time_rotate_cw = QTimer()
        self.time_rotate_cw.setInterval(self.chopper_rotate_cw_thread.timeout * 1000)
        self.time_rotate_cw.timeout.connect(
            lambda: self.chopper_rotate_cw_thread.terminate()
        )
        self.time_rotate_cw.start()

    def startContinuesRotation(self):
        state.CHOPPER_FREQ = self.speedSlider.value()
        self.chopper_start_continues_rotation_thread = (
            ChopperStartContinuesRotationThread()
        )
        self.btnStartContinuesRotate.setEnabled(False)
        self.chopper_start_continues_rotation_thread.finished.connect(
            lambda: self.btnStartContinuesRotate.setEnabled(True)
        )
        self.chopper_start_continues_rotation_thread.start()

        self.timer_continues_rotation = QTimer()
        self.timer_continues_rotation.setInterval(10000)
        self.timer_continues_rotation.timeout.connect(
            lambda: self.chopper_start_continues_rotation_thread.terminate()
        )
        self.timer_continues_rotation.start()

    def stopContinuesRotation(self):
        self.chopper_stop_continues_rotation_thread = (
            ChopperStopContinuesRotationThread()
        )
        self.btnStopContinuesRotate.setEnabled(False)
        self.chopper_stop_continues_rotation_thread.finished.connect(
            lambda: self.btnStopContinuesRotate.setEnabled(True)
        )
        self.chopper_stop_continues_rotation_thread.start()
        self.timer_stop_continues_rotation = QTimer()
        self.timer_stop_continues_rotation.setInterval(10000)
        self.timer_stop_continues_rotation.timeout.connect(
            lambda: self.chopper_stop_continues_rotation_thread.terminate()
        )
        self.timer_stop_continues_rotation.start()

    def chopperAlign(self):
        self.chopper_align_thread = ChopperAlignThread()
        self.chopper_align_thread.finished.connect(
            lambda: self.btnAlign.setEnabled(True)
        )
        self.btnAlign.setEnabled(False)
        self.chopper_align_thread.start()

        self.timer_chopper_align = QTimer()
        self.timer_chopper_align.setInterval(10000)
        self.timer_chopper_align.timeout.connect(
            lambda: self.chopper_align_thread.terminate()
        )
        self.timer_chopper_align.start()
