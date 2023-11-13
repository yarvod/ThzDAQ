import logging
import time

import numpy as np
from PyQt5.QtCore import pyqtSignal, QThread, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QScrollArea,
    QCheckBox,
    QProgressBar,
    QGroupBox as GroupBox,
    QFormLayout,
)

from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store.state import state
from store.base import MeasureModel
from utils.functions import linear

logger = logging.getLogger(__name__)


class DigitalYigThread(QThread):
    response = pyqtSignal(str)

    def run(self):
        value = int(
            linear(
                state.DIGITAL_YIG_FREQ * 1e9, *state.CALIBRATION_DIGITAL_FREQ_2_POINT
            )
        )
        ni_yig = NiYIGManager(host=state.NI_IP)
        resp = ni_yig.write_task(value=value)
        resp_int = resp.get("result", None)
        if resp_int is None:
            self.response.emit("Unable to set frequency")
        else:
            freq = round(
                linear(resp_int, *state.CALIBRATION_DIGITAL_POINT_2_FREQ) * 1e-9, 2
            )
            self.response.emit(f"{freq} GHz")
        logger.info(f"[setNiYigFreq] {resp}")


class MeasureThread(QThread):
    results = pyqtSignal(list)
    stream_result = pyqtSignal(dict)
    stream_diff_results = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def get_results_format(self):
        if not state.CHOPPER_SWITCH:
            return []
        return {
            "hot": {"data": [], "power": [], "frequency": []},
            "cold": {"data": [], "power": [], "frequency": []},
            "diff": [],
        }

    def run(self):
        ni = NiYIGManager()
        self.nrx = NRXPowerMeter(
            ip=state.NRX_IP,
            filter_time=state.NRX_FILTER_TIME,
            aperture_time=state.NRX_APER_TIME,
        )
        if state.CHOPPER_SWITCH:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureModel.type_class.CHOPPER_IF_POWER, data=[]
            )
        else:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureModel.type_class.IF_POWER, data=[]
            )
        self.measure.save(finish=False)

        results = self.get_results_format()
        freq_range = np.linspace(
            state.NI_FREQ_FROM,
            state.NI_FREQ_TO,
            int(state.NI_FREQ_POINTS),
        )
        start_time = time.time()
        chopper_range = list(range(1, 3) if state.CHOPPER_SWITCH else range(1, 2))
        total_steps = state.NI_FREQ_POINTS * state.NRX_POINTS * len(chopper_range)
        for chopper_step in chopper_range:
            chop_state = "hot" if chopper_step == 1 else "cold"

            for freq_step, freq in enumerate(freq_range, 1):
                result = {
                    "frequency": freq,
                    "power": [],
                    "power_mean": 0,
                    "time": [],
                }
                if not state.NI_STABILITY_MEAS:
                    break
                freq_point = linear(freq * 1e9, *state.CALIBRATION_DIGITAL_FREQ_2_POINT)
                ni.write_task(freq_point)
                time.sleep(0.01)
                if freq_step == 1:
                    time.sleep(0.4)
                tm = time.time()
                for power_step in range(1, state.NRX_POINTS + 1):
                    power = self.nrx.get_power()
                    result["power"].append(power)
                    result["time"].append(time.time() - tm)
                    step = (
                        (chopper_step - 1) * state.NI_FREQ_POINTS + freq_step - 1
                    ) * state.NRX_POINTS + power_step
                    proc = round(step / total_steps * 100, 2)
                    logger.info(
                        f"[{proc} %][Time {round(time.time() - start_time, 1)} s][Freq {freq}]"
                    )
                    self.progress.emit(int(proc))

                power_mean = np.mean(result["power"])
                result["power_mean"] = power_mean
                self.stream_result.emit(
                    {
                        "x": [freq],
                        "y": [power_mean],
                        "new_plot": freq_step == 1,
                    }
                )

                if state.CHOPPER_SWITCH:
                    results[chop_state]["data"].append(result)
                    results[chop_state]["power"].append(power_mean)
                    results[chop_state]["frequency"].append(freq)
                else:
                    results.append(result)

                self.measure.data = results

            if state.CHOPPER_SWITCH:
                chopper_manager.chopper.path0()
                if not chopper_step == 2:
                    time.sleep(2)

        if state.CHOPPER_SWITCH:
            hot = np.array(results["hot"]["power"])
            cold = np.array(results["cold"]["power"])
            if len(hot) and len(cold):

                min_ind = min([len(cold), len(hot)])
                power_diff = hot[:min_ind] - cold[:min_ind]
                self.stream_diff_results.emit(
                    {
                        "x": results["hot"]["frequency"],
                        "y": power_diff.tolist(),
                    }
                )
                self.measure.data["diff"] = power_diff.tolist()

        self.pre_exit()
        self.results.emit(results)
        self.finished.emit()

    def pre_exit(self):
        self.nrx.disconnect()
        self.measure.save()

    def terminate(self) -> None:
        self.pre_exit()
        super().terminate()


class YIGWidget(QScrollArea):
    def __init__(self, parent):
        super().__init__(parent)
        self.widget = QWidget()
        self.layout = QVBoxLayout(self)
        self.powerIfGraphWindow = None
        self.powerIfDiffGraphWindow = None
        self.createGroupNiYig()
        self.createGroupMeas()
        self.layout.addWidget(self.groupNiYig)
        self.layout.addWidget(self.groupMeas)
        self.layout.addStretch()
        self.widget.setLayout(self.layout)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setWidget(self.widget)

    def createGroupMeas(self):
        self.groupMeas = GroupBox("P-IF measurement")
        self.groupMeas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.niFreqStartLabel = QLabel(self)
        self.niFreqStartLabel.setText("Frequency start, GHz")
        self.niFreqStart = DoubleSpinBox(self)
        self.niFreqStart.setRange(0, 20)
        self.niFreqStart.setDecimals(3)
        self.niFreqStart.setValue(state.NI_FREQ_FROM)

        self.niFreqStopLabel = QLabel(self)
        self.niFreqStopLabel.setText("Frequency stop, GHz")
        self.niFreqStop = DoubleSpinBox(self)
        self.niFreqStop.setRange(0, 20)
        self.niFreqStop.setDecimals(3)
        self.niFreqStop.setValue(state.NI_FREQ_TO)

        self.niFreqPointsLabel = QLabel(self)
        self.niFreqPointsLabel.setText("Freq points")
        self.niFreqPoints = DoubleSpinBox(self)
        self.niFreqPoints.setRange(0, 1001)
        self.niFreqPoints.setDecimals(0)
        self.niFreqPoints.setValue(state.NI_FREQ_POINTS)

        self.nrxPointsLabel = QLabel(self)
        self.nrxPointsLabel.setText("Power points")
        self.nrxPoints = DoubleSpinBox(self)
        self.nrxPoints.setRange(0, 1001)
        self.nrxPoints.setDecimals(0)
        self.nrxPoints.setValue(state.NRX_POINTS)

        self.chopperSwitch = QCheckBox(self)
        self.chopperSwitch.setText("Enable chopper Hot/Cold switching")
        self.chopperSwitch.setChecked(state.CHOPPER_SWITCH)

        self.progress = QProgressBar(self)
        self.progress.setValue(0)

        self.btnStartMeas = Button("Start Measure", animate=True)
        self.btnStartMeas.clicked.connect(self.start_meas)

        self.btnStopMeas = Button("Stop Measure")
        self.btnStopMeas.clicked.connect(self.stop_meas)

        layout.addWidget(self.niFreqStartLabel, 1, 0)
        layout.addWidget(self.niFreqStart, 1, 1)
        layout.addWidget(self.niFreqStopLabel, 2, 0)
        layout.addWidget(self.niFreqStop, 2, 1)
        layout.addWidget(self.niFreqPointsLabel, 3, 0)
        layout.addWidget(self.niFreqPoints, 3, 1)
        layout.addWidget(self.nrxPointsLabel, 4, 0)
        layout.addWidget(self.nrxPoints, 4, 1)
        layout.addWidget(self.chopperSwitch, 5, 0)
        layout.addWidget(self.progress, 6, 0, 1, 2)
        layout.addWidget(self.btnStartMeas, 7, 0)
        layout.addWidget(self.btnStopMeas, 7, 1)

        self.groupMeas.setLayout(layout)

    def createGroupNiYig(self):
        self.groupNiYig = GroupBox("Digital YIG (NI)")
        self.groupNiYig.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QFormLayout()

        self.niYigFreqLabel = QLabel(self)
        self.niYigFreqLabel.setText("Freq, GHz")
        self.niYigFreq = DoubleSpinBox(self)
        self.niYigFreq.setRange(2.94, 13)
        self.niYigFreq.setValue(state.DIGITAL_YIG_FREQ)

        self.niDigitalResponseLabel = QLabel(self)
        self.niDigitalResponseLabel.setText("Actual:")
        self.niDigitalResponse = QLabel(self)
        self.niDigitalResponse.setText("Unknown")

        self.btnSetNiYigFreq = Button("Set frequency", animate=True)
        self.btnSetNiYigFreq.clicked.connect(self.set_ni_yig_freq)

        layout.addRow(self.niYigFreqLabel, self.niYigFreq)
        layout.addRow(self.niDigitalResponseLabel, self.niDigitalResponse)
        layout.addRow(self.btnSetNiYigFreq)

        self.groupNiYig.setLayout(layout)

    def start_meas(self):
        self.meas_thread = MeasureThread()

        state.NI_STABILITY_MEAS = True
        state.NI_FREQ_TO = self.niFreqStop.value()
        state.NI_FREQ_FROM = self.niFreqStart.value()
        state.NI_FREQ_POINTS = int(self.niFreqPoints.value())
        state.NRX_POINTS = int(self.nrxPoints.value())
        state.CHOPPER_SWITCH = self.chopperSwitch.isChecked()

        self.meas_thread.stream_result.connect(self.show_measure_graph_window)
        self.meas_thread.progress.connect(lambda x: self.progress.setValue(x))
        self.meas_thread.finished.connect(lambda: self.progress.setValue(0))
        if state.CHOPPER_SWITCH:
            self.meas_thread.stream_diff_results.connect(
                self.show_bias_power_diff_graph
            )
        self.meas_thread.start()

        self.btnStartMeas.setEnabled(False)
        self.meas_thread.finished.connect(lambda: self.btnStartMeas.setEnabled(True))

        self.btnStopMeas.setEnabled(True)
        self.meas_thread.finished.connect(lambda: self.btnStopMeas.setEnabled(False))

    def stop_meas(self):
        state.NI_STABILITY_MEAS = False
        self.meas_thread.terminate()

    def show_measure_graph_window(self, results: dict):
        if self.powerIfGraphWindow is None:
            return
        self.powerIfGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
        )
        self.powerIfGraphWindow.widget().show()

    def show_bias_power_diff_graph(self, results):
        if self.powerIfDiffGraphWindow is None:
            return
        self.powerIfDiffGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
        )
        self.powerIfDiffGraphWindow.widget().show()

    def set_ni_yig_freq(self):
        state.DIGITAL_YIG_FREQ = self.niYigFreq.value()
        self.set_digital_yig_freq_thread = DigitalYigThread()
        self.set_digital_yig_freq_thread.finished.connect(
            lambda: self.btnSetNiYigFreq.setEnabled(True)
        )
        self.set_digital_yig_freq_thread.response.connect(
            lambda x: self.niDigitalResponse.setText(f"{x}")
        )
        self.set_digital_yig_freq_thread.start()
        self.btnSetNiYigFreq.setEnabled(False)
