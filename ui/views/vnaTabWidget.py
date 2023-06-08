import time
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QSizePolicy,
)

from config import config
from interactors.block import Block
from interactors.vna import VNABlock
from ui.components import CustomQDoubleSpinBox
from ui.windows.vnaGraphWindow import VNAGraphWindow
from utils.functions import to_db
from utils.logger import logger


class BiasReflectionWorker(QObject):
    finished = pyqtSignal()
    results = pyqtSignal(dict)
    progress = pyqtSignal(float)

    def run(self):
        vna = VNABlock(vna_ip=config.VNA_ADDRESS)
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()

        frequencies = np.linspace(
            config.VNA_FREQ_FROM, config.VNA_FREQ_TO, config.VNA_POINTS
        )

        results = {
            "i_get": [],
            "v_set": [],
            "v_get": [],
            "refl": defaultdict(np.ndarray),
            "frequencies": frequencies,
            "time": [],
        }
        initial_v = block.get_bias_voltage()
        v_range = np.linspace(
            config.BIAS_REFL_VOLT_FROM * 1e-3,
            config.BIAS_REFL_VOLT_TO * 1e-3,
            config.BIAS_REFL_VOLT_POINTS,
        )
        start_t = datetime.now()
        for i, v_set in enumerate(v_range, 1):
            if not config.BIAS_REFL_THREAD:
                break
            proc = round((i / config.BIAS_REFL_VOLT_POINTS) * 100, 2)
            block.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            v_get = block.get_bias_voltage()
            if not v_get:
                continue
            i_get = block.get_bias_current()
            if not i_get:
                continue
            time.sleep(config.BIAS_REFL_DELAY)  # waiting for VNA averaging
            refl = vna.get_reflection()
            results["v_get"].append(v_get * 1e3)
            results["v_set"].append(v_set * 1e3)
            results["i_get"].append(i_get * 1e6)
            results["refl"][f"{v_get * 1e3};{i_get * 1e6}"] = refl
            delta_t = datetime.now() - start_t
            results["time"].append(delta_t)
            logger.info(
                f"[scan_reflection] Proc {proc} %; Time {delta_t}; V_set {v_set * 1e3}"
            )
            self.progress.emit(proc)

        block.set_bias_voltage(initial_v)
        block.disconnect()

        self.results.emit(results)
        self.finished.emit()


class VNAGetReflectionWorker(QObject):
    finished = pyqtSignal()
    reflection = pyqtSignal(list)

    def run(self):
        vna = VNABlock(vna_ip=config.VNA_ADDRESS)
        reflection = vna.get_reflection()
        reflection_db = list(to_db(reflection))
        self.reflection.emit(reflection_db)
        self.finished.emit()


class VNATabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.vnaGraphWindow = None
        self.createGroupVNAParameters()
        self.createGroupBiasReflScan()
        self.layout.addWidget(
            self.groupVNAParameters, alignment=Qt.AlignmentFlag.AlignTop
        )
        self.layout.addWidget(
            self.groupBiasReflScan, alignment=Qt.AlignmentFlag.AlignTop
        )
        self.setLayout(self.layout)

    def createGroupVNAParameters(self):
        self.groupVNAParameters = QGroupBox("VNA parameters")
        self.groupVNAParameters.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.freqFromLabel = QLabel(self)
        self.freqFromLabel.setText("Freq from, GHz:")
        self.freqFrom = CustomQDoubleSpinBox(self)
        self.freqFrom.setValue(config.VNA_FREQ_FROM)

        self.freqToLabel = QLabel(self)
        self.freqToLabel.setText("Freq to, GHz:")
        self.freqTo = CustomQDoubleSpinBox(self)
        self.freqTo.setValue(config.VNA_FREQ_TO)

        self.vnaPointsLabel = QLabel(self)
        self.vnaPointsLabel.setText("Points count:")
        self.vnaPoints = CustomQDoubleSpinBox(self)
        self.vnaPoints.setMaximum(config.VNA_POINTS_MAX)
        self.vnaPoints.setDecimals(0)
        self.vnaPoints.setValue(config.VNA_POINTS)

        self.vnaPowerLabel = QLabel(self)
        self.vnaPowerLabel.setText("Power, dB:")
        self.vnaPower = CustomQDoubleSpinBox(self)
        self.vnaPower.setRange(config.VNA_POWER_MIN, config.VNA_POWER_MAX)
        self.vnaPower.setValue(config.VNA_POWER)

        self.btnGetReflection = QPushButton("Get reflection")
        self.btnGetReflection.clicked.connect(self.getReflection)

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
        self.groupBiasReflScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.voltFromLabel = QLabel(self)
        self.voltFromLabel.setText("Bias voltage from, mV")
        self.voltFrom = CustomQDoubleSpinBox(self)
        self.voltFrom.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltToLabel = QLabel(self)
        self.voltToLabel.setText("Bias voltage to, mV")
        self.voltTo = CustomQDoubleSpinBox(self)
        self.voltTo.setRange(
            config.BLOCK_BIAS_VOLT_MIN_VALUE, config.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltPointsLabel = QLabel(self)
        self.voltPointsLabel.setText("Points count")
        self.voltPoints = CustomQDoubleSpinBox(self)
        self.voltPoints.setMaximum(config.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(config.BLOCK_BIAS_VOLT_POINTS)

        self.scanStepDelayLabel = QLabel("Scan delay, s")
        self.scanStepDelay = CustomQDoubleSpinBox(self)
        self.scanStepDelay.setRange(0, 10)
        self.scanStepDelay.setValue(config.BIAS_REFL_DELAY)

        self.scanProgressLabel = QLabel("Progress")
        self.scanProgress = QLabel("0 %")

        self.btnBiasReflScan = QPushButton("Scan Bias Reflection")
        self.btnBiasReflScan.clicked.connect(self.scan_bias_reflection)
        self.btnStopBiasReflScan = QPushButton("Stop Scan")
        self.btnStopBiasReflScan.clicked.connect(self.stop_scan_bias_reflection)

        layout.addWidget(self.voltFromLabel, 1, 0)
        layout.addWidget(self.voltFrom, 1, 1)
        layout.addWidget(self.voltToLabel, 2, 0)
        layout.addWidget(self.voltTo, 2, 1)
        layout.addWidget(self.voltPointsLabel, 3, 0)
        layout.addWidget(self.voltPoints, 3, 1)
        layout.addWidget(self.scanStepDelayLabel, 4, 0)
        layout.addWidget(self.scanStepDelay, 4, 1)
        layout.addWidget(self.scanProgressLabel, 5, 0)
        layout.addWidget(self.scanProgress, 5, 1)
        layout.addWidget(self.btnBiasReflScan, 6, 0)
        layout.addWidget(self.btnStopBiasReflScan, 6, 1)

        self.groupBiasReflScan.setLayout(layout)

    def update_vna_params(self):
        config.VNA_POWER = self.vnaPower.value()
        config.VNA_POINTS = int(self.vnaPoints.value())
        config.VNA_FREQ_FROM = self.freqFrom.value() * 1e9
        config.VNA_FREQ_TO = self.freqTo.value() * 1e9

    def getReflection(self):
        self.vna_get_reflection_thread = QThread()
        self.vna_get_reflection_worker = VNAGetReflectionWorker()

        self.update_vna_params()

        self.vna_get_reflection_worker.moveToThread(self.vna_get_reflection_thread)
        self.vna_get_reflection_thread.started.connect(
            self.vna_get_reflection_worker.run
        )
        self.vna_get_reflection_worker.finished.connect(
            self.vna_get_reflection_thread.quit
        )
        self.vna_get_reflection_worker.finished.connect(
            self.vna_get_reflection_worker.deleteLater
        )
        self.vna_get_reflection_thread.finished.connect(
            self.vna_get_reflection_thread.deleteLater
        )
        self.vna_get_reflection_worker.reflection.connect(self.plotReflection)
        self.vna_get_reflection_thread.start()

        self.btnGetReflection.setEnabled(False)
        self.vna_get_reflection_thread.finished.connect(
            lambda: self.btnGetReflection.setEnabled(True)
        )

    def plotReflection(self, reflection):
        freq_list = np.linspace(
            config.VNA_FREQ_FROM, config.VNA_FREQ_TO, config.VNA_POINTS
        )
        if self.vnaGraphWindow is None:
            self.vnaGraphWindow = VNAGraphWindow()
        self.vnaGraphWindow.plotNew(x=freq_list, y=reflection)
        self.vnaGraphWindow.show()

    def scan_bias_reflection(self):
        self.bias_reflection_thread = QThread()
        self.bias_reflection_worker = BiasReflectionWorker()

        self.update_vna_params()
        config.BIAS_REFL_THREAD = True
        config.BIAS_REFL_VOLT_FROM = self.voltFrom.value()
        config.BIAS_REFL_VOLT_TO = self.voltTo.value()
        config.BIAS_REFL_VOLT_POINTS = int(self.voltPoints.value())
        config.BIAS_REFL_DELAY = self.scanStepDelay.value()

        self.bias_reflection_worker.moveToThread(self.bias_reflection_thread)
        self.bias_reflection_thread.started.connect(self.bias_reflection_worker.run)
        self.bias_reflection_worker.finished.connect(self.bias_reflection_thread.quit)
        self.bias_reflection_worker.finished.connect(
            self.bias_reflection_worker.deleteLater
        )
        self.bias_reflection_thread.finished.connect(
            self.bias_reflection_thread.deleteLater
        )
        self.bias_reflection_worker.results.connect(self.save_bias_reflection)
        self.bias_reflection_worker.progress.connect(self.set_bias_reflection_progress)
        self.bias_reflection_thread.start()

        self.btnBiasReflScan.setEnabled(False)
        self.bias_reflection_thread.finished.connect(
            lambda: self.btnBiasReflScan.setEnabled(True)
        )

    def stop_scan_bias_reflection(self):
        config.BIAS_REFL_THREAD = False

    def save_bias_reflection(self, data):
        try:
            refl_filepath = QFileDialog.getSaveFileName(filter="*.csv")[0]
            refl_df = pd.DataFrame(data["refl"], index=data["frequencies"])
            refl_df.to_csv(refl_filepath)

            iv_filepath = QFileDialog.getSaveFileName(filter="*.csv")[0]
            iv_df = pd.DataFrame(
                dict(
                    v_set=data["v_set"],
                    v_get=data["v_get"],
                    i_get=data["i_get"],
                    time=data["time"],
                )
            )
            iv_df.to_csv(iv_filepath)
        except (IndexError, FileNotFoundError):
            pass
        self.scanProgress.setText(f"0 %")

    def set_bias_reflection_progress(self, progress):
        self.scanProgress.setText(f"{progress} %")
