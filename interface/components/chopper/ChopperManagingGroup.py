import logging

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QHBoxLayout,
    QDoubleSpinBox,
)

from api.Chopper import chopper_manager
from interface.components.ui.Button import Button
from store.state import state


logger = logging.getLogger(__name__)


class ChopperRotateCwThread(QThread):
    timeout = 10

    def __init__(self, angle: float = 90):
        super().__init__()
        self.angle = angle

    def run(self):
        if not chopper_manager.chopper.client.connected:
            return
        chopper_manager.chopper.path0(self.angle)
        logger.info("Finish rotate cw")


class ChopperStartContinuesRotationThread(QThread):
    def run(self):
        if not chopper_manager.chopper.client.connected:
            return
        chopper_manager.chopper.set_frequency(state.CHOPPER_FREQ)
        chopper_manager.chopper.path1()


class ChopperStopContinuesRotationThread(QThread):
    def run(self):
        if not chopper_manager.chopper.client.connected:
            return
        chopper_manager.chopper.path2()


class ChopperAlignThread(QThread):
    def run(self):
        if not chopper_manager.chopper.client.connected:
            return
        chopper_manager.chopper.align_to_hot()


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
        self.btnAlign = Button("Align to Hot", animate=True)
        self.btnAlign.clicked.connect(self.chopperAlign)

        horizontal_layout.addWidget(self.btnRotateCw)
        horizontal_layout.addWidget(self.btnAlign)
        layout.addLayout(horizontal_layout)

        self.frequencyLabel = QLabel(self)
        self.frequencyLabel.setText("Frequency, Hz")
        self.frequencyInput = QDoubleSpinBox(self)
        self.frequencyInput.setRange(0.1, 20)
        self.frequencyInput.setDecimals(2)
        self.frequencyInput.setSingleStep(0.1)
        self.frequencyInput.setValue(float(state.CHOPPER_FREQ))

        grid_layout.addWidget(self.frequencyLabel, 1, 0)
        grid_layout.addWidget(self.frequencyInput, 1, 1)
        layout.addLayout(grid_layout)

        self.btnStartContinuesRotate = Button("Continues rotate", animate=True)
        self.btnStartContinuesRotate.clicked.connect(self.startContinuesRotation)
        self.btnStopContinuesRotate = Button("Stop rotate", animate=True)
        self.btnStopContinuesRotate.clicked.connect(self.stopContinuesRotation)

        horizontal_layout2.addWidget(self.btnStartContinuesRotate)
        horizontal_layout2.addWidget(self.btnStopContinuesRotate)
        layout.addLayout(horizontal_layout2)

        self.setLayout(layout)

    def startThreadWithTimeout(
        self, thread: QThread, button: Button, timeout_ms: int, label: str
    ):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(timeout_ms)

        def cleanup():
            timer.stop()
            timer.deleteLater()
            button.setEnabled(True)

        def terminate_thread():
            if not thread.isRunning():
                return
            logger.warning(f"[{label}] timeout exceeded, terminating thread")
            thread.terminate()
            thread.wait(1000)

        button.setEnabled(False)
        thread.finished.connect(cleanup)
        timer.timeout.connect(terminate_thread)
        timer.start()
        thread.start()

    # Buttons methods
    def rotateCw(self, angle: float):
        self.chopper_rotate_cw_thread = ChopperRotateCwThread(angle=angle)
        self.startThreadWithTimeout(
            thread=self.chopper_rotate_cw_thread,
            button=self.btnRotateCw,
            timeout_ms=self.chopper_rotate_cw_thread.timeout * 1000,
            label="rotateCw",
        )

    def startContinuesRotation(self):
        state.CHOPPER_FREQ = self.frequencyInput.value()
        self.chopper_start_continues_rotation_thread = (
            ChopperStartContinuesRotationThread()
        )
        self.startThreadWithTimeout(
            thread=self.chopper_start_continues_rotation_thread,
            button=self.btnStartContinuesRotate,
            timeout_ms=10000,
            label="startContinuesRotation",
        )

    def stopContinuesRotation(self):
        self.chopper_stop_continues_rotation_thread = (
            ChopperStopContinuesRotationThread()
        )
        self.startThreadWithTimeout(
            thread=self.chopper_stop_continues_rotation_thread,
            button=self.btnStopContinuesRotate,
            timeout_ms=25000,
            label="stopContinuesRotation",
        )

    def chopperAlign(self):
        self.chopper_align_thread = ChopperAlignThread()
        self.startThreadWithTimeout(
            thread=self.chopper_align_thread,
            button=self.btnAlign,
            timeout_ms=10000,
            label="chopperAlign",
        )
