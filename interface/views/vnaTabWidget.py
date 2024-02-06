import time
from datetime import datetime

import numpy as np
from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QFormLayout,
    QComboBox,
    QCheckBox,
    QProgressBar,
)

from interface.components.ui.Button import Button
from store.base import MeasureModel, MeasureType
from store.state import state
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.vna import VNABlock
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from threads import Thread
from utils.functions import to_db
from utils.logger import logger


class BiasReflectionThread(Thread):
    results = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def run(self):
        vna = VNABlock(
            host=state.VNA_ADDRESS,
            port=state.VNA_PORT,
            parameter=state.VNA_SPARAM,
            start=state.VNA_FREQ_START,
            stop=state.VNA_FREQ_STOP,
            power=state.VNA_POWER,
            points=state.VNA_POINTS,
            delay=1,
            timeout=3,
        )
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()

        frequencies = list(
            np.linspace(state.VNA_FREQ_START, state.VNA_FREQ_STOP, state.VNA_POINTS)
        )

        results = {
            "i_get": [],
            "v_set": [],
            "v_get": [],
            "refl": [],
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
        measure.save(False)
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
            vna_data = vna.get_data()
            vna_data.pop("array", None)
            vna_data.pop("freq", None)
            results["v_get"].append(v_get * 1e3)
            results["v_set"].append(v_set * 1e3)
            results["i_get"].append(i_get * 1e6)
            results["refl"].append(vna_data)
            delta_t = datetime.now() - start_t
            results["time"].append(delta_t.total_seconds())
            logger.info(
                f"[scan_reflection] Proc {proc} %; Time {delta_t}; V_set {v_set * 1e3}"
            )
            measure.data = results
            self.progress.emit(int(proc))

        block.set_bias_voltage(initial_v)
        block.disconnect()
        measure.save()
        self.results.emit(results)
        self.pre_exit()
        self.finished.emit()


class VNAGetReflectionThread(Thread):
    results = pyqtSignal(dict)

    def run(self):
        vna = VNABlock(
            host=state.VNA_ADDRESS,
            port=state.VNA_PORT,
            parameter=state.VNA_SPARAM,
            start=state.VNA_FREQ_START,
            stop=state.VNA_FREQ_STOP,
            power=state.VNA_POWER,
            points=state.VNA_POINTS,
            delay=1,
            timeout=3,
        )
        data = vna.get_data()
        results = {
            "reflection": list(to_db(data.pop("array", []))),
            "freq": data["freq"],
        }
        if state.VNA_STORE_DATA:
            measure = MeasureModel.objects.create(
                measure_type=MeasureType.VNA_REFLECTION,
                data=data,
                finished=datetime.now(),
            )
            measure.save()
            results["measure_id"] = measure.id
        self.results.emit(results)
        self.pre_exit()
        self.finished.emit()


class VNATabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
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
        layout = QFormLayout()

        self.vnaParameter = QComboBox(self)
        self.vnaParameter.addItems(state.VNA_SPARAMS)

        self.freqFromLabel = QLabel(self)
        self.freqFromLabel.setText("Freq start, GHz:")
        self.freqFrom = DoubleSpinBox(self)
        self.freqFrom.setValue(state.VNA_FREQ_START)

        self.freqToLabel = QLabel(self)
        self.freqToLabel.setText("Freq stop, GHz:")
        self.freqTo = DoubleSpinBox(self)
        self.freqTo.setValue(state.VNA_FREQ_STOP)

        self.vnaPointsLabel = QLabel(self)
        self.vnaPointsLabel.setText("Points count:")
        self.vnaPoints = QSpinBox(self)
        self.vnaPoints.setMaximum(state.VNA_POINTS_MAX)
        self.vnaPoints.setValue(state.VNA_POINTS)

        self.vnaPowerLabel = QLabel(self)
        self.vnaPowerLabel.setText("Power, dB:")
        self.vnaPower = DoubleSpinBox(self)
        self.vnaPower.setRange(state.VNA_POWER_MIN, state.VNA_POWER_MAX)
        self.vnaPower.setValue(state.VNA_POWER)

        self.vnaStoreData = QCheckBox(self)
        self.vnaStoreData.setText("Store Data")
        self.vnaStoreData.setChecked(state.VNA_STORE_DATA)

        self.btnGetReflection = Button("Get reflection", animate=True)
        self.btnGetReflection.clicked.connect(self.getReflection)

        layout.addRow("Parameter:", self.vnaParameter)
        layout.addRow(self.freqFromLabel, self.freqFrom)
        layout.addRow(self.freqToLabel, self.freqTo)
        layout.addRow(self.vnaPointsLabel, self.vnaPoints)
        layout.addRow(self.vnaPowerLabel, self.vnaPower)
        layout.addRow(self.vnaStoreData)
        layout.addRow(self.btnGetReflection)

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

        self.scanProgress = QProgressBar(self)
        self.scanProgress.setValue(0)

        self.btnBiasReflScan = Button("Scan Bias Reflection", animate=True)
        self.btnBiasReflScan.clicked.connect(self.scan_bias_reflection)
        self.btnStopBiasReflScan = Button("Stop Scan")
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
        layout.addWidget(self.scanProgress, 5, 0, 1, 2)
        layout.addWidget(self.btnBiasReflScan, 6, 0)
        layout.addWidget(self.btnStopBiasReflScan, 6, 1)

        self.groupBiasReflScan.setLayout(layout)

    def update_vna_params(self):
        state.VNA_STORE_DATA = self.vnaStoreData.isChecked()
        state.VNA_SPARAM = self.vnaParameter.currentText()
        state.VNA_POWER = self.vnaPower.value()
        state.VNA_POINTS = int(self.vnaPoints.value())
        state.VNA_FREQ_START = self.freqFrom.value() * 1e9
        state.VNA_FREQ_STOP = self.freqTo.value() * 1e9

    def getReflection(self):
        self.vna_get_reflection_thread = VNAGetReflectionThread()

        self.update_vna_params()

        self.vna_get_reflection_thread.results.connect(self.plotReflection)
        self.vna_get_reflection_thread.start()

        self.btnGetReflection.setEnabled(False)
        self.vna_get_reflection_thread.finished.connect(
            lambda: self.btnGetReflection.setEnabled(True)
        )

    def plotReflection(self, data):
        if self.vnaGraphWindow is None:
            return
        self.vnaGraphWindow.widget().plotNew(
            x=data.get("freq"),
            y=data.get("reflection"),
            measure_id=data.get("measure_id"),
        )
        self.vnaGraphWindow.widget().show()

    def scan_bias_reflection(self):
        self.bias_reflection_thread = BiasReflectionThread()

        self.update_vna_params()
        state.BIAS_REFL_SCAN_THREAD = True
        state.BIAS_REFL_VOLT_FROM = self.voltFrom.value()
        state.BIAS_REFL_VOLT_TO = self.voltTo.value()
        state.BIAS_REFL_VOLT_POINTS = int(self.voltPoints.value())
        state.BIAS_REFL_DELAY = self.scanStepDelay.value()

        self.bias_reflection_thread.progress.connect(
            lambda x: self.scanProgress.setValue(x)
        )
        self.bias_reflection_thread.finished.connect(
            lambda: self.scanProgress.setValue(0)
        )
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
        state.BIAS_REFL_SCAN_THREAD = False
