from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QGridLayout,
    QComboBox,
    QCheckBox,
)

from api.Agilent.signal_generator import SignalGenerator
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.ui.Lines import HLine
from store.state import state


class SignalGeneratorTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
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

        self.groupSignalGeneratorConfig.setLayout(layout)

    def apply_config(self):
        agilent = SignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_oem_status(self.OemStatus.currentText())
        agilent.set_oem_frequency_start(self.OemFrequencyStart.value() * 1e9)
        agilent.set_oem_frequency_stop(self.OemFrequencyStop.value() * 1e9)
        agilent.set_oem_multiplier(self.OemMultiplier.value())

    def createGroupSignalGenerator(self):
        self.groupSignalGenerator = QGroupBox("Signal Generator")
        layout = QVBoxLayout()
        grid_layout = QGridLayout()

        self.rfOutputLabel = QLabel(self)
        self.rfOutputLabel.setText("RF Output:")
        self.rfOutput = QComboBox(self)
        self.rfOutput.addItems(["RF OFF", "RF ON"])
        self.btnRfOutput = Button("Set RF Output")
        self.btnRfOutput.clicked.connect(self.set_rf_output)

        self.instantUpdateFrequency = QCheckBox(self)
        self.instantUpdateFrequency.setText("Instant frequency set")
        self.frequencyLabel = QLabel(self)
        self.frequencyLabel.setText("Frequency, GHz")
        self.frequency = DoubleSpinBox(self)
        self.frequency.setRange(1, 300)
        self.frequency.setValue(14)
        self.frequency.valueChanged.connect(self.update_stream_frequency)
        self.btnSetFrequency = Button("Set frequency")
        self.btnSetFrequency.clicked.connect(self.set_frequency)

        self.amplitudeLabel = QLabel(self)
        self.amplitudeLabel.setText("Amplitude, dBm")
        self.amplitude = DoubleSpinBox(self)
        self.amplitude.setRange(-90, 15)
        self.amplitude.setValue(-20)
        self.btnSetAmplitude = Button("Set amplitude")
        self.btnSetAmplitude.clicked.connect(self.set_amplitude)

        grid_layout.addWidget(self.rfOutputLabel, 0, 0)
        grid_layout.addWidget(self.rfOutput, 0, 1)
        grid_layout.addWidget(self.btnRfOutput, 0, 2)
        grid_layout.addWidget(HLine(self), 1, 0, 1, 3)
        grid_layout.addWidget(self.instantUpdateFrequency, 2, 0)
        grid_layout.addWidget(self.frequencyLabel, 3, 0)
        grid_layout.addWidget(self.frequency, 3, 1)
        grid_layout.addWidget(self.btnSetFrequency, 3, 2)
        grid_layout.addWidget(HLine(self), 4, 0, 1, 3)
        grid_layout.addWidget(self.amplitudeLabel, 5, 0)
        grid_layout.addWidget(self.amplitude, 5, 1)
        grid_layout.addWidget(self.btnSetAmplitude, 5, 2)
        layout.addLayout(grid_layout)

        self.groupSignalGenerator.setLayout(layout)

    def set_frequency(self):
        state.AGILENT_SIGNAL_GENERATOR_FREQUENCY = self.frequency.value()
        agilent = SignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_frequency(state.AGILENT_SIGNAL_GENERATOR_FREQUENCY * 1e9)

    def set_amplitude(self):
        state.AGILENT_SIGNAL_GENERATOR_AMPLITUDE = self.amplitude.value()
        agilent = SignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_amplitude(state.AGILENT_SIGNAL_GENERATOR_AMPLITUDE)

    def set_rf_output(self):
        state.AGILENT_SIGNAL_GENERATOR_OUTPUT = self.rfOutput.currentIndex() == 1
        agilent = SignalGenerator(host=state.PROLOGIX_IP)
        agilent.set_rf_output_state(state.AGILENT_SIGNAL_GENERATOR_OUTPUT)

    def update_stream_frequency(self):
        if self.instantUpdateFrequency.isChecked():
            self.set_frequency()
