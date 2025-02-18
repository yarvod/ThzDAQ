from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
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
    data = Signal(dict)

    def __init__(
        self,
        cid: int,
        video_bw: float,
        start_frequency: float,
        stop_frequency: float,
        delay: float,
    ):
        super().__init__()
        self.cid = cid
        self.video_bw = video_bw
        self.start_frequency = start_frequency
        self.stop_frequency = stop_frequency
        self.config = RohdeSchwarzSpectrumFsek30Manager.get_config(cid)
        self.config.delay = delay
        self.spectrum = None

    def run(self):
        try:
            self.spectrum = SpectrumBlock(**self.config.dict(), delay=self.config.delay)
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

        self.readDelayLabel = QLabel(self)
        self.readDelayLabel.setText("Read delay, s")
        self.readDelay = DoubleSpinBox(self)
        self.readDelay.setRange(0, 3)
        self.readDelay.setValue(0.2)

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
        self.btnSetConfig.clicked.connect(self.set_config)

        layout.addWidget(
            FormWidget(
                self,
                {
                    self.readDelayLabel: self.readDelay,
                    self.videoBwLabel: self.videoBw,
                    self.startFrequencyLabel: self.startFrequency,
                    self.stopFrequencyLabel: self.stopFrequency,
                },
            )
        )
        layout.addWidget(self.btnSetConfig)
        self.setLayout(layout)

    def set_config(self):
        self.config_thread = SetConfigSpectrumThread(
            cid=self.cid,
            video_bw=self.videoBw.value(),
            start_frequency=self.startFrequency.value() * 1e9,
            stop_frequency=self.stopFrequency.value() * 1e9,
            delay=self.readDelay.value(),
        )
        self.config_thread.start()
        self.btnSetConfig.setEnabled(False)
        self.config_thread.finished.connect(lambda: self.btnSetConfig.setEnabled(True))
