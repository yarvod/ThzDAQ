import logging
import time
from datetime import datetime

import numpy as np
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QSizePolicy,
    QGroupBox,
    QSpinBox,
    QProgressBar,
    QFormLayout,
    QHBoxLayout,
    QComboBox,
)

from api import VNABlock
from api.Scontel.sis_block import SisBlock
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.ui.Lines import HLine
from store import RohdeSchwarzVnaZva67Manager, ScontelSisBlockManager
from store.base import MeasureModel
from store.state import state
from threads import Thread
from utils.exceptions import DeviceConnectionError


logger = logging.getLogger(__name__)


class BiasReflectionThread(Thread):
    progress = pyqtSignal(int)

    def __init__(
        self,
        cid_sis: int,
        cid_vna: int,
        start_frequency: float,
        stop_frequency: float,
        frequency_points: int,
        vna_power: float,
        vna_parameter: str,
        vna_samples_count: int,
        vna_average_count: int,
        start_voltage: float,
        stop_voltage: float,
        voltage_points: int,
        step_delay: float,
    ):
        super().__init__()
        self.cid_sis = cid_sis
        self.config_sis = ScontelSisBlockManager.get_config(cid_sis)
        self.cid_vna = cid_vna
        self.config_vna = RohdeSchwarzVnaZva67Manager.get_config(cid_vna)
        self.start_frequency = start_frequency
        self.stop_frequency = stop_frequency
        self.frequency_points = int(frequency_points)
        self.vna_power = vna_power
        self.vna_parameter = vna_parameter
        self.vna_samples_count = vna_samples_count
        self.vna_average_count = vna_average_count
        self.start_voltage = start_voltage
        self.stop_voltage = stop_voltage
        self.voltage_points = int(voltage_points)
        self.step_delay = step_delay
        self.vna = None
        self.block = None

        self.measure = MeasureModel.objects.create(
            measure_type=MeasureModel.type_class.SV_VNA,
            data={
                "i_get": [],
                "v_set": [],
                "v_get": [],
                "refl": [],
                "frequencies": [],
                "time": [],
            },
        )
        self.measure.save(False)

    def run(self):
        try:
            self.vna = VNABlock(**self.config_vna.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        try:
            self.block = SisBlock(**self.config_sis.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        self.vna.set_parameter(self.vna_parameter)
        self.vna.set_start_frequency(self.start_frequency)
        self.vna.set_stop_frequency(self.stop_frequency)
        self.vna.set_sweep(self.frequency_points)
        self.vna.set_power(self.vna_power)
        self.vna.set_channel_format("COMP")
        self.vna.set_average_count(self.vna_average_count)
        self.vna.set_average_status(True)

        frequencies = list(
            np.linspace(
                self.start_frequency * 1e9,
                self.stop_frequency * 1e9,
                self.frequency_points,
            )
        )

        self.measure.data["frequencies"] = frequencies

        initial_v = self.block.get_bias_voltage()
        v_range = np.linspace(
            self.start_voltage * 1e-3,
            self.stop_voltage * 1e-3,
            self.voltage_points,
        )
        proc = 0
        start_t = datetime.now()
        for i, v_set in enumerate(v_range, 1):
            if not state.BIAS_REFL_SCAN_THREAD:
                break
            self.block.set_bias_voltage(v_set)
            if i == 0:
                time.sleep(1)
            v_get = self.block.get_bias_voltage()
            if not v_get:
                continue
            i_get = self.block.get_bias_current()
            if not i_get:
                continue
            time.sleep(self.step_delay)  # waiting for VNA averaging
            vna_samples = []
            for sample in range(self.vna_samples_count):
                vna_data = self.vna.get_data()
                vna_data.pop("array", None)
                vna_data.pop("freq", None)
                vna_samples.append(vna_data)
                proc = round(
                    (
                        (i * self.vna_samples_count + sample)
                        / (self.voltage_points * self.vna_samples_count)
                    )
                    * 100
                )
            self.measure.data["v_get"].append(v_get * 1e3)
            self.measure.data["v_set"].append(v_set * 1e3)
            self.measure.data["i_get"].append(i_get * 1e6)
            self.measure.data["refl"].append(vna_samples)
            delta_t = datetime.now() - start_t
            self.measure.data["time"].append(delta_t.total_seconds())
            logger.info(
                f"[scan_reflection] Proc {proc} %; Time {delta_t}; V_set {v_set * 1e3}"
            )
            self.progress.emit(proc)

        self.block.set_bias_voltage(initial_v)
        self.block.disconnect()
        self.measure.save()
        self.pre_exit()
        self.finished.emit()


class SisReflectionMeasureWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.createGroupBiasReflScan()
        self.layout.addWidget(self.groupBiasReflScan)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupBiasReflScan(self):
        self.groupBiasReflScan = QGroupBox("Scan Bias Reflection")
        self.groupBiasReflScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.sisConfigLabel = QLabel(self)
        self.sisConfigLabel.setText("SIS block device")
        self.sisConfig = QComboBox(self)
        ScontelSisBlockManager.event_manager.configs_updated.connect(
            self.update_sis_config
        )

        self.voltageStartLabel = QLabel(self)
        self.voltageStartLabel.setText("Voltage start, mV")
        self.voltageStart = DoubleSpinBox(self)
        self.voltageStart.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltageStopLabel = QLabel(self)
        self.voltageStopLabel.setText("Voltage stop, mV")
        self.voltageStop = DoubleSpinBox(self)
        self.voltageStop.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltagePointsLabel = QLabel(self)
        self.voltagePointsLabel.setText("Voltage points")
        self.voltagePoints = DoubleSpinBox(self)
        self.voltagePoints.setMaximum(state.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltagePoints.setDecimals(0)
        self.voltagePoints.setValue(state.BLOCK_BIAS_VOLT_POINTS)

        self.scanStepDelayLabel = QLabel("Step delay, s")
        self.scanStepDelay = DoubleSpinBox(self)
        self.scanStepDelay.setRange(0, 10)
        self.scanStepDelay.setValue(state.BIAS_REFL_DELAY)

        self.vnaConfigLabel = QLabel(self)
        self.vnaConfigLabel.setText("VNA device")
        self.vnaConfig = QComboBox(self)
        RohdeSchwarzVnaZva67Manager.event_manager.configs_updated.connect(
            self.update_vna_config
        )

        self.vnaParameter = QComboBox(self)
        self.vnaParameter.addItems(state.VNA_SPARAMS)

        self.frequencyStartLabel = QLabel(self)
        self.frequencyStartLabel.setText("Freq start, GHz:")
        self.frequencyStart = DoubleSpinBox(self)
        self.frequencyStart.setRange(state.VNA_FREQ_MIN, state.VNA_FREQ_MAX)
        self.frequencyStart.setValue(state.VNA_FREQ_START)

        self.frequencyStopLabel = QLabel(self)
        self.frequencyStopLabel.setText("Freq stop, GHz:")
        self.frequencyStop = DoubleSpinBox(self)
        self.frequencyStop.setRange(state.VNA_FREQ_MIN, state.VNA_FREQ_MAX)
        self.frequencyStop.setValue(state.VNA_FREQ_STOP)

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

        self.vnaSamplesCountLabel = QLabel("VNA samples count")
        self.vnaSamplesCount = QSpinBox(self)
        self.vnaSamplesCount.setRange(1, 1000)
        self.vnaSamplesCount.setValue(state.VNA_SAMPLES_COUNT)

        self.vnaAverageCountLabel = QLabel(self)
        self.vnaAverageCountLabel.setText("Aver count:")
        self.vnaAverageCount = QSpinBox(self)
        self.vnaAverageCount.setRange(1, 1000)
        self.vnaAverageCount.setValue(10)

        self.scanProgress = QProgressBar(self)
        self.scanProgress.setValue(0)

        self.btnBiasReflScan = Button("Scan Bias Reflection", animate=True)
        self.btnBiasReflScan.clicked.connect(self.scan_bias_reflection)
        self.btnStopBiasReflScan = Button("Stop Scan")
        self.btnStopBiasReflScan.clicked.connect(self.stop_scan_bias_reflection)
        self.btnStopBiasReflScan.setEnabled(False)

        flayout.addRow(self.sisConfigLabel, self.sisConfig)
        flayout.addRow(self.voltageStartLabel, self.voltageStart)
        flayout.addRow(self.voltageStopLabel, self.voltageStop)
        flayout.addRow(self.voltagePointsLabel, self.voltagePoints)
        flayout.addRow(self.scanStepDelayLabel, self.scanStepDelay)
        flayout.addRow(HLine(self))
        flayout.addRow(self.vnaConfigLabel, self.vnaConfig)
        flayout.addRow("VNA parameter", self.vnaParameter)
        flayout.addRow(self.vnaPowerLabel, self.vnaPower)
        flayout.addRow(self.frequencyStartLabel, self.frequencyStart)
        flayout.addRow(self.frequencyStopLabel, self.frequencyStop)
        flayout.addRow(self.vnaPointsLabel, self.vnaPoints)
        flayout.addRow(self.vnaSamplesCountLabel, self.vnaSamplesCount)
        flayout.addRow(self.vnaAverageCountLabel, self.vnaAverageCount)
        flayout.addRow(HLine(self))
        flayout.addRow(self.scanProgress)

        hlayout.addWidget(self.btnBiasReflScan)
        hlayout.addWidget(self.btnStopBiasReflScan)

        layout.addLayout(flayout)
        layout.addLayout(hlayout)

        self.groupBiasReflScan.setLayout(layout)

    def update_vna_config(self):
        names = RohdeSchwarzVnaZva67Manager.configs.list_of_names()
        for i in range(self.vnaConfig.count()):
            self.vnaConfig.removeItem(i)
        if len(names):
            self.vnaConfig.insertItems(0, names)

    def update_sis_config(self):
        names = ScontelSisBlockManager.configs.list_of_names()
        for i in range(self.sisConfig.count()):
            self.sisConfig.removeItem(i)
        if len(names):
            self.sisConfig.insertItems(0, names)

    def scan_bias_reflection(self):
        self.bias_reflection_thread = BiasReflectionThread(
            cid_sis=ScontelSisBlockManager.configs[self.sisConfig.currentIndex()].cid,
            cid_vna=RohdeSchwarzVnaZva67Manager.configs[
                self.vnaConfig.currentIndex()
            ].cid,
            start_frequency=self.frequencyStart.value(),
            stop_frequency=self.frequencyStop.value(),
            frequency_points=self.vnaPoints.value(),
            vna_power=self.vnaPower.value(),
            vna_parameter=self.vnaParameter.currentText(),
            vna_samples_count=self.vnaSamplesCount.value(),
            vna_average_count=int(self.vnaAverageCount.value()),
            start_voltage=self.voltageStart.value(),
            stop_voltage=self.voltageStop.value(),
            voltage_points=self.voltagePoints.value(),
            step_delay=self.scanStepDelay.value(),
        )
        state.BIAS_REFL_SCAN_THREAD = True

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
