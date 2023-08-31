import time
from typing import Dict

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QGroupBox,
    QVBoxLayout,
    QPushButton,
    QFormLayout,
    QLabel,
)

from api.RohdeSchwarz.spectrum_fsek30 import SpectrumBlock
from interface.components.DoubleSpinBox import DoubleSpinBox
from interface.windows.spectrumGrpahWindow import SpectrumGraphWindow
from store.state import state


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


class FormWidget(QWidget):
    def __init__(self, parent, label_widget_map: Dict):
        super().__init__(parent)
        self.layout = QFormLayout(self)
        for label, widget in label_widget_map.items():
            self.layout.addRow(label, widget)
        self.setLayout(self.layout)


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

        self.btnStartSpectrum = QPushButton("Start stream spectrum")
        self.btnStartSpectrum.clicked.connect(self.startStreamSpectrum)
        self.btnStopSpectrum = QPushButton("Stop stream spectrum")
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
        if self.spectrumStreamGraphWindow is None:
            self.spectrumStreamGraphWindow = SpectrumGraphWindow()

        self.spectrumStreamGraphWindow.plotNew(x=data["x"], y=data["y"])
        self.spectrumStreamGraphWindow.show()
