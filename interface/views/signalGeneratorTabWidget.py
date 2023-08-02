from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QGroupBox,
    QLabel,
    QPushButton,
    QGridLayout,
)

from api.agilent_signal_generator import AgilentSignalGenerator
from interface.components import CustomQDoubleSpinBox
from state import state


class SignalGeneratorTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.createGroupSignalGanarator()
        self.layout.addWidget(self.groupSignalGenerator)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupSignalGanarator(self):
        self.groupSignalGenerator = QGroupBox("Signal Generator")
        layout = QGridLayout()

        self.frequencyLabel = QLabel(self)
        self.frequencyLabel.setText("Frequency, GHz")
        self.frequency = CustomQDoubleSpinBox(self)
        self.frequency.setRange(1, 50)
        self.frequency.setValue(14)
        self.btnSetFrequency = QPushButton("Set frequency")
        self.btnSetFrequency.clicked.connect(self.set_frequency)

        self.amplitudeLabel = QLabel(self)
        self.amplitudeLabel.setText("Amplitude, dBm")
        self.amplitude = CustomQDoubleSpinBox(self)
        self.amplitude.setRange(-90, 4)
        self.amplitude.setValue(-20)
        self.btnSetAmplitude = QPushButton("Set amplitude")
        self.btnSetAmplitude.clicked.connect(self.set_amplitude)

        layout.addWidget(self.frequencyLabel, 1, 0)
        layout.addWidget(self.frequency, 1, 1)
        layout.addWidget(self.btnSetFrequency, 1, 2)
        layout.addWidget(self.amplitudeLabel, 2, 0)
        layout.addWidget(self.amplitude, 2, 1)
        layout.addWidget(self.btnSetAmplitude, 2, 2)

        self.groupSignalGenerator.setLayout(layout)

    def set_frequency(self):
        state.AGILENT_SIGNAL_GENERATOR_FREQUENCY = self.frequency.value()
        agilent = AgilentSignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_frequency(state.AGILENT_SIGNAL_GENERATOR_FREQUENCY * 1e9)

    def set_amplitude(self):
        state.AGILENT_SIGNAL_GENERATOR_AMPLITUDE = self.amplitude.value()
        agilent = AgilentSignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_amplitude(state.AGILENT_SIGNAL_GENERATOR_AMPLITUDE)
