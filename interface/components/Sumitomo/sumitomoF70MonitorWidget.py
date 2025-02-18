import time
from typing import Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QSizePolicy,
    QGroupBox,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QGridLayout,
)

from api import F70Rest
from interface.components.ui.Button import Button
from store import SumitomoF70Manager
from threads import Thread


class StreamThread(Thread):
    stream_temperatures = Signal(dict)

    def __init__(self, cid):
        super().__init__()
        self.config = SumitomoF70Manager.get_config(cid)

    def run(self):
        compressor = F70Rest(**self.config.dict())
        self.config.thread_stream = True
        while self.config.thread_stream:
            raw_data = compressor.get_temperatures()
            if raw_data.get("error"):
                self.finished.emit()
                return
            temps = raw_data.get("temperatures", [])
            if len(temps) >= 3:
                self.stream_temperatures.emit(
                    {
                        "t1": temps[0],
                        "t2": temps[1],
                        "t3": temps[2],
                    }
                )
            time.sleep(0.5)
        self.finished.emit()

    def pre_exit(self):
        self.config.thread_stream = False


class SumitomoF70MonitorWidget(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.setTitle("Monitor")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cid = cid

        layout = QVBoxLayout()
        glayout = QGridLayout()
        hlayout = QHBoxLayout()

        self.temp1Label = QLabel(self)
        self.temp1Label.setText("T1,°C")
        self.temp1Label.setToolTip("Temperature of Helium container. 93°C is Danger!")
        self.temp1 = QLabel(self)
        self.temp1.setText("Unknown")
        self.temp1.setToolTip("Temperature of Helium container. 93°C is Danger!")

        self.temp2Label = QLabel(self)
        self.temp2Label.setText("T2,°C")
        self.temp2Label.setToolTip("Temperature of Output water.")
        self.temp2 = QLabel(self)
        self.temp2.setText("Unknown")
        self.temp2.setToolTip("Temperature of Output water.")

        self.temp3Label = QLabel(self)
        self.temp3Label.setText("T3,°C")
        self.temp3Label.setToolTip("Temperature of Input water.")
        self.temp3 = QLabel(self)
        self.temp3.setText("Unknown")
        self.temp3.setToolTip("Temperature of Input water.")

        self.btnStartStream = Button(animate=True)
        self.btnStartStream.setText("Start Stream")
        self.btnStartStream.clicked.connect(self.start_stream)

        self.btnStopStream = Button(animate=False)
        self.btnStopStream.setText("Stop")
        self.btnStopStream.clicked.connect(self.stop_stream)

        glayout.addWidget(self.temp1Label, 0, 0)
        glayout.addWidget(self.temp1, 1, 0)
        glayout.addWidget(self.temp2Label, 0, 1)
        glayout.addWidget(self.temp2, 1, 1)
        glayout.addWidget(self.temp3Label, 0, 2)
        glayout.addWidget(self.temp3, 1, 2)

        hlayout.addWidget(self.btnStartStream)
        hlayout.addWidget(self.btnStopStream)

        layout.addLayout(glayout)
        layout.addLayout(hlayout)
        self.setLayout(layout)

    def start_stream(self):
        self.thread_stream = StreamThread(cid=self.cid)
        self.thread_stream.start()
        self.btnStartStream.setEnabled(False)
        self.btnStopStream.setEnabled(True)
        self.thread_stream.finished.connect(
            lambda: self.btnStartStream.setEnabled(True)
        )
        self.thread_stream.finished.connect(
            lambda: self.btnStopStream.setEnabled(False)
        )
        self.thread_stream.stream_temperatures.connect(self.set_temperatures)

    def stop_stream(self):
        self.thread_stream.quit()

    def set_temperatures(self, temps: Dict):
        self.temp1.setText(f"{temps['t1']}")
        self.temp2.setText(f"{temps['t2']}")
        self.temp3.setText(f"{temps['t3']}")
