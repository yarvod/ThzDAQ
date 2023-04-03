import numpy as np
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QDoubleSpinBox,
    QPushButton,
)

from config import (
    VNA_POINTS,
    VNA_FREQ_FROM,
    VNA_FREQ_TO,
    BLOCK_BIAS_VOLT_MIN_VALUE,
    BLOCK_BIAS_VOLT_MAX_VALUE,
    BLOCK_BIAS_VOLT_POINTS,
    BLOCK_BIAS_VOLT_POINTS_MAX,
    VNA_POINTS_MAX,
    VNA_POWER,
    VNA_POWER_MAX,
    VNA_POWER_MIN,
)
from interactors.vna import VNABlock
from ui.windows.vnaGraphWindow import VNAGraphWindow
from utils.functions import to_db


class UtilsMixin:
    @property
    def vna(self):
        return VNABlock()

    def vna_set_start_frequency(self):
        self.vna.set_start_frequency(self.freqFrom.value() * 1e9)

    def vna_set_stop_frequency(self):
        self.vna.set_stop_frequency(self.freqTo.value() * 1e9)

    def vna_set_sweep(self):
        self.vna.set_sweep(int(self.vnaPoints.value()))

    def vna_set_power(self):
        self.vna.set_power(self.vnaPower.value())

    def vna_update(self):
        self.vna_set_start_frequency()
        self.vna_set_stop_frequency()
        self.vna_set_sweep()
        self.vna_set_power()

    def scan_bias_refl(self):
        ...

    def get_reflection(self):
        self.vna_update()
        reflection = self.vna.get_reflection()
        reflection_db = to_db(reflection)
        return reflection_db


class VNATabWidget(QWidget, UtilsMixin):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.vnaGraphWindow = None
        self.createGroupVNAParameters()
        self.createGroupBiasReflScan()
        self.layout.addWidget(self.groupVNAParameters)
        self.layout.addWidget(self.groupBiasReflScan)
        self.setLayout(self.layout)

    # def show_graph_window(self, x: list, y: list):
    #     self.graphWindow = GraphWindow(x=x, y=y)
    #     self.graphWindow.show()

    def createGroupVNAParameters(self):
        self.groupVNAParameters = QGroupBox("VNA parameters")
        layout = QGridLayout()

        self.freqFromLabel = QLabel(self)
        self.freqFromLabel.setText("Freq from, GHz:")
        self.freqFrom = QDoubleSpinBox(self)
        self.freqFrom.setValue(VNA_FREQ_FROM)

        self.freqToLabel = QLabel(self)
        self.freqToLabel.setText("Freq to, GHz:")
        self.freqTo = QDoubleSpinBox(self)
        self.freqTo.setValue(VNA_FREQ_TO)

        self.vnaPointsLabel = QLabel(self)
        self.vnaPointsLabel.setText("Points num:")
        self.vnaPoints = QDoubleSpinBox(self)
        self.vnaPoints.setMaximum(VNA_POINTS_MAX)
        self.vnaPoints.setDecimals(0)
        self.vnaPoints.setValue(VNA_POINTS)

        self.vnaPowerLabel = QLabel(self)
        self.vnaPowerLabel.setText("Power, dB:")
        self.vnaPower = QDoubleSpinBox(self)
        self.vnaPower.setRange(VNA_POWER_MIN, VNA_POWER_MAX)
        self.vnaPower.setValue(VNA_POWER)

        self.btnGetReflection = QPushButton("Get reflection")
        self.btnGetReflection.clicked.connect(self.plotReflection)

        layout.addWidget(self.freqFromLabel, 1, 0)
        layout.addWidget(self.freqFrom, 1, 1)
        layout.addWidget(self.freqToLabel, 2, 0)
        layout.addWidget(self.freqTo, 2, 1)
        layout.addWidget(self.vnaPointsLabel, 3, 0)
        layout.addWidget(self.vnaPoints, 3, 1)
        layout.addWidget(self.vnaPowerLabel, 4, 0)
        layout.addWidget(self.vnaPower, 4, 1)
        layout.addWidget(self.btnGetReflection, 5, 0, 1, 2)

        self.groupVNAParameters.setLayout(layout)

    def createGroupBiasReflScan(self):
        self.groupBiasReflScan = QGroupBox("Scan Bias Reflection")
        layout = QGridLayout()

        self.voltFromLabel = QLabel(self)
        self.voltFromLabel.setText("Bias voltage from, mV")
        self.voltFrom = QDoubleSpinBox(self)
        self.voltFrom.setRange(BLOCK_BIAS_VOLT_MIN_VALUE, BLOCK_BIAS_VOLT_MAX_VALUE)

        self.voltToLabel = QLabel(self)
        self.voltToLabel.setText("Bias voltage to, mV")
        self.voltTo = QDoubleSpinBox(self)
        self.voltTo.setRange(BLOCK_BIAS_VOLT_MIN_VALUE, BLOCK_BIAS_VOLT_MAX_VALUE)

        self.voltPointsLabel = QLabel(self)
        self.voltPointsLabel.setText("Points num")
        self.voltPoints = QDoubleSpinBox(self)
        self.voltPoints.setMaximum(BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(BLOCK_BIAS_VOLT_POINTS)

        self.btnBiasReflScan = QPushButton("Scan Bias Reflection")
        self.btnBiasReflScan.clicked.connect(lambda: self.scan_bias_refl())

        layout.addWidget(self.voltFromLabel, 1, 0)
        layout.addWidget(self.voltFrom, 1, 1)
        layout.addWidget(self.voltToLabel, 2, 0)
        layout.addWidget(self.voltTo, 2, 1)
        layout.addWidget(self.voltPointsLabel, 3, 0)
        layout.addWidget(self.voltPoints, 3, 1)
        layout.addWidget(self.btnBiasReflScan, 4, 0, 1, 2)

        self.groupBiasReflScan.setLayout(layout)

    def plotReflection(self):
        freq_list = np.linspace(
            self.freqFrom.value(), self.freqTo.value(), int(self.vnaPoints.value())
        )
        reflection = self.get_reflection()
        if self.vnaGraphWindow is None:
            self.vnaGraphWindow = VNAGraphWindow(x=freq_list, y=reflection)
        else:
            self.vnaGraphWindow.plotNew(x=freq_list, y=reflection)
        self.vnaGraphWindow.show()