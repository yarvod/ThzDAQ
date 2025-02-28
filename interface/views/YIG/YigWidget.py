import logging
import time

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QSizePolicy,
    QCheckBox,
    QProgressBar,
    QGroupBox,
    QHBoxLayout,
    QFormLayout,
)

from api.Chopper import chopper_manager
from api.NationalInstruments.yig_filter import NiYIGManager, YigType
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from interface.components.yig.manage_yig import ManageYigWidget
from store.state import state
from store.base import MeasureModel
from threads import Thread
from utils.dock import Dock
from utils.functions import get_if_tn

logger = logging.getLogger(__name__)


class MeasureThread(Thread):
    stream_result = Signal(dict)
    stream_y_results = Signal(dict)
    stream_tn_results = Signal(dict)
    progress = Signal(int)

    def __init__(self, yig: YigType):
        super().__init__()
        self.yig = yig
        self.ni = NiYIGManager()
        self.nrx = NRXPowerMeter(
            host=state.NRX_IP,
            aperture_time=state.NRX_APER_TIME,
            delay=0,
        )
        if state.CHOPPER_SWITCH:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureModel.type_class.PIF_CURVE_HOT_COLD, data=[]
            )
        else:
            self.measure = MeasureModel.objects.create(
                measure_type=MeasureModel.type_class.PIF_CURVE, data=[]
            )
        self.measure.save(finish=False)

        self.initial_freq = state.DIGITAL_YIG_MAP[yig].value

    def get_results_format(self):
        if not state.CHOPPER_SWITCH:
            return []
        return {
            "hot": {"data": [], "power": [], "frequency": []},
            "cold": {"data": [], "power": [], "frequency": []},
            "diff": [],
        }

    def run(self):
        results = self.get_results_format()
        freq_range = np.linspace(
            state.NI_FREQ_FROM,
            state.NI_FREQ_TO,
            int(state.NI_FREQ_POINTS),
        )
        if state.CHOPPER_SWITCH:
            chopper_manager.chopper.align_to_hot()
        start_time = time.time()
        chopper_range = list(range(1, 3) if state.CHOPPER_SWITCH else range(1, 2))
        total_steps = state.NI_FREQ_POINTS * state.NRX_POINTS * len(chopper_range)
        for chopper_step in chopper_range:
            chop_state = "hot" if chopper_step == 1 else "cold"
            if not state.NI_STABILITY_MEAS:
                break

            for freq_step, freq in enumerate(freq_range, 1):
                if not state.NI_STABILITY_MEAS:
                    break
                result = {
                    "frequency": freq,
                    "power": [],
                    "power_mean": 0,
                    "time": [],
                }
                if not state.NI_STABILITY_MEAS:
                    break
                freq_set = self.ni.set_frequency(freq * 1e9)
                if freq_set:
                    state.DIGITAL_YIG_MAP[self.yig].value = freq_set
                else:
                    break
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
                logger.info(f"Power {result['power'][-1]}")
                power_mean = np.mean(result["power"])
                result["power_mean"] = power_mean
                self.stream_result.emit(
                    {
                        "x": [freq],
                        "y": [power_mean],
                        "new_plot": freq_step == 1,
                        "measure_id": self.measure.id,
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
                time.sleep(2)

        if state.CHOPPER_SWITCH:
            hot = np.array(results["hot"]["power"])
            cold = np.array(results["cold"]["power"])
            if len(hot) and len(cold):

                min_ind = min([len(cold), len(hot)])
                y_factor = hot[:min_ind] - cold[:min_ind]
                tn = get_if_tn(hot_power=hot[:min_ind], cold_power=cold[:min_ind])
                self.stream_y_results.emit(
                    {
                        "x": results["hot"]["frequency"],
                        "y": y_factor.tolist(),
                        "measure_id": self.measure.id,
                    }
                )
                self.stream_tn_results.emit(
                    {
                        "x": results["hot"]["frequency"],
                        "y": tn.tolist(),
                        "measure_id": self.measure.id,
                    }
                )
                self.measure.data["y_factor"] = y_factor.tolist()
                self.measure.data["tn"] = tn.tolist()

            chopper_manager.chopper.align_to_cold()

        self.pre_exit()
        self.finished.emit()

    def pre_exit(self):
        state.NI_STABILITY_MEAS = False
        resp = self.ni.set_frequency(self.initial_freq, yig=self.yig)
        if resp:
            state.DIGITAL_YIG_MAP[self.yig].value = resp
        self.nrx.adapter.close()
        self.measure.save()


class YIGWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.createGroupMeas()
        layout.addWidget(ManageYigWidget(self, yig="yig_1"))
        layout.addWidget(ManageYigWidget(self, yig="yig_2"))
        layout.addWidget(self.groupMeas)
        layout.addStretch()
        self.setLayout(layout)

        self.powerIfGraphWindow = None
        self.yIfGraphWindow = None
        self.tnIfGraphWindow = None

    def createGroupMeas(self):
        self.groupMeas = QGroupBox("P-IF measurement")
        self.groupMeas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.niFreqStartLabel = QLabel(self)
        self.niFreqStartLabel.setText("Frequency start, GHz")
        self.niFreqStart = DoubleSpinBox(self)
        self.niFreqStart.setRange(2.97, 13)
        self.niFreqStart.setDecimals(3)
        self.niFreqStart.setValue(state.NI_FREQ_FROM)

        self.niFreqStopLabel = QLabel(self)
        self.niFreqStopLabel.setText("Frequency stop, GHz")
        self.niFreqStop = DoubleSpinBox(self)
        self.niFreqStop.setRange(2.97, 13)
        self.niFreqStop.setDecimals(3)
        self.niFreqStop.setValue(state.NI_FREQ_TO)

        self.niFreqPointsLabel = QLabel(self)
        self.niFreqPointsLabel.setText("Freq points")
        self.niFreqPoints = DoubleSpinBox(self)
        self.niFreqPoints.setRange(0, 100000)
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

        flayout.addRow(self.niFreqStartLabel, self.niFreqStart)
        flayout.addRow(self.niFreqStopLabel, self.niFreqStop)
        flayout.addRow(self.niFreqPointsLabel, self.niFreqPoints)
        flayout.addRow(self.nrxPointsLabel, self.nrxPoints)
        flayout.addRow(self.chopperSwitch)
        flayout.addRow(self.progress)
        hlayout.addWidget(self.btnStartMeas)
        hlayout.addWidget(self.btnStopMeas)

        layout.addLayout(flayout)
        layout.addLayout(hlayout)

        self.groupMeas.setLayout(layout)

    def start_meas(self):
        self.meas_thread = MeasureThread(yig="yig_1")

        state.NI_STABILITY_MEAS = True
        state.NI_FREQ_TO = self.niFreqStop.value()
        state.NI_FREQ_FROM = self.niFreqStart.value()
        state.NI_FREQ_POINTS = int(self.niFreqPoints.value())
        state.NRX_POINTS = int(self.nrxPoints.value())
        state.CHOPPER_SWITCH = self.chopperSwitch.isChecked()

        self.meas_thread.stream_result.connect(self.show_p_if_graph_window)
        self.meas_thread.progress.connect(lambda x: self.progress.setValue(x))
        self.meas_thread.finished.connect(lambda: self.progress.setValue(0))
        if state.CHOPPER_SWITCH:
            self.meas_thread.stream_y_results.connect(self.show_y_if_graph)
            self.meas_thread.stream_tn_results.connect(self.show_tn_if_graph)

        self.powerIfGraphWindow = Dock.ex.dock_manager.findDockWidget("P-IF curve")
        self.yIfGraphWindow = Dock.ex.dock_manager.findDockWidget("Y-IF curve")
        self.tnIfGraphWindow = Dock.ex.dock_manager.findDockWidget("Tn-IF curve")

        self.meas_thread.start()

        self.btnStartMeas.setEnabled(False)
        self.meas_thread.finished.connect(lambda: self.btnStartMeas.setEnabled(True))

        self.btnStopMeas.setEnabled(True)
        self.meas_thread.finished.connect(lambda: self.btnStopMeas.setEnabled(False))

    def stop_meas(self):
        state.NI_STABILITY_MEAS = False

    def show_p_if_graph_window(self, results: dict):
        if self.powerIfGraphWindow is None:
            return
        self.powerIfGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            new_plot=results.get("new_plot", True),
            measure_id=results.get("measure_id"),
        )
        self.powerIfGraphWindow.widget().show()

    def show_y_if_graph(self, results):
        if self.yIfGraphWindow is None:
            return
        self.yIfGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            measure_id=results.get("measure_id"),
        )
        self.yIfGraphWindow.widget().show()

    def show_tn_if_graph(self, results):
        if self.tnIfGraphWindow is None:
            return
        self.tnIfGraphWindow.widget().plotNew(
            x=results.get("x", []),
            y=results.get("y", []),
            measure_id=results.get("measure_id"),
        )
        self.tnIfGraphWindow.widget().show()
