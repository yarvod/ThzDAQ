from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QLabel,
)

from api.RohdeSchwarz.spectrum_fsek30 import SpectrumBlock
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.FormWidget import FormWidget
from store import RohdeSchwarzSpectrumFsek30Manager
from threads import Thread
from utils.exceptions import DeviceConnectionError


class SetConfigSpectrumThread(Thread):
    data = pyqtSignal(dict)

    def __init__(
        self,
        cid: int,
        video_bw: float,
        start_frequency: float,
        stop_frequency: float,
    ):
        super().__init__()
        self.cid = cid
        self.video_bw = video_bw
        self.start_frequency = start_frequency
        self.stop_frequency = stop_frequency
        self.config = RohdeSchwarzSpectrumFsek30Manager.get_config(cid)
        self.spectrum = None

    def run(self):
        try:
            self.spectrum = SpectrumBlock(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return
        self.spectrum.set_video_bw(self.video_bw)
        self.spectrum.set_start_frequency(self.start_frequency)
        self.config.start_frequency = self.start_frequency
        self.spectrum.set_stop_frequency(self.stop_frequency)
        self.config.stop_frequency = self.stop_frequency

        self.finished.emit()


class SpectrumConfigWidget(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self.setTitle("Config")
        layout = QVBoxLayout()

        self.videoBwLabel = QLabel(self)
        self.videoBwLabel.setText("Video BW, kHz")
        self.videoBw = DoubleSpinBox(self)
        self.videoBw.setRange(1, 2000)
        self.videoBw.setValue(40)

        self.startFrequencyLabel = QLabel(self)
        self.startFrequencyLabel.setText("Start frequency, GHz")
        self.startFrequency = DoubleSpinBox(self)
        self.startFrequency.setRange(0, 40)
        self.startFrequency.setValue(2)

        self.stopFrequencyLabel = QLabel(self)
        self.stopFrequencyLabel.setText("Stop frequency, GHz")
        self.stopFrequency = DoubleSpinBox(self)
        self.stopFrequency.setRange(0, 40)
        self.stopFrequency.setValue(12)

        self.btnSetConfig = Button("Set Config", animate=True)
        self.btnSetConfig.clicked.connect(self.startStreamSpectrum)

        layout.addWidget(
            FormWidget(
                self,
                {
                    self.videoBwLabel: self.videoBw,
                    self.startFrequencyLabel: self.startFrequency,
                    self.stopFrequencyLabel: self.stopFrequency,
                },
            )
        )
        layout.addWidget(self.btnSetConfig)
        self.setLayout(layout)

    def startStreamSpectrum(self):
        self.config_thread = SetConfigSpectrumThread(
            cid=self.cid,
            video_bw=self.videoBw.value(),
            start_frequency=self.startFrequency.value() * 1e9,
            stop_frequency=self.stopFrequency.value() * 1e9,
        )
        self.config_thread.start()
        self.btnSetConfig.setEnabled(False)
        self.config_thread.finished.connect(lambda: self.btnSetConfig.setEnabled(True))
