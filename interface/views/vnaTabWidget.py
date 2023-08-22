import time
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd
from PyQt6.QtCore import pyqtSignal, QThread
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

from store.base import MeasureModel, MeasureType
from store.state import state
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.vna import VNABlock
from interface.components.DoubleSpinBox import DoubleSpinBox
from interface.windows.vnaGraphWindow import VNAGraphWindow
from utils.functions import to_db
from utils.logger import logger


class BiasReflectionThread(QThread):
    results = pyqtSignal(dict)
    progress = pyqtSignal(float)

    def run(self):
        vna = VNABlock(vna_ip=state.VNA_ADDRESS)
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()

        frequencies = np.linspace(
            state.VNA_FREQ_FROM, state.VNA_FREQ_TO, state.VNA_POINTS
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
            state.BIAS_REFL_VOLT_FROM * 1e-3,
            state.BIAS_REFL_VOLT_TO * 1e-3,
            state.BIAS_REFL_VOLT_POINTS,
        )
        measure = MeasureModel.objects.create(
            measure_type=MeasureType.BIAS_VNA, data={}
        )
        start_t = datetime.now()
        for i, v_set in enumerate(v_range, 1):
            if not state.BIAS_REFL_SCAN_THREAD:
                break
            proc = round((i / state.BIAS_REFL_VOLT_POINTS) * 100, 2)
            block.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            v_get = block.get_bias_voltage()
            if not v_get:
                continue
            i_get = block.get_bias_current()
            if not i_get:
                continue
            time.sleep(state.BIAS_REFL_DELAY)  # waiting for VNA averaging
            refl = vna.get_reflection()
            results["v_get"].append(v_get * 1e3)
            results["v_set"].append(v_set * 1e3)
            results["i_get"].append(i_get * 1e6)
            results["refl"][f"{v_get * 1e3};{i_get * 1e6}"] = refl
            delta_t = datetime.now() - start_t
            results["time"].append(delta_t.total_seconds())
            logger.info(
                f"[scan_reflection] Proc {proc} %; Time {delta_t}; V_set {v_set * 1e3}"
            )
            measure.data = results
            self.progress.emit(proc)

        block.set_bias_voltage(initial_v)
        block.disconnect()
        measure.finished = datetime.now()
        measure.save()
        self.results.emit(results)
        self.finished.emit()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")
        state.BIAS_REFL_SCAN_THREAD = False

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")
        state.BIAS_REFL_SCAN_THREAD = False

    def quit(
        self,
    ):
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")
        state.BIAS_REFL_SCAN_THREAD = False


class VNAGetReflectionThread(QThread):
    reflection = pyqtSignal(list)

    def run(self):
        vna = VNABlock(vna_ip=state.VNA_ADDRESS)
        reflection = vna.get_reflection()
        reflection_db = list(to_db(reflection))
        self.reflection.emit(reflection_db)
        self.finished.emit()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")

    def quit(
        self,
    ):
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")


class VNATabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.vnaGraphWindow = None
        self.createGroupVNAParameters()
        self.createGroupBiasReflScan()
        self.layout.addWidget(self.groupVNAParameters)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupBiasReflScan)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupVNAParameters(self):
        self.groupVNAParameters = QGroupBox("VNA parameters")
        self.groupVNAParameters.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.freqFromLabel = QLabel(self)
        self.freqFromLabel.setText("Freq from, GHz:")
        self.freqFrom = DoubleSpinBox(self)
        self.freqFrom.setValue(state.VNA_FREQ_FROM)

        self.freqToLabel = QLabel(self)
        self.freqToLabel.setText("Freq to, GHz:")
        self.freqTo = DoubleSpinBox(self)
        self.freqTo.setValue(state.VNA_FREQ_TO)

        self.vnaPointsLabel = QLabel(self)
        self.vnaPointsLabel.setText("Points count:")
        self.vnaPoints = DoubleSpinBox(self)
        self.vnaPoints.setMaximum(state.VNA_POINTS_MAX)
        self.vnaPoints.setDecimals(0)
        self.vnaPoints.setValue(state.VNA_POINTS)

        self.vnaPowerLabel = QLabel(self)
        self.vnaPowerLabel.setText("Power, dB:")
        self.vnaPower = DoubleSpinBox(self)
        self.vnaPower.setRange(state.VNA_POWER_MIN, state.VNA_POWER_MAX)
        self.vnaPower.setValue(state.VNA_POWER)

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
        self.voltFrom = DoubleSpinBox(self)
        self.voltFrom.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltToLabel = QLabel(self)
        self.voltToLabel.setText("Bias voltage to, mV")
        self.voltTo = DoubleSpinBox(self)
        self.voltTo.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltPointsLabel = QLabel(self)
        self.voltPointsLabel.setText("Points count")
        self.voltPoints = DoubleSpinBox(self)
        self.voltPoints.setMaximum(state.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(state.BLOCK_BIAS_VOLT_POINTS)

        self.scanStepDelayLabel = QLabel("Scan delay, s")
        self.scanStepDelay = DoubleSpinBox(self)
        self.scanStepDelay.setRange(0, 10)
        self.scanStepDelay.setValue(state.BIAS_REFL_DELAY)

        self.scanProgressLabel = QLabel("Progress")
        self.scanProgress = QLabel("0 %")

        self.btnBiasReflScan = QPushButton("Scan Bias Reflection")
        self.btnBiasReflScan.clicked.connect(self.scan_bias_reflection)
        self.btnStopBiasReflScan = QPushButton("Stop Scan")
        self.btnStopBiasReflScan.clicked.connect(self.stop_scan_bias_reflection)
        self.btnStopBiasReflScan.setEnabled(False)

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
        state.VNA_POWER = self.vnaPower.value()
        state.VNA_POINTS = int(self.vnaPoints.value())
        state.VNA_FREQ_FROM = self.freqFrom.value() * 1e9
        state.VNA_FREQ_TO = self.freqTo.value() * 1e9

    def getReflection(self):
        self.vna_get_reflection_thread = VNAGetReflectionThread()

        self.update_vna_params()

        self.vna_get_reflection_thread.reflection.connect(self.plotReflection)
        self.vna_get_reflection_thread.start()

        self.btnGetReflection.setEnabled(False)
        self.vna_get_reflection_thread.finished.connect(
            lambda: self.btnGetReflection.setEnabled(True)
        )

    def plotReflection(self, reflection):
        freq_list = np.linspace(
            state.VNA_FREQ_FROM, state.VNA_FREQ_TO, state.VNA_POINTS
        )
        if self.vnaGraphWindow is None:
            self.vnaGraphWindow = VNAGraphWindow()
        self.vnaGraphWindow.plotNew(x=freq_list, y=reflection)
        self.vnaGraphWindow.show()

    def scan_bias_reflection(self):
        self.bias_reflection_thread = BiasReflectionThread()

        self.update_vna_params()
        state.BIAS_REFL_SCAN_THREAD = True
        state.BIAS_REFL_VOLT_FROM = self.voltFrom.value()
        state.BIAS_REFL_VOLT_TO = self.voltTo.value()
        state.BIAS_REFL_VOLT_POINTS = int(self.voltPoints.value())
        state.BIAS_REFL_DELAY = self.scanStepDelay.value()

        self.bias_reflection_thread.progress.connect(self.set_bias_reflection_progress)
        self.bias_reflection_thread.start()

        self.btnBiasReflScan.setEnabled(False)
        self.bias_reflection_thread.finished.connect(
            lambda: self.btnBiasReflScan.setEnabled(True)
        )
        self.btnStopBiasReflScan.setEnabled(True)
        self.bias_reflection_thread.finished.connect(
            lambda: self.btnStopBiasReflScan.setEnabled(False)
        )

    def stop_scan_bias_reflection(self):
        self.bias_reflection_thread.quit()
        self.bias_reflection_thread.exit(0)

    def set_bias_reflection_progress(self, progress):
        self.scanProgress.setText(f"{progress} %")
