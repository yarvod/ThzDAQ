from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QFormLayout,
    QComboBox,
    QCheckBox,
)

from interface.components.ui.Button import Button
from store import RohdeSchwarzVnaZva67Manager
from store.base import MeasureModel, MeasureType
from store.state import state
from api.RohdeSchwarz.vna import VNABlock
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from threads import Thread
from utils.dock import Dock
from utils.exceptions import DeviceConnectionError
from utils.functions import to_db


class VnaGetDataThread(Thread):
    results = Signal(dict)

    def __init__(
        self,
        cid: int,
        store_data: bool,
    ):
        super().__init__()
        self.cid = cid
        self.store_data = store_data
        self.config = RohdeSchwarzVnaZva67Manager.get_config(cid)
        self.vna = None

    def run(self):
        try:
            self.vna = VNABlock(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return
        data = self.vna.get_data()
        results = {
            "reflection": list(to_db(data.pop("array", []))),
            "freq": data["freq"],
            "s_param": data["parameter"],
            "power": data["power"],
        }
        if self.store_data:
            measure = MeasureModel.objects.create(
                measure_type=MeasureType.SIF_VNA,
                data=data,
                finished=datetime.now(),
            )
            measure.save()
            results["measure_id"] = measure.id
        self.results.emit(results)
        self.pre_exit()
        self.finished.emit()


class ConfigureVnaThread(Thread):
    def __init__(
        self,
        cid: int,
        start: float,
        stop: float,
        points: int,
        parameter: str,
        power: float = -30,
        channel_format: str = "COMP",
        average_count: int = 10,
    ):
        super().__init__()
        self.cid = cid
        self.config = RohdeSchwarzVnaZva67Manager.get_config(cid)
        self.start_frequency = start
        self.stop_frequency = stop
        self.points = points
        self.parameter = parameter
        self.power = power
        self.channel_format = channel_format
        self.average_count = average_count
        self.vna = None

    def run(self):
        try:
            self.vna = VNABlock(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        self.vna.set_parameter(self.parameter)
        self.vna.set_start_frequency(self.start_frequency)
        self.vna.set_stop_frequency(self.stop_frequency)
        self.vna.set_sweep(self.points)
        self.vna.set_power(self.power)
        self.vna.set_channel_format(self.channel_format)
        self.vna.set_average_count(self.average_count)
        self.vna.set_average_status(True)

        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        del self.vna


class VNATabWidget(QWidget):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self.layout = QVBoxLayout(self)
        self.vnaGraphWindow = None
        self.createGroupVNAParameters()
        self.layout.addWidget(self.groupVNAParameters)
        self.layout.addSpacing(10)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupVNAParameters(self):
        self.groupVNAParameters = QGroupBox("Config")
        self.groupVNAParameters.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QFormLayout()

        self.vnaParameter = QComboBox(self)
        self.vnaParameter.addItems(state.VNA_SPARAMS)

        self.freqFromLabel = QLabel(self)
        self.freqFromLabel.setText("Freq start, GHz:")
        self.freqFrom = DoubleSpinBox(self)
        self.freqFrom.setRange(0.01, 67)
        self.freqFrom.setValue(state.VNA_FREQ_START)

        self.freqToLabel = QLabel(self)
        self.freqToLabel.setText("Freq stop, GHz:")
        self.freqTo = DoubleSpinBox(self)
        self.freqFrom.setRange(0.01, 67)
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

        self.vnaAverageCountLabel = QLabel(self)
        self.vnaAverageCountLabel.setText("Aver count:")
        self.vnaAverageCount = QSpinBox(self)
        self.vnaAverageCount.setRange(1, 1000)
        self.vnaAverageCount.setValue(10)

        self.vnaStoreData = QCheckBox(self)
        self.vnaStoreData.setText("Store Data")
        self.vnaStoreData.setChecked(state.VNA_STORE_DATA)

        self.btnConfigureVna = Button("Configure", animate=True)
        self.btnConfigureVna.clicked.connect(self.configure_vna)

        self.btnGetVnaData = Button("Get Data", animate=True)
        self.btnGetVnaData.clicked.connect(self.get_vna_data)

        layout.addRow("Parameter:", self.vnaParameter)
        layout.addRow(self.freqFromLabel, self.freqFrom)
        layout.addRow(self.freqToLabel, self.freqTo)
        layout.addRow(self.vnaPointsLabel, self.vnaPoints)
        layout.addRow(self.vnaPowerLabel, self.vnaPower)
        layout.addRow(self.vnaAverageCountLabel, self.vnaAverageCount)
        layout.addRow(self.vnaStoreData)
        layout.addRow(self.btnConfigureVna)
        layout.addRow(self.btnGetVnaData)

        self.groupVNAParameters.setLayout(layout)

    def configure_vna(self):
        self.vna_configure_thread = ConfigureVnaThread(
            cid=self.cid,
            start=self.freqFrom.value() * 1e9,
            stop=self.freqTo.value() * 1e9,
            points=self.vnaPoints.value(),
            parameter=self.vnaParameter.currentText(),
            power=self.vnaPower.value(),
            channel_format=state.VNA_CHANNEL_FORMAT,
            average_count=int(self.vnaAverageCount.value()),
        )
        self.vna_configure_thread.start()
        self.btnConfigureVna.setEnabled(False)
        self.vna_configure_thread.finished.connect(
            lambda: self.btnConfigureVna.setEnabled(True)
        )

    def get_vna_data(self):
        self.vna_get_reflection_thread = VnaGetDataThread(
            cid=self.cid, store_data=self.vnaStoreData.isChecked()
        )

        self.vnaGraphWindow = Dock.ex.dock_manager.findDockWidget("VNA P-F curve")
        self.vna_get_reflection_thread.results.connect(self.plot_vna_data)
        self.vna_get_reflection_thread.start()

        self.btnGetVnaData.setEnabled(False)
        self.vna_get_reflection_thread.finished.connect(
            lambda: self.btnGetVnaData.setEnabled(True)
        )

    def plot_vna_data(self, data):
        if self.vnaGraphWindow is None:
            return
        self.vnaGraphWindow.widget().plotNew(
            x=data.get("freq"),
            y=data.get("reflection"),
            measure_id=data.get("measure_id"),
            legend_postfix=f"{data.get('s_param')}; {data.get('power')} dBm",
        )
        self.vnaGraphWindow.widget().show()
