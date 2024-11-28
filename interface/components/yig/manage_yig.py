import logging
from typing import Literal

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QFormLayout, QLabel, QGroupBox

from api.NationalInstruments.yig_filter import YigType, NiYIGManager
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store.state import state
from threads import Thread


logger = logging.getLogger(__name__)


class DigitalYigThread(Thread):
    response = pyqtSignal(str)

    def __init__(self, yig: Literal["yig_1", "yig_2"] = "yig_1"):
        super().__init__()
        self.yig = yig

    def run(self):
        ni_yig = NiYIGManager(host=state.NI_IP)
        resp = ni_yig.set_frequency(state.DIGITAL_YIG_FREQ.value * 1e9, yig=self.yig)
        if resp is None:
            self.response.emit("Unable to set frequency")
        else:
            state.DIGITAL_YIG_FREQ.value = resp
        logger.info(f"[setNiYigFreq] {resp}")


class ManageYigWidget(QGroupBox):
    def __init__(self, parent, yig: YigType):
        super().__init__(parent)
        self.yig = yig
        self.set_digital_yig_freq_thread = None
        self.setTitle(f"Digital (NI) {yig}")
        layout = QFormLayout()

        self.niYigFreqLabel = QLabel(self)
        self.niYigFreqLabel.setText("Freq, GHz")
        self.niYigFreq = DoubleSpinBox(self)
        self.niYigFreq.setRange(2.94, 13)
        self.niYigFreq.setValue(8)

        self.niDigitalResponseLabel = QLabel(self)
        self.niDigitalResponseLabel.setText("Actual:")
        self.niDigitalResponse = QLabel(self)
        self.niDigitalResponse.setText("Unknown")
        state.DIGITAL_YIG_FREQ.signal_value.connect(
            lambda x: self.niDigitalResponse.setText(f"{x} GHz")
        )

        self.btnSetNiYigFreq = Button("Set frequency", animate=True)
        self.btnSetNiYigFreq.clicked.connect(self.set_ni_yig_freq)

        layout.addRow(self.niDigitalResponseLabel, self.niDigitalResponse)
        layout.addRow(self.niYigFreqLabel, self.niYigFreq)
        layout.addRow(self.btnSetNiYigFreq)

        self.setLayout(layout)

    def set_ni_yig_freq(self):
        if self.set_digital_yig_freq_thread is None:
            self.set_digital_yig_freq_thread = DigitalYigThread(yig=self.yig)

        state.DIGITAL_YIG_FREQ.value = self.niYigFreq.value()
        self.set_digital_yig_freq_thread.finished.connect(
            lambda: self.btnSetNiYigFreq.setEnabled(True)
        )
        self.set_digital_yig_freq_thread.response.connect(
            lambda x: self.niDigitalResponse.setText(f"{x}")
        )
        self.set_digital_yig_freq_thread.start()
        self.btnSetNiYigFreq.setEnabled(False)
