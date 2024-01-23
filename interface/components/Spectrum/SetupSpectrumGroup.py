from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QSpinBox,
    QFormLayout,
)

from api.RohdeSchwarz.spectrum_fsek30 import SpectrumBlock
from interface.components.ui.Button import Button
from store.state import state
from utils.exceptions import DeviceConnectionError


class SetUpSpectrumThread(QThread):
    status = pyqtSignal(bool)

    def run(self):
        try:
            block = SpectrumBlock(
                host=state.PROLOGIX_IP, gpib=state.SPECTRUM_GPIB_ADDRESS
            )
            result = block.tst()
            self.status.emit(result)
        except DeviceConnectionError:
            self.status.emit(False)


class SetupSpectrumGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Spectrum analyzer")
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.gpibAddressLabel = QLabel(self)
        self.gpibAddressLabel.setText("GPIB address:")
        self.gpibAddress = QSpinBox(self)
        self.gpibAddress.setRange(1, 31)
        self.gpibAddress.setValue(state.SPECTRUM_GPIB_ADDRESS)

        self.status = QLabel(self)
        self.status.setText("Doesn't initialized yet!")

        self.btnInitSpectrum = Button("Initialize", animate=True)
        self.btnInitSpectrum.clicked.connect(self.initialize_spectrum)

        form_layout.addRow(self.gpibAddressLabel, self.gpibAddress)
        form_layout.addRow("Status", self.status)
        form_layout.addRow(self.btnInitSpectrum)

        layout.addLayout(form_layout)
        self.setLayout(layout)

    def initialize_spectrum(self):
        state.SPECTRUM_GPIB_ADDRESS = self.gpibAddress.value()
        self.spectrum_thread = SetUpSpectrumThread()
        self.spectrum_thread.status.connect(self.set_spectrum_status)
        self.spectrum_thread.start()
        self.btnInitSpectrum.setEnabled(False)
        self.spectrum_thread.finished.connect(
            lambda: self.btnInitSpectrum.setEnabled(True)
        )

    def set_spectrum_status(self, status: bool = False):
        if status:
            self.status.setText("Ok")
        else:
            self.status.setText("Error!")
