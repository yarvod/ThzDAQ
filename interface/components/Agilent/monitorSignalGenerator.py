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

from api.Agilent.signal_generator import SignalGenerator
from store import AgilentSignalGeneratorManager
from interface.components.ui.Button import Button
from threads import Thread
from utils.exceptions import DeviceConnectionError


class StreamThread(Thread):
    amplitude = pyqtSignal(float)
    frequency = pyqtSignal(float)
    output = pyqtSignal(bool)

    def __init__(self, cid: int):
        super().__init__()
        self.cid = cid
        self.config = AgilentSignalGeneratorManager.get_config(self.cid)
        self.signal = None

    def run(self):
        try:
            self.signal = SignalGenerator(**self.config.dict())
        except DeviceConnectionError:
            self.finished.emit()
            return

        while self.config.thread_stream:
            time.sleep(0.5)
            frequency = self.signal.get_frequency()
            if frequency:
                self.frequency.emit(frequency)

            amplitude = self.signal.get_power()
            if amplitude:
                self.amplitude.emit(amplitude)

            output = self.signal.get_rf_output_state()
            if output is not None:
                self.output.emit(output)

            if not any((frequency, amplitude, output)):
                break

        self.pre_exit()
        self.finished.emit()


class AgilentSignalGeneratorMonitorWidget(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.setTitle("Monitor")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cid = cid
        self.stream_thread = None
        layout = QVBoxLayout()
        glayout = QGridLayout()
        state_layout = QFormLayout()
        hlayout = QHBoxLayout()

        self.frequencyLabel = QLabel(self)
        self.frequencyLabel.setText("<h4>Frequency, GHz</h4>")
        self.frequencyLabel.setStyleSheet("color: black;")
        self.frequency = QLabel(self)
        self.frequency.setText("0.0")
        self.frequency.setStyleSheet(
            "font-size: 23px; font-weight: bold; color: black;"
        )

        self.amplitudeLabel = QLabel(self)
        self.amplitudeLabel.setText("<h4>Amplitude, dBm</h4>")
        self.amplitudeLabel.setStyleSheet("color: black;")
        self.amplitude = QLabel(self)
        self.amplitude.setText("0.0")
        self.amplitude.setStyleSheet(
            "font-size: 23px; font-weight: bold; color: black;"
        )

        self.RfOutputLabel = QLabel(self)
        self.RfOutputLabel.setText("<h4>RF Output:</h4>")
        self.RfOutputLabel.setStyleSheet("color: black;")
        self.rfOutput = QLabel(self)
        self.rfOutput.setText("Undef")
        self.rfOutput.setStyleSheet("color: black;")

        self.btnStartStream = Button("Start Stream", animate=True)
        self.btnStartStream.clicked.connect(self.start_stream)

        self.btnStopStream = Button("Stop Stream")
        self.btnStopStream.setEnabled(False)
        self.btnStopStream.clicked.connect(self.stop_stream)

        glayout.addWidget(
            self.frequencyLabel, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(
            self.amplitudeLabel, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        glayout.addWidget(self.frequency, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        glayout.addWidget(self.amplitude, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(glayout)

        state_layout.addRow(self.RfOutputLabel, self.rfOutput)
        layout.addLayout(state_layout)

        hlayout.addWidget(self.btnStartStream)
        hlayout.addWidget(self.btnStopStream)
        layout.addLayout(hlayout)
        self.setLayout(layout)

    def start_stream(self):
        self.stream_thread = StreamThread(cid=self.cid)
        config = AgilentSignalGeneratorManager.get_config(cid=self.cid)
        config.thread_stream = True

        self.stream_thread.amplitude.connect(
            lambda x: self.amplitude.setText(f"{round(x, 4)}")
        )
        self.stream_thread.frequency.connect(
            lambda x: self.frequency.setText(f"{round(x * 1e-9, 4)}")
        )
        self.stream_thread.output.connect(self.set_output)
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
        config = AgilentSignalGeneratorManager.get_config(cid=self.cid)
        config.thread_stream = False

    def set_output(self, output: bool):
        out = "On" if output else "Off"
        color = "green" if output else "red"
        self.rfOutput.setText(out)
        self.rfOutput.setStyleSheet(f"color: {color};")
