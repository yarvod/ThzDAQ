import numpy as np
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QDoubleSpinBox,
    QPushButton,
    QFileDialog,
)

from config import config
from interactors.block import Block
from interactors.vna import VNABlock
from ui.windows.vnaGraphWindow import VNAGraphWindow
from utils.functions import to_db


class UtilsMixin:

    def __init__(self):
        self.vna = VNABlock()

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
        self.vna_update()
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        freqs = np.linspace(
            self.freqFrom.value() * 1e9,
            self.freqTo.value() * 1e9,
            int(self.vnaPoints.value()),
        )
        data = block.scan_reflection(
            v_from=self.voltFrom.value() * 1e-3,
            v_to=self.voltTo.value() * 1e-3,
            points_num=int(self.voltPoints.value()),
        )
        try:
            refl_filepath = QFileDialog.getSaveFileName()[0]
            refl_df = pd.DataFrame(data["refl"], index=freqs)
            refl_df.to_csv(refl_filepath)

            iv_filepath = QFileDialog.getSaveFileName()[0]
            iv_df = pd.DataFrame(
                dict(v_set=data["v_set"], v_get=data["v_get"], i_get=data["i_get"])
            )
            iv_df.to_csv(iv_filepath)
        except (IndexError, FileNotFoundError):
            pass

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

    def createGroupVNAParameters(self):
        self.groupVNAParameters = QGroupBox("VNA parameters")
        layout = QGridLayout()

        self.freqFromLabel = QLabel(self)
        self.freqFromLabel.setText("Freq from, GHz:")
        self.freqFrom = QDoubleSpinBox(self)
        self.freqFrom.setValue(config.VNA_FREQ_FROM)

        self.freqToLabel = QLabel(self)
        self.freqToLabel.setText("Freq to, GHz:")
        self.freqTo = QDoubleSpinBox(self)
        self.freqTo.setValue(config.VNA_FREQ_TO)

        self.vnaPointsLabel = QLabel(self)
        self.vnaPointsLabel.setText("Points num:")
        self.vnaPoints = QDoubleSpinBox(self)
        self.vnaPoints.setMaximum(config.VNA_POINTS_MAX)
        self.vnaPoints.setDecimals(0)
        self.vnaPoints.setValue(config.VNA_POINTS)

        self.vnaPowerLabel = QLabel(self)
        self.vnaPowerLabel.setText("Power, dB:")
        self.vnaPower = QDoubleSpinBox(self)
        self.vnaPower.setRange(config.VNA_POWER_MIN, config.VNA_POWER_MAX)
        self.vnaPower.setValue(config.VNA_POWER)

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
        self.voltFrom.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltToLabel = QLabel(self)
        self.voltToLabel.setText("Bias voltage to, mV")
        self.voltTo = QDoubleSpinBox(self)
        self.voltTo.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltPointsLabel = QLabel(self)
        self.voltPointsLabel.setText("Points num")
        self.voltPoints = QDoubleSpinBox(self)
        self.voltPoints.setMaximum(config.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(config.BLOCK_BIAS_VOLT_POINTS)

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
            self.vnaGraphWindow = VNAGraphWindow()
        self.vnaGraphWindow.plotNew(x=freq_list, y=reflection)
        self.vnaGraphWindow.show()
