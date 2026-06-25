from PySide6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QCheckBox,
)

from api.Agilent.signal_generator import SignalGenerator
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.ui.Lines import HLine
from store import AgilentSignalGeneratorManager


class AgilentSignalGeneratorManagerWidget(QGroupBox):
    def __init__(self, parent, cid):
        super().__init__(parent)
        self.setTitle("Manager")
        self.cid = cid
        self.config = AgilentSignalGeneratorManager.get_config(self.cid)

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
        self.frequency.setRange(1, 1000)
        self.frequency.setValue(14)
        self.frequency.setDecimals(3)
        self.frequency.valueChanged.connect(self.update_stream_frequency)
        self.btnSetFrequency = Button("Set frequency")
        self.btnSetFrequency.clicked.connect(self.set_frequency)

        self.frequencyMultiplierLabel = QLabel(self)
        self.frequencyMultiplierLabel.setText("Frequency multiplier")
        self.frequencyMultiplier = DoubleSpinBox(self)
        self.frequencyMultiplier.setRange(0.001, 1000)
        self.frequencyMultiplier.setValue(1)
        self.frequencyMultiplier.setDecimals(3)
        self.btnSetFrequencyMultiplier = Button("Set multiplier")
        self.btnSetFrequencyMultiplier.clicked.connect(self.set_frequency_multiplier)

        self.amplitudeLabel = QLabel(self)
        self.amplitudeLabel.setText("Amplitude, dBm")
        self.amplitude = DoubleSpinBox(self)
        self.amplitude.setRange(-90, 25)
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
        grid_layout.addWidget(self.frequencyMultiplierLabel, 4, 0)
        grid_layout.addWidget(self.frequencyMultiplier, 4, 1)
        grid_layout.addWidget(self.btnSetFrequencyMultiplier, 4, 2)
        grid_layout.addWidget(HLine(self), 5, 0, 1, 3)
        grid_layout.addWidget(self.amplitudeLabel, 6, 0)
        grid_layout.addWidget(self.amplitude, 6, 1)
        grid_layout.addWidget(self.btnSetAmplitude, 6, 2)
        layout.addLayout(grid_layout)

        self.setLayout(layout)

    def set_frequency(self):
        freq = self.frequency.value()
        agilent = SignalGenerator(**self.config.dict())
        agilent.set_frequency(freq * 1e9)

    def set_frequency_multiplier(self):
        agilent = SignalGenerator(**self.config.dict())
        agilent.set_frequency_multiplier(self.frequencyMultiplier.value())

    def set_amplitude(self):
        agilent = SignalGenerator(**self.config.dict())
        agilent.set_power(self.amplitude.value())

    def set_rf_output(self):
        agilent = SignalGenerator(**self.config.dict())
        agilent.set_rf_output_state(self.rfOutput.currentIndex() == 1)

    def update_stream_frequency(self):
        if self.instantUpdateFrequency.isChecked():
            self.set_frequency()
