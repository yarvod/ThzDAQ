import time

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QHBoxLayout,
    QProgressBar,
)

from api.NationalInstruments.yig_filter import NiYIGManager, YigType
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.Scontel.sis_block import SisBlock
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store.base import MeasureModel
from store.powerMeterUnitsModel import power_meter_unit_model
from store.state import state
from threads import Thread
from utils.dock import Dock
from utils.functions import linear_fit, linear, calc_tta


class MeasureRnThread(Thread):
    rn1 = Signal(float)
    rn2 = Signal(float)
    progress = Signal(int)

    def __init__(self, voltage1, voltage2):
        super().__init__()
        self.voltage1 = voltage1
        self.voltage2 = voltage2
        self.sis = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            ctrl_dev=state.BLOCK_CTRL_DEV,
            bias_dev=state.BLOCK_BIAS_DEV,
        )

    def run(self):
        self.sis.connect()

        steps = 42
        step = 0
        voltage1_range = (
            np.linspace(self.voltage1 * 0.95, self.voltage1 * 1.05, 20) * 1e-3
        )
        voltage1_get = []
        current1_get = []
        for voltage in voltage1_range:
            self.sis.set_bias_voltage(voltage)
            time.sleep(0.05)
            voltage1_get.append(self.sis.get_bias_voltage())
            current1_get.append(self.sis.get_bias_current())
            step += 1
            self.progress.emit(round(step / steps * 100))

        voltage2_range = (
            np.linspace(self.voltage2 * 0.95, self.voltage2 * 1.05, 20) * 1e-3
        )
        voltage2_get = []
        current2_get = []
        for voltage in voltage2_range:
            self.sis.set_bias_voltage(voltage)
            time.sleep(0.05)
            voltage2_get.append(self.sis.get_bias_voltage())
            current2_get.append(self.sis.get_bias_current())
            step += 1
            self.progress.emit(round(step / steps * 100))

        rn1, _ = linear_fit(voltage1_get, current1_get)
        self.rn1.emit(1 / rn1)
        step += 1
        self.progress.emit(round(step / steps * 100))
        rn2, _ = linear_fit(voltage2_get, current2_get)
        self.rn2.emit(1 / rn2)
        step += 1
        self.progress.emit(round(step / steps * 100))
        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        self.sis.disconnect()


class MeasurePowerThread(Thread):
    current1 = Signal(float)
    current2 = Signal(float)
    result = Signal(dict)
    progress = Signal(int)

    def __init__(
        self,
        voltage1,
        voltage2,
        rn1,
        rn2,
        freq_start,
        freq_stop,
        freq_points,
        t_sis=4,
        yig: YigType = "yig_1",
    ):
        super().__init__()
        self.voltage1 = voltage1 * 1e-3
        self.voltage2 = voltage2 * 1e-3
        self.rn1 = rn1
        self.rn2 = rn2
        self.freq_range = np.linspace(freq_start, freq_stop, freq_points)
        self.t_sis = t_sis
        self.sis = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            ctrl_dev=state.BLOCK_CTRL_DEV,
            bias_dev=state.BLOCK_BIAS_DEV,
        )
        self.nrx = NRXPowerMeter(
            host=state.NRX_IP,
            aperture_time=state.NRX_APER_TIME,
            delay=0,
        )
        self.yig_type = yig
        self.yig = NiYIGManager()
        self.initial_freq = state.DIGITAL_YIG_MAP[yig].value
        self.measure = MeasureModel.objects.create(
            measure_type=MeasureModel.type_class.TA_SIS_CALIBRATION, data={}
        )
        self.measure.save(False)

    def run(self):
        self.sis.connect()
        step = 0
        steps = 2 * len(self.freq_range) + 1
        self.measure.data = {
            "point 1": {
                "voltage": None,
                "current": None,
                "rd": self.rn1,
                "power": [],
                "power_units": power_meter_unit_model.val_pretty,
            },
            "point 2": {
                "voltage": None,
                "current": None,
                "rd": self.rn2,
                "power": [],
                "power_units": power_meter_unit_model.val_pretty,
            },
            "frequency": self.freq_range.tolist(),
            "tn": [],
        }
        voltage_get = []
        current_get = []
        for i, voltage_set in enumerate([self.voltage1, self.voltage2], 1):
            self.sis.set_bias_voltage(voltage_set)
            time.sleep(0.5)
            voltage = self.sis.get_bias_voltage()
            voltage_get.append(voltage)
            current = self.sis.get_bias_current()
            current_get.append(current)
            current_signal = getattr(self, f"current{i}")
            current_signal.emit(current)
            self.current1.emit(current)
            for freq in self.freq_range:
                step += 1
                self.progress.emit(round(step / steps * 100))
                freq_point = linear(freq * 1e9, *state.CALIBRATION_DIGITAL_FREQ_2_POINT)
                resp = self.yig.write_task(freq_point)
                resp_int = resp.get("result", None)
                if resp_int:
                    freq = round(
                        linear(resp_int, *state.CALIBRATION_DIGITAL_POINT_2_FREQ)
                        * 1e-9,
                        2,
                    )
                    state.DIGITAL_YIG_MAP[self.yig_type].value = freq
                else:
                    break

                power = self.nrx.get_power()
                self.measure.data[f"point {i}"]["power"].append(power)
                self.measure.data[f"point {i}"]["voltage"] = voltage
                self.measure.data[f"point {i}"]["current"] = current

        if (
            len(voltage_get) == 2
            and len(current_get) == 2
            and len(self.measure.data["point 1"]["power"])
            == len(self.measure.data["point 2"]["power"])
        ):
            ta = calc_tta(
                p_if_data1=self.measure.data["point 1"],
                p_if_data2=self.measure.data["point 2"],
                v1=voltage_get[0],
                v2=voltage_get[1],
                i1=current_get[0],
                i2=current_get[1],
                rd1=self.rn1,
                rd2=self.rn2,
                t_sis=self.t_sis,
            )
            self.result.emit(
                {
                    "x": self.freq_range.tolist(),
                    "y": list(ta),
                    "measure_id": self.measure.id,
                }
            )
            self.measure.data["tn"] = list(ta)

        step += 1
        self.progress.emit(round(step / steps * 100))

        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        self.measure.save()
        self.sis.disconnect()
        del self.sis
        del self.nrx


class SisRnPowerMeasureTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)

        self.groupInitialCalibration = None
        self.createGroupInitialCalibration()
        self.layout.addWidget(self.groupInitialCalibration)

        self.layout.addStretch()
        self.setLayout(self.layout)

        self.current1 = None
        self.current2 = None

    def createGroupInitialCalibration(self):
        self.groupInitialCalibration = QGroupBox(self)
        self.groupInitialCalibration.setTitle("Initial calibration")

        layout_main = QVBoxLayout()
        flayout1 = QFormLayout()
        flayout2 = QFormLayout()
        hlayout1 = QHBoxLayout()
        hlayout2 = QHBoxLayout()

        self.voltage1 = DoubleSpinBox(self)
        self.voltage1.setRange(-30, 30)
        self.voltage1.setValue(15)

        self.voltage2 = DoubleSpinBox(self)
        self.voltage2.setRange(-30, 30)
        self.voltage2.setValue(20)

        self.rn1 = DoubleSpinBox(self)
        self.rn1.setRange(0, 100)
        self.rn1.setValue(0)

        self.rn2 = DoubleSpinBox(self)
        self.rn2.setRange(0, 100)
        self.rn2.setValue(0)

        self.frequencyStart = DoubleSpinBox(self)
        self.frequencyStart.setRange(3, 13)
        self.frequencyStart.setValue(3)

        self.frequencyStop = DoubleSpinBox(self)
        self.frequencyStop.setRange(3, 13)
        self.frequencyStop.setValue(13)

        self.frequencyPoints = QSpinBox(self)
        self.frequencyPoints.setRange(1, 5000)
        self.frequencyPoints.setValue(300)

        self.t_sis = DoubleSpinBox(self)
        self.t_sis.setRange(0, 300)
        self.t_sis.setValue(4)

        self.progress_rn = QProgressBar(self)
        self.progress_rn.setValue(0)

        self.progress_p = QProgressBar(self)
        self.progress_p.setValue(0)

        self.btnStartCalculateRn = Button("Start Measure Rn", animate=True)
        self.btnStartCalculateRn.clicked.connect(self.start_measure_rn)
        self.btnStopCalculateRn = Button("Stop Measure Rn")
        self.btnStopCalculateRn.clicked.connect(self.stop_measure_rn)
        self.btnStopCalculateRn.setEnabled(False)

        self.btnStartMeasure = Button("Start Measure Power", animate=True)
        self.btnStartMeasure.clicked.connect(self.start_measure_power)
        self.btnStopMeasure = Button("Stop Measure Power")
        self.btnStopMeasure.clicked.connect(self.stop_measure_power)
        self.btnStopMeasure.setEnabled(False)

        flayout1.addRow("Voltage 1, mV", self.voltage1)
        flayout1.addRow("Voltage 2, mV", self.voltage2)
        flayout1.addRow("Rn 1, Ohm", self.rn1)
        flayout1.addRow("Rn 2, Ohm", self.rn2)
        flayout1.addRow(self.progress_rn)
        hlayout1.addWidget(self.btnStartCalculateRn)
        hlayout1.addWidget(self.btnStopCalculateRn)
        flayout2.addRow("Frequency start, GHz", self.frequencyStart)
        flayout2.addRow("Frequency stop, GHz", self.frequencyStop)
        flayout2.addRow("Frequency points", self.frequencyPoints)
        flayout2.addRow("Temp SIS, K", self.t_sis)
        flayout2.addRow(self.progress_p)
        hlayout2.addWidget(self.btnStartMeasure)
        hlayout2.addWidget(self.btnStopMeasure)

        layout_main.addLayout(flayout1)
        layout_main.addLayout(hlayout1)
        layout_main.addLayout(flayout2)
        layout_main.addLayout(hlayout2)
        self.groupInitialCalibration.setLayout(layout_main)

    def start_measure_rn(self):
        self.thread_measure_rn = MeasureRnThread(
            self.voltage1.value(), self.voltage2.value()
        )

        self.thread_measure_rn.rn1.connect(lambda x: self.rn1.setValue(x))
        self.thread_measure_rn.rn2.connect(lambda x: self.rn2.setValue(x))
        self.thread_measure_rn.progress.connect(lambda x: self.progress_rn.setValue(x))

        self.thread_measure_rn.finished.connect(
            lambda: self.btnStartCalculateRn.setEnabled(True)
        )
        self.thread_measure_rn.finished.connect(
            lambda: self.btnStopCalculateRn.setEnabled(False)
        )
        self.thread_measure_rn.finished.connect(lambda: self.progress_rn.setValue(0))
        self.btnStartCalculateRn.setEnabled(False)
        self.btnStopCalculateRn.setEnabled(True)
        self.thread_measure_rn.start()

    def stop_measure_rn(self):
        self.thread_measure_rn.terminate()

    def start_measure_power(self):
        self.thread_measure_power = MeasurePowerThread(
            voltage1=self.voltage1.value(),
            voltage2=self.voltage2.value(),
            rn1=self.rn1.value(),
            rn2=self.rn2.value(),
            freq_start=self.frequencyStart.value(),
            freq_stop=self.frequencyStop.value(),
            freq_points=self.frequencyPoints.value(),
            t_sis=self.t_sis.value(),
        )

        self.thread_measure_power.current1.connect(self.set_current1)
        self.thread_measure_power.current2.connect(self.set_current2)

        self.thread_measure_power.finished.connect(
            lambda: self.btnStartMeasure.setEnabled(True)
        )
        self.thread_measure_power.finished.connect(
            lambda: self.btnStopMeasure.setEnabled(False)
        )
        self.thread_measure_power.progress.connect(
            lambda x: self.progress_p.setValue(x)
        )
        self.thread_measure_power.finished.connect(lambda: self.progress_p.setValue(0))
        self.thread_measure_power.result.connect(self.plot_graph_ta_if)
        self.btnStartMeasure.setEnabled(False)
        self.btnStopMeasure.setEnabled(True)

        self.thread_measure_power.start()

    def stop_measure_power(self):
        self.thread_measure_power.terminate()

    def set_current1(self, value):
        self.current1 = value

    def set_current2(self, value):
        self.current2 = value

    def plot_graph_ta_if(self, results):
        graph_tn_if = Dock.ex.dock_manager.findDockWidget("Tn-IF curve")
        if graph_tn_if is None:
            return
        graph_tn_if.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            measure_id=results.get("measure_id"),
        )
        graph_tn_if.widget().show()
