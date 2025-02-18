from PySide6.QtWidgets import QGroupBox, QGridLayout, QLabel, QComboBox

from api.Agilent.signal_generator import SignalGenerator
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store import AgilentSignalGeneratorManager
from threads import Thread
from utils.exceptions import DeviceConnectionError


class ThreadSetConfig(Thread):
    def __init__(
        self,
        cid,
        oem_status,
        oem_freq_start,
        oem_freq_stop,
        oem_multiplier,
    ):
        super().__init__()
        self.config = AgilentSignalGeneratorManager.get_config(cid=cid)
        self.agilent = None
        self.oem_status = oem_status
        self.oem_freq_start = oem_freq_start
        self.oem_freq_stop = oem_freq_stop
        self.oem_multiplier = oem_multiplier

    def run(self) -> None:
        try:
            self.agilent = SignalGenerator(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return
        self.agilent.set_oem_status(self.oem_status)
        self.agilent.set_oem_frequency_start(self.oem_freq_start * 1e9)
        self.agilent.set_oem_frequency_stop(self.oem_freq_stop * 1e9)
        self.agilent.set_oem_multiplier(self.oem_multiplier)

        self.pre_exit()
        self.finished.emit()


class AgilentSignalGeneratorConfigWidget(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.setTitle("OEM Config")
        self.cid = cid
        self.thread_config = None

        layout = QGridLayout()

        self.OemStatusLabel = QLabel(self)
        self.OemStatusLabel.setText("OEM Status:")
        self.OemStatus = QComboBox(self)
        self.OemStatus.addItems(["OFF", "ON"])

        self.OemFrequencyStartLabel = QLabel(self)
        self.OemFrequencyStartLabel.setText("Frequency Start, GHz")
        self.OemFrequencyStart = DoubleSpinBox(self)
        self.OemFrequencyStart.setRange(200, 350)
        self.OemFrequencyStart.setValue(219.6)

        self.OemFrequencyStopLabel = QLabel(self)
        self.OemFrequencyStopLabel.setText("Frequency Stop, GHz")
        self.OemFrequencyStop = DoubleSpinBox(self)
        self.OemFrequencyStop.setRange(200, 350)
        self.OemFrequencyStop.setValue(325.8)

        self.OemMultiplierLabel = QLabel(self)
        self.OemMultiplierLabel.setText("OEM multiplier")
        self.OemMultiplier = DoubleSpinBox(self)
        self.OemMultiplier.setRange(1, 40)
        self.OemMultiplier.setValue(18)

        self.btnApplyConfig = Button("Apply", animate=True)
        self.btnApplyConfig.clicked.connect(self.apply_config)

        layout.addWidget(self.OemStatusLabel, 1, 0)
        layout.addWidget(self.OemStatus, 1, 1)
        layout.addWidget(self.OemFrequencyStartLabel, 2, 0)
        layout.addWidget(self.OemFrequencyStart, 2, 1)
        layout.addWidget(self.OemFrequencyStopLabel, 3, 0)
        layout.addWidget(self.OemFrequencyStop, 3, 1)
        layout.addWidget(self.OemMultiplierLabel, 4, 0)
        layout.addWidget(self.OemMultiplier, 4, 1)
        layout.addWidget(self.btnApplyConfig, 5, 0, 1, 2)

        self.setLayout(layout)

    def apply_config(self):
        config = AgilentSignalGeneratorManager.get_config(cid=self.cid)
        config.thread_set_config = True
        self.thread_config = ThreadSetConfig(
            cid=self.cid,
            oem_status=self.OemStatus.currentText(),
            oem_freq_start=self.OemFrequencyStart.value(),
            oem_freq_stop=self.OemFrequencyStop.value(),
            oem_multiplier=self.OemMultiplier.value(),
        )
        self.btnApplyConfig.setEnabled(False)
        self.thread_config.finished.connect(
            lambda: self.btnApplyConfig.setEnabled(True)
        )
        self.thread_config.start()
