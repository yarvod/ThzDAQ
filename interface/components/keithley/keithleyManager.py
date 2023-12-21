from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QSizePolicy,
)

from api.Keithley import PowerSupply
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store import KeithleyPowerSupplyManager
from threads import Thread
from utils.exceptions import DeviceConnectionError


class ThreadSetOutput(Thread):
    def __init__(self, cid: int, value: int):
        super().__init__()
        self.cid = cid
        self.value = value
        self.config = KeithleyPowerSupplyManager.get_config(self.cid)
        self.keithley = None

    def run(self):
        try:
            self.keithley = PowerSupply(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        self.keithley.set_output_state(self.value)

        self.pre_exit()
        self.finished.emit()

    # def pre_exit(self, *args, **kwargs):
    #     if self.keithley:
    #         self.keithley.adapter.close()


class ThreadSetVoltage(Thread):
    def __init__(self, cid: int, value: float):
        super().__init__()
        self.cid = cid
        self.value = value
        self.config = KeithleyPowerSupplyManager.get_config(self.cid)
        self.keithley = None

    def run(self):
        try:
            self.keithley = PowerSupply(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        self.keithley.set_voltage(self.value)

        self.pre_exit()
        self.finished.emit()

    # def pre_exit(self, *args, **kwargs):
    #     if self.keithley:
    #         self.keithley.adapter.close()


class ThreadSetCurrent(Thread):
    def __init__(self, cid: int, value: float):
        super().__init__()
        self.cid = cid
        self.value = value
        self.config = KeithleyPowerSupplyManager.get_config(self.cid)
        self.keithley = None

    def run(self):
        try:
            self.keithley = PowerSupply(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        self.keithley.set_current(self.value)

        self.pre_exit()
        self.finished.emit()

    # def pre_exit(self, *args, **kwargs):
    #     if self.keithley:
    #         self.keithley.adapter.close()


class KeitleyManagerWidget(QGroupBox):
    def __init__(self, parent, cid: int):
        super(KeitleyManagerWidget, self).__init__(parent)
        self.setTitle("Manager")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cid = cid
        self.set_output_thread = None
        self.set_voltage_thread = None
        self.set_current_thread = None
        layout = QVBoxLayout()
        glayout = QGridLayout()

        self.outputLabel = QLabel(self)
        self.outputLabel.setText("Output:")
        self.output = QComboBox(self)
        self.output.addItems(["On", "Off"])
        self.btnSetOutput = Button("Set output", animate=True)
        self.btnSetOutput.clicked.connect(self.set_output)

        self.voltageLabel = QLabel(self)
        self.voltageLabel.setText("Voltage, V:")
        self.voltage = DoubleSpinBox(self)
        self.voltage.setRange(0, 30)
        self.voltage.setDecimals(4)
        self.voltage.setValue(0)
        self.btnSetVoltage = Button("Set voltage", animate=True)
        self.btnSetVoltage.clicked.connect(self.set_voltage)

        self.currentLabel = QLabel(self)
        self.currentLabel.setText("Current, A:")
        self.current = DoubleSpinBox(self)
        self.current.setRange(0, 5)
        self.current.setDecimals(4)
        self.current.setValue(0)
        self.btnSetCurrent = Button("Set current", animate=True)
        self.btnSetCurrent.clicked.connect(self.set_current)

        glayout.addWidget(self.outputLabel, 0, 0)
        glayout.addWidget(self.output, 0, 1)
        glayout.addWidget(self.btnSetOutput, 0, 2)

        glayout.addWidget(self.voltageLabel, 1, 0)
        glayout.addWidget(self.voltage, 1, 1)
        glayout.addWidget(self.btnSetVoltage, 1, 2)

        glayout.addWidget(self.currentLabel, 2, 0)
        glayout.addWidget(self.current, 2, 1)
        glayout.addWidget(self.btnSetCurrent, 2, 2)

        layout.addLayout(glayout)
        self.setLayout(layout)

    def set_output(self):
        output = 1 if self.output.currentText() == "On" else 0
        self.set_output_thread = ThreadSetOutput(cid=self.cid, value=output)
        self.set_output_thread.finished.connect(
            lambda: self.btnSetOutput.setEnabled(True)
        )
        self.btnSetOutput.setEnabled(False)
        self.set_output_thread.start()

    def set_voltage(self):
        self.set_voltage_thread = ThreadSetVoltage(
            cid=self.cid, value=self.voltage.value()
        )
        self.set_voltage_thread.finished.connect(
            lambda: self.btnSetVoltage.setEnabled(True)
        )
        self.btnSetVoltage.setEnabled(False)
        self.set_voltage_thread.start()

    def set_current(self):
        self.set_current_thread = ThreadSetCurrent(
            cid=self.cid, value=self.current.value()
        )
        self.set_current_thread.finished.connect(
            lambda: self.btnSetCurrent.setEnabled(True)
        )
        self.btnSetCurrent.setEnabled(False)
        self.set_current_thread.start()
