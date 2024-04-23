import time
from typing import Dict

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
)

from api.RohdeSchwarz.spectrum_fsek30 import SpectrumBlock
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.FormWidget import FormWidget
from store import RohdeSchwarzSpectrumFsek30Manager
from threads import Thread
from utils.dock import Dock
from utils.exceptions import DeviceConnectionError


class StreamSpectrumThread(Thread):
    data = pyqtSignal(dict)

    def __init__(
        self,
        cid: int,
        step_delay: float,
    ):
        super().__init__()
        self.cid = cid
        self.step_delay = step_delay
        self.config = RohdeSchwarzSpectrumFsek30Manager.get_config(cid)
        self.spectrum = None

    def run(self):
        try:
            self.spectrum = SpectrumBlock(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return
        while 1:
            power, freq = self.spectrum.get_trace_data()
            if not power:
                continue
            self.data.emit(
                {
                    "x": freq,
                    "y": power,
                }
            )
            time.sleep(self.step_delay)


class SpectrumMonitor(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self.setTitle("Monitor")
        layout = QVBoxLayout()
        hlayout = QHBoxLayout()

        self.spectrumStreamGraphWindow = None

        self.timeDelayLabel = QLabel(self)
        self.timeDelayLabel.setText("Step delay, s")
        self.timeDelay = DoubleSpinBox(self)
        self.timeDelay.setRange(0.01, 5)
        self.timeDelay.setValue(0.4)

        self.btnStartSpectrum = Button("Start stream spectrum", animate=True)
        self.btnStartSpectrum.clicked.connect(self.startStreamSpectrum)
        self.btnStopSpectrum = Button("Stop stream spectrum")
        self.btnStopSpectrum.clicked.connect(lambda: self.spectrum_thread.terminate())
        self.btnStopSpectrum.setEnabled(False)

        layout.addWidget(FormWidget(self, {self.timeDelayLabel: self.timeDelay}))
        hlayout.addWidget(self.btnStartSpectrum)
        hlayout.addWidget(self.btnStopSpectrum)
        layout.addLayout(hlayout)
        self.setLayout(layout)

    def startStreamSpectrum(self):
        self.spectrum_thread = StreamSpectrumThread(
            cid=self.cid, step_delay=self.timeDelay.value()
        )
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
