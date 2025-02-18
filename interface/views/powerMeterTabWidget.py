import time
import logging

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QVBoxLayout,
    QWidget,
    QLabel,
    QSizePolicy,
    QCheckBox,
    QHBoxLayout,
)

from interface.components.ui.Button import Button
from store.base import MeasureModel, MeasureType
from store.powerMeterUnitsModel import power_meter_unit_model
from store.state import state
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from threads import Thread
from utils.dock import Dock


logger = logging.getLogger(__name__)


class NRXBlockStreamThread(Thread):
    meas = Signal(dict)

    def run(self):
        nrx = NRXPowerMeter(
            host=state.NRX_IP,
            aperture_time=state.NRX_APER_TIME,
            delay=0,
        )
        data = {"power": [], "time": []}
        if state.NRX_STREAM_STORE_DATA:
            measure = MeasureModel.objects.create(
                measure_type=MeasureType.POWER_STREAM, data=data
            )
            measure.save(False)
        i = 0
        start_time = time.time()
        while state.NRX_STREAM_THREAD:
            power = nrx.get_power()
            meas_time = time.time() - start_time
            if not power:
                time.sleep(2)
                continue

            self.meas.emit({"power": power, "time": meas_time, "reset": i == 0})
            if state.NRX_STREAM_STORE_DATA:
                measure.data["power"].append(power)
                measure.data["time"].append(meas_time)
            i += 1

        if state.NRX_STREAM_STORE_DATA:
            measure.data = data
            measure.save(finish=True)

        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        state.NRX_STREAM_THREAD = False


class PowerMeterTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.powerStreamGraphDockWidget = None
        self.createGroupNRX()
        self.layout.addWidget(self.groupNRX)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupNRX(self):
        self.groupNRX = QGroupBox("Power meter monitor")
        self.groupNRX.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QVBoxLayout()
        grid_layout = QGridLayout()
        buttons_layout = QHBoxLayout()

        self.nrxPowerLabel = QLabel(self)
        self.nrxPowerLabel.setText("<h4>Power, dBm</h4>")
        power_meter_unit_model.value.connect(self.unit_changed)
        self.nrxPower = QLabel(self)
        self.nrxPower.setText("0.0")
        self.nrxPower.setStyleSheet("font-size: 23px; font-weight: bold;")

        self.btnStartStreamNRX = Button("Start Stream", animate=True)
        self.btnStartStreamNRX.clicked.connect(self.start_stream_nrx)

        self.btnStopStreamNRX = Button("Stop Stream")
        self.btnStopStreamNRX.setEnabled(False)
        self.btnStopStreamNRX.clicked.connect(self.stop_stream_nrx)

        self.checkNRXStreamPlot = QCheckBox(self)
        self.checkNRXStreamPlot.setText("Plot stream time line")

        self.checkNRXStoreStream = QCheckBox(self)
        self.checkNRXStoreStream.setText("Store stream data")

        self.nrxStreamWindowTimeLabel = QLabel(self)
        self.nrxStreamWindowTimeLabel.setText("Time window, s")
        self.nrxStreamWindowTime = DoubleSpinBox(self)
        self.nrxStreamWindowTime.setRange(10, 3600)
        self.nrxStreamWindowTime.setDecimals(0)
        self.nrxStreamWindowTime.setValue(state.NRX_STREAM_GRAPH_TIME)

        grid_layout.addWidget(
            self.nrxPowerLabel, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid_layout.addWidget(
            self.nrxPower, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid_layout.addWidget(self.checkNRXStreamPlot, 2, 0)
        grid_layout.addWidget(self.checkNRXStoreStream, 2, 1)
        grid_layout.addWidget(self.nrxStreamWindowTimeLabel, 3, 0)
        grid_layout.addWidget(self.nrxStreamWindowTime, 3, 1)

        buttons_layout.addWidget(self.btnStartStreamNRX)
        buttons_layout.addWidget(self.btnStopStreamNRX)

        layout.addLayout(grid_layout)
        layout.addLayout(buttons_layout)

        self.groupNRX.setLayout(layout)

    def unit_changed(self, unit: str):
        self.nrxPowerLabel.setText(
            f"<h4>Power, {power_meter_unit_model.val_pretty}</h4>"
        )

    def start_stream_nrx(self):
        self.nrx_stream_thread = NRXBlockStreamThread()

        state.NRX_STREAM_THREAD = True
        state.NRX_STREAM_PLOT_GRAPH = self.checkNRXStreamPlot.isChecked()
        state.NRX_STREAM_GRAPH_TIME = self.nrxStreamWindowTime.value()
        state.NRX_STREAM_STORE_DATA = self.checkNRXStoreStream.isChecked()

        self.nrx_stream_thread.meas.connect(self.update_nrx_stream_values)

        self.powerStreamGraphDockWidget = Dock.ex.dock_manager.findDockWidget(
            "P-t curve"
        )
        self.nrx_stream_thread.start()

        self.btnStartStreamNRX.setEnabled(False)
        self.nrx_stream_thread.finished.connect(
            lambda: self.btnStartStreamNRX.setEnabled(True)
        )

        self.btnStopStreamNRX.setEnabled(True)
        self.nrx_stream_thread.finished.connect(
            lambda: self.btnStopStreamNRX.setEnabled(False)
        )

    def show_power_stream_graph(self, x: float, y: float, reset: bool = True):
        if self.powerStreamGraphDockWidget is None:
            return
        self.powerStreamGraphDockWidget.widget().plotNew(x=x, y=y, reset_data=reset)
        self.powerStreamGraphDockWidget.widget().show()

    def update_nrx_stream_values(self, measure: dict):
        self.nrxPower.setText(f"{measure.get('power'):.3E}")
        if state.NRX_STREAM_PLOT_GRAPH:
            self.show_power_stream_graph(
                x=measure.get("time"),
                y=measure.get("power"),
                reset=measure.get("reset"),
            )

    def stop_stream_nrx(self):
        self.nrx_stream_thread.quit()
        self.nrx_stream_thread.exit(0)
