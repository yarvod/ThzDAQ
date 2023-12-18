import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QGroupBox,
    QSizePolicy,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
)

from api.Keithley import PowerSupply
from store import KeithleyPowerSupplyManager
from interface.components.ui.Button import Button
from threads import Thread


class KeithleyStreamThread(Thread):
    current_get = pyqtSignal(float)
    voltage_get = pyqtSignal(float)

    def __init__(self, cid: int):
        super().__init__()
        self.cid = cid
        self.config = KeithleyPowerSupplyManager.get_config(self.cid)
        self.keithley = PowerSupply(**self.config.dict())

    def run(self):
        while self.config.thread_stream:
            time.sleep(0.2)
            current_get = self.keithley.get_current()
            self.current_get.emit(current_get)
            voltage_get = self.keithley.get_voltage()
            self.voltage_get.emit(voltage_get)
        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        self.keithley.adapter.close()


class KeithleyMonitor(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.setTitle("Monitor")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cid = cid
        layout = QVBoxLayout()
        glayout = QGridLayout()
        hlayout = QHBoxLayout()

        self.keithleyVoltageGetLabel = QLabel(self)
        self.keithleyVoltageGetLabel.setText("<h4>Voltage, V</h4>")
        self.keithleyVoltageGetLabel.setStyleSheet("color: black;")
        self.keithleyVoltageGet = QLabel(self)
        self.keithleyVoltageGet.setText("0.0")
        self.keithleyVoltageGet.setStyleSheet(
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

        self.btnStartStreamKeithley = Button("Start Stream", animate=True)
        self.btnStartStreamKeithley.clicked.connect(self.start_stream_keithley)

        self.btnStopStreamKeithley = Button("Stop Stream")
        self.btnStopStreamKeithley.setEnabled(False)
        self.btnStopStreamKeithley.clicked.connect(self.stop_stream_keithley)

        glayout.addWidget(
            self.keithleyVoltageGetLabel, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyCurrentGetLabel, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyVoltageGet, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.keithleyCurrentGet, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addLayout(glayout)

        hlayout.addWidget(self.btnStartStreamKeithley)
        hlayout.addWidget(self.btnStopStreamKeithley)
        layout.addLayout(hlayout)
        self.setLayout(layout)

    def start_stream_keithley(self):
        self.keithley_stream_thread = KeithleyStreamThread(cid=self.cid)
        config = KeithleyPowerSupplyManager.get_config(cid=self.cid)
        config.thread_stream = True

        self.keithley_stream_thread.current_get.connect(
            lambda x: self.keithleyCurrentGet.setText(f"{round(x, 4)}")
        )
        self.keithley_stream_thread.voltage_get.connect(
            lambda x: self.keithleyVoltageGet.setText(f"{round(x, 4)}")
        )
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
