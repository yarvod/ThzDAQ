import logging

from PyQt6.QtCore import QThread, Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QGridLayout,
    QSlider,
    QLabel,
    QHBoxLayout,
)

from api.Chopper.chopper_sync import ChopperManager
from interface.components.ui.Button import Button
from store.state import state


logger = logging.getLogger(__name__)


class ChopperRotateCwThread(QThread):
    def __init__(self, angle: float = 90):
        super().__init__()
        self.angle = angle

    def run(self):
        if not ChopperManager.chopper.client.connected:
            self.finished.emit()
            return
        ChopperManager.chopper.path0(self.angle)
        logger.info("Finish rotate cw")
        self.finished.emit()


class ChopperStartContinuesRotationThread(QThread):
    def run(self):
        if not ChopperManager.chopper.client.connected:
            self.finished.emit()
            return
        ChopperManager.chopper.set_frequency(state.CHOPPER_FREQ)
        ChopperManager.chopper.path1()
        self.finished.emit()


class ChopperStopContinuesRotationThread(QThread):
    def run(self):
        if not ChopperManager.chopper.client.connected:
            self.finished.emit()
            return
        ChopperManager.chopper.path2()
        self.finished.emit()


class ChopperAlignThread(QThread):
    def run(self):
        if not ChopperManager.chopper.client.connected:
            self.finished.emit()
            return
        ChopperManager.chopper.align()
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
        self.chopper_rotate_cw_thread = ChopperRotateCwThread(angle=angle)
        self.chopper_rotate_cw_thread.finished.connect(
            lambda: self.btnRotateCw.setEnabled(True)
        )
        self.chopper_rotate_cw_thread.start()

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

    def stopContinuesRotation(self):
        self.chopper_stop_continues_rotation_thread = (
            ChopperStopContinuesRotationThread()
        )
        self.btnStopContinuesRotate.setEnabled(False)
        self.chopper_stop_continues_rotation_thread.finished.connect(
            lambda: self.btnStopContinuesRotate.setEnabled(True)
        )
        self.chopper_stop_continues_rotation_thread.start()

    def chopperAlign(self):
        self.chopper_align_thread = ChopperAlignThread()
        self.chopper_align_thread.finished.connect(
            lambda: self.btnAlign.setEnabled(True)
        )
        self.btnAlign.setEnabled(False)
        self.chopper_align_thread.start()
