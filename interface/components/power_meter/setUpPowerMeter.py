import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QSizePolicy,
    QLabel,
    QLineEdit,
    QComboBox,
    QFormLayout,
)

from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store.powerMeterUnitsModel import power_meter_unit_model
from store.state import state
from utils.exceptions import DeviceConnectionError

logger = logging.getLogger(__name__)


class NRXBlockThread(QThread):
    status = Signal(str)

    def run(self):
        logger.info(f"[{self.__class__.__name__}.run] Running...")
        try:
            block = NRXPowerMeter(
                host=state.NRX_IP,
                aperture_time=state.NRX_APER_TIME,
                delay=0,
            )
            block.set_power_units(state.NRX_UNIT)
            result = block.test()
            self.status.emit(state.NRX_TEST_MAP.get(result, "Error"))
        except DeviceConnectionError:
            self.status.emit("Connection Error!")
        self.finished.emit()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")

    def quit(self) -> None:
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")


class SetUpPowerMeter(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Power meter")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QFormLayout()

        self.nrxIPLabel = QLabel(self)
        self.nrxIPLabel.setText("IP Address:")
        self.nrxIP = QLineEdit(self)
        self.nrxIP.setText(state.NRX_IP)

        self.nrxAperTimeLabel = QLabel(self)
        self.nrxAperTimeLabel.setText("Averaging time, ms:")
        self.nrxAperTime = DoubleSpinBox(self)
        self.nrxAperTime.setDecimals(2)
        self.nrxAperTime.setRange(0.01, 10000)
        self.nrxAperTime.setValue(state.NRX_APER_TIME)

        self.nrxUnitsLabel = QLabel(self)
        self.nrxUnitsLabel.setText("Power Units:")
        self.nrxUnits = QComboBox(self)
        self.nrxUnits.addItems(list(state.NRX_UNITS.values()))

        self.nrxStatusLabel = QLabel(self)
        self.nrxStatusLabel.setText("Status:")
        self.nrxStatus = QLabel(self)
        self.nrxStatus.setText("Doesn't initialized yet!")

        self.btnInitNRX = Button("Initialize", animate=True)
        self.btnInitNRX.clicked.connect(self.initialize_nrx)

        layout.addRow(self.nrxIPLabel, self.nrxIP)
        layout.addRow(self.nrxAperTimeLabel, self.nrxAperTime)
        layout.addRow(self.nrxUnitsLabel, self.nrxUnits)
        layout.addRow(self.nrxStatusLabel, self.nrxStatus)
        layout.addRow(self.btnInitNRX)

        self.setLayout(layout)

    def initialize_nrx(self):
        self.nrx_thread = NRXBlockThread()
        self.nrx_thread.status.connect(lambda x: self.nrxStatus.setText(x))
        state.NRX_IP = self.nrxIP.text()
        state.NRX_APER_TIME = self.nrxAperTime.value()
        state.NRX_UNIT = state.NRX_UNITS_REVERSE.get(self.nrxUnits.currentText(), "DBM")
        power_meter_unit_model.set_value(state.NRX_UNIT)
        self.nrx_thread.start()

        self.btnInitNRX.setEnabled(False)
        self.nrx_thread.finished.connect(lambda: self.btnInitNRX.setEnabled(True))
