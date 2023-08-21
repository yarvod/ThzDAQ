from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QGroupBox,
    QLabel,
    QPushButton,
    QGridLayout,
    QComboBox,
)

from api.Agilent.signal_generator import SignalGenerator
from interface.components import CustomQDoubleSpinBox
from state import state


class SignalGeneratorTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.createGroupSignalGeneratorConfig()
        self.createGroupSignalGenerator()
        self.layout.addWidget(self.groupSignalGeneratorConfig)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupSignalGenerator)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupSignalGeneratorConfig(self):
        self.groupSignalGeneratorConfig = QGroupBox("Config")
        layout = QGridLayout()

        self.OemStatusLabel = QLabel(self)
        self.OemStatusLabel.setText("OEM Status:")
        self.OemStatus = QComboBox(self)
        self.OemStatus.addItems(["OFF", "ON"])

        self.OemFrequencyStartLabel = QLabel(self)
        self.OemFrequencyStartLabel.setText("Frequency Start, GHz")
        self.OemFrequencyStart = CustomQDoubleSpinBox(self)
        self.OemFrequencyStart.setRange(200, 350)
        self.OemFrequencyStart.setValue(219.6)

        self.OemFrequencyStopLabel = QLabel(self)
        self.OemFrequencyStopLabel.setText("Frequency Stop, GHz")
        self.OemFrequencyStop = CustomQDoubleSpinBox(self)
        self.OemFrequencyStop.setRange(200, 350)
        self.OemFrequencyStop.setValue(325.8)

        self.OemMultiplierLabel = QLabel(self)
        self.OemMultiplierLabel.setText("OEM multiplier")
        self.OemMultiplier = CustomQDoubleSpinBox(self)
        self.OemMultiplier.setRange(1, 40)
        self.OemMultiplier.setValue(18)

        self.btnApplyConfig = QPushButton("Apply")
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

        self.groupSignalGeneratorConfig.setLayout(layout)

    def apply_config(self):
        agilent = SignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_oem_status(self.OemStatus.currentText())
        agilent.set_oem_frequency_start(self.OemFrequencyStart.value() * 1e9)
        agilent.set_oem_frequency_stop(self.OemFrequencyStop.value() * 1e9)
        agilent.set_oem_multiplier(self.OemMultiplier.value())

    def createGroupSignalGenerator(self):
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
        agilent = SignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_frequency(state.AGILENT_SIGNAL_GENERATOR_FREQUENCY * 1e9)

    def set_amplitude(self):
        state.AGILENT_SIGNAL_GENERATOR_AMPLITUDE = self.amplitude.value()
        agilent = SignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_amplitude(state.AGILENT_SIGNAL_GENERATOR_AMPLITUDE)
