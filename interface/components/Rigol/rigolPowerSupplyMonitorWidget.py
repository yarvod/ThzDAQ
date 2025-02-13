import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QSizePolicy,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
)

from api.Rigol.DP832A import PowerSupplyDP832A
from store import RigolPowerSupplyManager
from interface.components.ui.Button import Button
from threads import Thread
from utils.exceptions import DeviceConnectionError


class StreamThread(Thread):
    measure_1 = Signal(list)
    voltage_sour_1 = Signal(float)
    current_sour_1 = Signal(float)
    output_1 = Signal(str)

    measure_2 = Signal(list)
    voltage_sour_2 = Signal(float)
    current_sour_2 = Signal(float)
    output_2 = Signal(str)

    measure_3 = Signal(list)
    voltage_sour_3 = Signal(float)
    current_sour_3 = Signal(float)
    output_3 = Signal(str)

    def __init__(self, cid: int):
        super().__init__()
        self.cid = cid
        self.config = RigolPowerSupplyManager.get_config(self.cid)
        self.rigol = None

    def run(self):
        try:
            self.rigol = PowerSupplyDP832A(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        while self.config.thread_stream:
            time.sleep(0.2)
            if self.config.monitor_ch1:
                measure_1 = self.rigol.measure_all(1)
                if len(measure_1) == 3:
                    self.measure_1.emit(measure_1)

                voltage_sour_1 = self.rigol.get_voltage(1)
                if voltage_sour_1:
                    self.voltage_sour_1.emit(voltage_sour_1)

                current_sour_1 = self.rigol.get_current(1)
                if current_sour_1:
                    self.current_sour_1.emit(current_sour_1)

                output1 = self.rigol.get_output(1)
                if output1:
                    self.output_1.emit(output1)

            if self.config.monitor_ch2:
                measure_2 = self.rigol.measure_all(2)
                if len(measure_2) == 3:
                    self.measure_2.emit(measure_2)

                voltage_sour_2 = self.rigol.get_voltage(2)
                if voltage_sour_2:
                    self.voltage_sour_2.emit(voltage_sour_2)

                current_sour_2 = self.rigol.get_current(2)
                if current_sour_2:
                    self.current_sour_2.emit(current_sour_2)

                output2 = self.rigol.get_output(2)
                if output2:
                    self.output_2.emit(output2)

            if self.config.monitor_ch3:
                measure_3 = self.rigol.measure_all(3)
                if len(measure_3) == 3:
                    self.measure_3.emit(measure_3)

                voltage_sour_3 = self.rigol.get_voltage(3)
                if voltage_sour_3:
                    self.voltage_sour_3.emit(voltage_sour_3)

                current_sour_3 = self.rigol.get_current(3)
                if current_sour_3:
                    self.current_sour_3.emit(current_sour_3)

                output3 = self.rigol.get_output(3)
                if output3:
                    self.output_3.emit(output3)

            if not any(
                (
                    self.config.monitor_ch1,
                    self.config.monitor_ch2,
                    self.config.monitor_ch3,
                )
            ):
                break

        self.pre_exit()
        self.finished.emit()


class MonitorWidget(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.setTitle("Monitor")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cid = cid
        self.config = RigolPowerSupplyManager.get_config(cid=self.cid)
        self.stream_thread = None
        layout = QVBoxLayout()
        glayout = QGridLayout()
        hlayout = QHBoxLayout()

        self.ch1Label = QCheckBox(self)
        self.ch1Label.setChecked(self.config.monitor_ch1)
        self.ch1Label.stateChanged.connect(self.set_monitor_ch1)
        self.ch1Label.setText("CH 1")
        self.ch1Label.setStyleSheet("color: black; font-size: 18px; font-weight: bold;")
        self.ch1Label.setToolTip("Monitor CH1")

        self.ch2Label = QCheckBox(self)
        self.ch2Label.setChecked(self.config.monitor_ch2)
        self.ch2Label.stateChanged.connect(self.set_monitor_ch2)
        self.ch2Label.setText("CH 2")
        self.ch2Label.setStyleSheet("color: black; font-size: 18px; font-weight: bold;")
        self.ch2Label.setToolTip("Monitor CH3")

        self.ch3Label = QCheckBox(self)
        self.ch3Label.setChecked(self.config.monitor_ch3)
        self.ch3Label.stateChanged.connect(self.set_monitor_ch3)
        self.ch3Label.setText("CH 3")
        self.ch3Label.setStyleSheet("color: black; font-size: 18px; font-weight: bold;")
        self.ch3Label.setToolTip("Monitor CH3")

        self.voltageSourLabel = QLabel(self)
        self.voltageSourLabel.setText("Voltage sour, V")
        self.currentSourLabel = QLabel(self)
        self.currentSourLabel.setText("Current sour, A")
        self.voltageLabel = QLabel(self)
        self.voltageLabel.setText("Voltage, V")
        self.currentLabel = QLabel(self)
        self.currentLabel.setText("Current, A")
        self.powerLabel = QLabel(self)
        self.powerLabel.setText("Power, W")

        self.voltageSour1 = QLabel(self)
        self.voltageSour1.setText("0.0")
        self.voltageSour1.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: black;"
        )

        self.voltage1 = QLabel(self)
        self.voltage1.setText("0.0")
        self.voltage1.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.currentSour1 = QLabel(self)
        self.currentSour1.setText("0.0")
        self.currentSour1.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: black;"
        )

        self.current1 = QLabel(self)
        self.current1.setText("0.0")
        self.current1.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.power1 = QLabel(self)
        self.power1.setText("0.0")
        self.power1.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.voltageSour2 = QLabel(self)
        self.voltageSour2.setText("0.0")
        self.voltageSour2.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: black;"
        )

        self.voltage2 = QLabel(self)
        self.voltage2.setText("0.0")
        self.voltage2.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.currentSour2 = QLabel(self)
        self.currentSour2.setText("0.0")
        self.currentSour2.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: black;"
        )

        self.current2 = QLabel(self)
        self.current2.setText("0.0")
        self.current2.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.power2 = QLabel(self)
        self.power2.setText("0.0")
        self.power2.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.voltageSour3 = QLabel(self)
        self.voltageSour3.setText("0.0")
        self.voltageSour3.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: black;"
        )

        self.voltage3 = QLabel(self)
        self.voltage3.setText("0.0")
        self.voltage3.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.currentSour3 = QLabel(self)
        self.currentSour3.setText("0.0")
        self.currentSour3.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: black;"
        )

        self.current3 = QLabel(self)
        self.current3.setText("0.0")
        self.current3.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.power3 = QLabel(self)
        self.power3.setText("0.0")
        self.power3.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")

        self.outputLabel = QLabel(self)
        self.outputLabel.setText("<h4>Output:</h4>")
        self.outputLabel.setStyleSheet("color: black;")
        self.output1 = QLabel(self)
        self.output1.setText("Undef")
        self.output1.setStyleSheet("color: black;")

        self.output2 = QLabel(self)
        self.output2.setText("Undef")
        self.output2.setStyleSheet("color: black;")

        self.output3 = QLabel(self)
        self.output3.setText("Undef")
        self.output3.setStyleSheet("color: black;")

        self.btnStartStream = Button("Start Stream", animate=True)
        self.btnStartStream.clicked.connect(self.start_stream)

        self.btnStopStream = Button("Stop Stream")
        self.btnStopStream.setEnabled(False)
        self.btnStopStream.clicked.connect(self.stop_stream)

        glayout.addWidget(self.ch1Label, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.ch2Label, 0, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.ch3Label, 0, 3, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(
            self.voltageSourLabel, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.currentSourLabel, 2, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.voltageLabel, 3, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.currentLabel, 4, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(self.powerLabel, 5, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(
            self.outputLabel, 6, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.voltageSour1, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.currentSour1, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(self.voltage1, 3, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.current1, 4, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.power1, 5, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.output1, 6, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(
            self.voltageSour2, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.currentSour2, 2, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(self.voltage2, 3, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.current2, 4, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.power2, 5, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.output2, 6, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(
            self.voltageSour3, 1, 3, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.currentSour3, 2, 3, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(self.voltage3, 3, 3, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.current3, 4, 3, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.power3, 5, 3, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.output3, 6, 3, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(glayout)

        hlayout.addWidget(self.btnStartStream)
        hlayout.addWidget(self.btnStopStream)
        layout.addLayout(hlayout)
        self.setLayout(layout)

    def start_stream(self):
        self.stream_thread = StreamThread(cid=self.cid)
        self.config.thread_stream = True

        self.stream_thread.measure_1.connect(self.set_measure_1)
        self.stream_thread.current_sour_1.connect(
            lambda x: self.currentSour1.setText(f"{round(x, 4)}")
        )
        self.stream_thread.voltage_sour_1.connect(
            lambda x: self.voltageSour1.setText(f"{round(x, 4)}")
        )
        self.stream_thread.output_1.connect(self.set_output_1)

        self.stream_thread.measure_2.connect(self.set_measure_2)
        self.stream_thread.current_sour_2.connect(
            lambda x: self.currentSour2.setText(f"{round(x, 4)}")
        )
        self.stream_thread.voltage_sour_2.connect(
            lambda x: self.voltageSour2.setText(f"{round(x, 4)}")
        )
        self.stream_thread.output_2.connect(self.set_output_2)

        self.stream_thread.measure_3.connect(self.set_measure_3)
        self.stream_thread.current_sour_3.connect(
            lambda x: self.currentSour3.setText(f"{round(x, 4)}")
        )
        self.stream_thread.voltage_sour_3.connect(
            lambda x: self.voltageSour3.setText(f"{round(x, 4)}")
        )
        self.stream_thread.output_3.connect(self.set_output_3)
        self.stream_thread.start()

        self.btnStartStream.setEnabled(False)
        self.stream_thread.finished.connect(
            lambda: self.btnStartStream.setEnabled(True)
        )

        self.btnStopStream.setEnabled(True)
        self.stream_thread.finished.connect(
            lambda: self.btnStopStream.setEnabled(False)
        )

    def stop_stream(self):
        config = RigolPowerSupplyManager.get_config(cid=self.cid)
        config.thread_stream = False

    def set_output_1(self, output: str):
        out = "On" if output == "ON" else "Off"
        color = "green" if output == "ON" else "red"
        self.output1.setText(out)
        self.output1.setStyleSheet(f"color: {color};")

    def set_output_2(self, output: str):
        out = "On" if output == "ON" else "Off"
        color = "green" if output == "ON" else "red"
        self.output2.setText(out)
        self.output2.setStyleSheet(f"color: {color};")

    def set_output_3(self, output: str):
        out = "On" if output == "ON" else "Off"
        color = "green" if output == "ON" else "red"
        self.output3.setText(out)
        self.output3.setStyleSheet(f"color: {color};")

    def set_measure_1(self, measure):
        voltage, current, power = measure
        self.voltage1.setText(f"{voltage:.4}")
        self.current1.setText(f"{current:.4}")
        self.power1.setText(f"{power:.4}")

    def set_measure_2(self, measure):
        voltage, current, power = measure
        self.voltage2.setText(f"{voltage:.4}")
        self.current2.setText(f"{current:.4}")
        self.power2.setText(f"{power:.4}")

    def set_measure_3(self, measure):
        voltage, current, power = measure
        self.voltage3.setText(f"{voltage:.4}")
        self.current3.setText(f"{current:.4}")
        self.power3.setText(f"{power:.4}")

    def set_monitor_ch1(self, value):
        self.config.monitor_ch1 = value

    def set_monitor_ch2(self, value):
        self.config.monitor_ch2 = value

    def set_monitor_ch3(self, value):
        self.config.monitor_ch3 = value
