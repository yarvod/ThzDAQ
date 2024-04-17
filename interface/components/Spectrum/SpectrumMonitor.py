import time
from typing import Dict

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QPushButton,
    QLabel,
)

from api.RohdeSchwarz.spectrum_fsek30 import SpectrumBlock
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.FormWidget import FormWidget
from interface.windows.spectrumGraphWindow import SpectrumGraphWindow
from store.state import state
from utils.dock import Dock


class StreamSpectrumThread(QThread):
    data = pyqtSignal(dict)

    def run(self):
        block = SpectrumBlock()
        while 1:
            power = block.get_trace_data()
            if not power:
                continue
            self.data.emit(
                {
                    "x": list(range(len(power))),
                    "y": power,
                }
            )
            time.sleep(state.SPECTRUM_STEP_DELAY)


class SpectrumMonitor(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Monitor")
        layout = QVBoxLayout()

        self.spectrumStreamGraphWindow = None

        self.timeDelayLabel = QLabel(self)
        self.timeDelayLabel.setText("Step delay, s")
        self.timeDelay = DoubleSpinBox(self)
        self.timeDelay.setRange(0.4, 1)
        self.timeDelay.setValue(state.SPECTRUM_STEP_DELAY)

        self.btnStartSpectrum = Button("Start stream spectrum", animate=True)
        self.btnStartSpectrum.clicked.connect(self.startStreamSpectrum)
        self.btnStopSpectrum = Button("Stop stream spectrum")
        self.btnStopSpectrum.clicked.connect(lambda: self.spectrum_thread.terminate())
        self.btnStopSpectrum.setEnabled(False)

        layout.addWidget(FormWidget(self, {self.timeDelayLabel: self.timeDelay}))
        layout.addWidget(self.btnStartSpectrum)
        layout.addWidget(self.btnStopSpectrum)
        self.setLayout(layout)

    def startStreamSpectrum(self):
        state.SPECTRUM_STEP_DELAY = self.timeDelay.value()
        self.spectrum_thread = StreamSpectrumThread()
        self.spectrum_thread.data.connect(self.show_spectrum)
        self.spectrumStreamGraphWindow = Dock.ex.dock_manager.findDockWidget(
            "Spectrum P-F curve"
        )
        self.spectrum_thread.start()
        self.btnStartSpectrum.setEnabled(False)
        self.btnStopSpectrum.setEnabled(True)
        self.spectrum_thread.finished.connect(
            lambda: self.btnStartSpectrum.setEnabled(True)
        )
        self.spectrum_thread.finished.connect(
            lambda: self.btnStopSpectrum.setEnabled(False)
        )

    def show_spectrum(self, data: Dict):
        if self.spectrumStreamGraphWindow.widget() is None:
            return
        self.spectrumStreamGraphWindow.widget().plotNew(x=data["x"], y=data["y"])
        self.spectrumStreamGraphWindow.widget().show()
