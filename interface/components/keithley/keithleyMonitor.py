import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QGroupBox,
    QSizePolicy,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
)

from api.Keithley import PowerSupply
from store import KeithleyPowerSupplyManager
from interface.components.ui.Button import Button
from threads import Thread
from utils.exceptions import DeviceConnectionError


class KeithleyStreamThread(Thread):
    current = pyqtSignal(float)
    voltage = pyqtSignal(float)
    sour_current = pyqtSignal(float)
    sour_voltage = pyqtSignal(float)
    output = pyqtSignal(str)

    def __init__(self, cid: int):
        super().__init__()
        self.cid = cid
        self.config = KeithleyPowerSupplyManager.get_config(self.cid)
        self.keithley = None

    def run(self):
        try:
            self.keithley = PowerSupply(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        while self.config.thread_stream:
            time.sleep(0.2)
            sour_voltage = self.keithley.get_sour_voltage()
            if sour_voltage:
                self.sour_voltage.emit(sour_voltage)

            voltage = self.keithley.get_voltage()
            if voltage:
                self.voltage.emit(voltage)

            sour_current = self.keithley.get_sour_current()
            if sour_current:
                self.sour_current.emit(sour_current)

            current = self.keithley.get_current()
            if current:
                self.current.emit(current)

            output = self.keithley.get_output_state()
            if output:
                self.output.emit(output)

            if not any((sour_voltage, voltage, sour_current, current)):
                break

        self.pre_exit()
        self.finished.emit()

    # def pre_exit(self, *args, **kwargs):
    #     if self.keithley:
    #         self.keithley.adapter.close()


class KeithleyMonitor(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.setTitle("Monitor")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cid = cid
        layout = QVBoxLayout()
        glayout = QGridLayout()
        state_layout = QFormLayout()
        hlayout = QHBoxLayout()

        self.keithleyVoltageSourLabel = QLabel(self)
        self.keithleyVoltageSourLabel.setText("<h4>Voltage sour, V</h4>")
        self.keithleyVoltageSourLabel.setStyleSheet("color: black;")
        self.keithleyVoltageSour = QLabel(self)
        self.keithleyVoltageSour.setText("0.0")
        self.keithleyVoltageSour.setStyleSheet(
            "font-size: 23px; font-weight: bold; color: black;"
        )

        self.keithleyVoltageGetLabel = QLabel(self)
        self.keithleyVoltageGetLabel.setText("<h4>Voltage, V</h4>")
        self.keithleyVoltageGetLabel.setStyleSheet("color: black;")
        self.keithleyVoltageGet = QLabel(self)
        self.keithleyVoltageGet.setText("0.0")
        self.keithleyVoltageGet.setStyleSheet(
            "font-size: 23px; font-weight: bold; color: black;"
        )

        self.keithleyCurrentSourLabel = QLabel(self)
        self.keithleyCurrentSourLabel.setText("<h4>Current sour, A</h4>")
        self.keithleyCurrentSourLabel.setStyleSheet("color: black;")
        self.keithleyCurrentSour = QLabel(self)
        self.keithleyCurrentSour.setText("0.0")
        self.keithleyCurrentSour.setStyleSheet(
            "font-size: 23px; font-weight: bold; color: black;"
        )

        self.keithleyCurrentGetLabel = QLabel(self)
        self.keithleyCurrentGetLabel.setText("<h4>Current, A</h4>")
        self.keithleyCurrentGetLabel.setStyleSheet("color: black;")
        self.keithleyCurrentGet = QLabel(self)
        self.keithleyCurrentGet.setText("0.0")
        self.keithleyCurrentGet.setStyleSheet(
            "font-size: 23px; font-weight: bold; color: black;"
        )

        self.keithleyOutputLabel = QLabel(self)
        self.keithleyOutputLabel.setText("<h4>Output:</h4>")
        self.keithleyOutputLabel.setStyleSheet("color: black;")
        self.keithleyOutput = QLabel(self)
        self.keithleyOutput.setText("Undef")
        self.keithleyOutput.setStyleSheet("color: black;")

        self.btnStartStreamKeithley = Button("Start Stream", animate=True)
        self.btnStartStreamKeithley.clicked.connect(self.start_stream_keithley)

        self.btnStopStreamKeithley = Button("Stop Stream")
        self.btnStopStreamKeithley.setEnabled(False)
        self.btnStopStreamKeithley.clicked.connect(self.stop_stream_keithley)

        glayout.addWidget(
            self.keithleyVoltageSourLabel, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyVoltageGetLabel, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyCurrentSourLabel, 0, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyCurrentGetLabel, 0, 3, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyVoltageSour, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyVoltageGet, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyCurrentSour, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyCurrentGet, 1, 3, alignment=Qt.AlignmentFlag.AlignCenter
        )

        layout.addLayout(glayout)

        state_layout.addRow(self.keithleyOutputLabel, self.keithleyOutput)
        layout.addLayout(state_layout)

        hlayout.addWidget(self.btnStartStreamKeithley)
        hlayout.addWidget(self.btnStopStreamKeithley)
        layout.addLayout(hlayout)
        self.setLayout(layout)

    def start_stream_keithley(self):
        self.keithley_stream_thread = KeithleyStreamThread(cid=self.cid)
        config = KeithleyPowerSupplyManager.get_config(cid=self.cid)
        config.thread_stream = True

        self.keithley_stream_thread.current.connect(
            lambda x: self.keithleyCurrentGet.setText(f"{round(x, 4)}")
        )
        self.keithley_stream_thread.sour_current.connect(
            lambda x: self.keithleyCurrentSour.setText(f"{round(x, 4)}")
        )
        self.keithley_stream_thread.voltage.connect(
            lambda x: self.keithleyVoltageGet.setText(f"{round(x, 4)}")
        )
        self.keithley_stream_thread.sour_voltage.connect(
            lambda x: self.keithleyVoltageSour.setText(f"{round(x, 4)}")
        )
        self.keithley_stream_thread.output.connect(self.set_output)
        self.keithley_stream_thread.start()

        self.btnStartStreamKeithley.setEnabled(False)
        self.keithley_stream_thread.finished.connect(
            lambda: self.btnStartStreamKeithley.setEnabled(True)
        )

        self.btnStopStreamKeithley.setEnabled(True)
        self.keithley_stream_thread.finished.connect(
            lambda: self.btnStopStreamKeithley.setEnabled(False)
        )

    def stop_stream_keithley(self):
        config = KeithleyPowerSupplyManager.get_config(cid=self.cid)
        config.thread_stream = False

    def set_output(self, output: str):
        out = "On" if output == "1" else "Off"
        color = "green" if output == "1" else "red"
        self.keithleyOutput.setText(out)
        self.keithleyOutput.setStyleSheet(f"color: {color};")
