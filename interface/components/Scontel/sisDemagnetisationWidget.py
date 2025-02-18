import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QSizePolicy,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QHBoxLayout,
    QProgressBar,
)

from api.Scontel.sis_block import SisBlock
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store.state import state
from threads import Thread


class ThreadDemagnetization(Thread):
    progress = Signal(int)

    def __init__(
        self,
        min_current,
        max_current,
        step,
    ):
        super().__init__()
        self.min_current = min_current
        self.max_current = max_current
        self.step = step
        self.sis = None

    @staticmethod
    def generate_range(min_current, max_current, step):
        full = list(np.arange(min_current, max_current + step, step))
        res = full
        reversed_full = [_ for _ in reversed(full)]
        for i in range(len(full) // 2):
            reversed_full.pop(0)
            reversed_full.pop(-1)
            res.extend(reversed_full)
        return res

    def run(self):
        self.sis = SisBlock(host=state.BLOCK_ADDRESS, port=state.BLOCK_PORT)
        self.sis.connect()
        current_range = self.generate_range(
            self.min_current, self.max_current, self.step
        )
        for i, current in enumerate(current_range, 1):
            self.sis.set_ctrl_current(current)
            self.progress.emit(int(i / len(current_range) * 100))
        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        self.sis.disconnect()


class SisDemagnetisationWidget(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.thread_demag = None
        self.setTitle("Demagnetization")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.minCurrentLabel = QLabel(self)
        self.minCurrentLabel.setText("Min current, mA:")
        self.minCurrent = DoubleSpinBox(self)
        self.minCurrent.setRange(-50, 50)
        self.minCurrent.setDecimals(1)
        self.minCurrent.setValue(-30)

        self.maxCurrentLabel = QLabel(self)
        self.maxCurrentLabel.setText("Max current, mA:")
        self.maxCurrent = DoubleSpinBox(self)
        self.maxCurrent.setRange(-50, 50)
        self.maxCurrent.setDecimals(1)
        self.maxCurrent.setValue(30)

        self.currentStepLabel = QLabel(self)
        self.currentStepLabel.setText("Step current, mA:")
        self.currentStep = DoubleSpinBox(self)
        self.currentStep.setRange(-50, 50)
        self.currentStep.setDecimals(2)
        self.currentStep.setValue(5)

        self.progress = QProgressBar(self)
        self.progress.setValue(0)

        flayout.addRow(self.minCurrentLabel, self.minCurrent)
        flayout.addRow(self.maxCurrentLabel, self.maxCurrent)
        flayout.addRow(self.currentStepLabel, self.currentStep)
        flayout.addRow(self.progress)

        self.btnStart = Button("Start", animate=True)
        self.btnStart.clicked.connect(self.start)

        self.btnStop = Button("Stop", animate=False)
        self.btnStop.clicked.connect(self.stop)
        self.btnStop.setEnabled(False)

        hlayout.addWidget(self.btnStart)
        hlayout.addWidget(self.btnStop)

        self.layout.addLayout(flayout)
        self.layout.addLayout(hlayout)
        self.setLayout(self.layout)

    def start(self):
        self.thread_demag = ThreadDemagnetization(
            min_current=self.minCurrent.value(),
            max_current=self.maxCurrent.value(),
            step=self.currentStep.value(),
        )
        state.BLOCK_DEMAG_THREAD = True

        self.thread_demag.progress.connect(lambda x: self.progress.setValue(x))
        self.thread_demag.finished.connect(lambda: self.progress.setValue(0))
        self.thread_demag.finished.connect(lambda: self.btnStart.setEnabled(True))
        self.thread_demag.finished.connect(lambda: self.btnStop.setEnabled(False))
        self.btnStart.setEnabled(False)
        self.btnStop.setEnabled(True)
        self.thread_demag.start()

    def stop(self):
        state.BLOCK_DEMAG_THREAD = False
