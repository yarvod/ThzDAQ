from PyQt6.QtCore import QObject, pyqtSignal, Qt, QThread
from PyQt6.QtWidgets import QGroupBox, QGridLayout, QVBoxLayout, QWidget, QLabel, QPushButton

from config import config
from interactors.rs_nrx import NRXBlock


class NRXBlockStreamWorker(QObject):
    finished = pyqtSignal()
    power = pyqtSignal(float)

    def run(self):
        block = NRXBlock(
            ip=config.NRX_IP,
            filter_time=config.NRX_FILTER_TIME,
            aperture_time=config.NRX_APER_TIME,
        )
        while config.NRX_STREAM:
            power = block.get_power()
            self.power.emit(power)
        block.close()
        self.finished.emit()


class NRXTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.createGroupNRX()
        self.layout.addWidget(self.groupNRX)
        self.setLayout(self.layout)

    def createGroupNRX(self):
        self.groupNRX = QGroupBox("NRX monitor")
        layout = QGridLayout()

        self.nrxPowerLabel = QLabel("<h4>Power, dBm</h4>")
        self.nrxPower = QLabel(self)
        self.nrxPower.setText("0.0")
        self.nrxPower.setStyleSheet("font-size: 23px; font-weight: bold;")

        self.btnStartStreamNRX = QPushButton("Start Stream")
        self.btnStartStreamNRX.clicked.connect(self.start_stream_nrx)

        self.btnStopStreamNRX = QPushButton("Stop Stream")
        self.btnStopStreamNRX.setEnabled(False)
        self.btnStopStreamNRX.clicked.connect(self.stop_stream_nrx)

        layout.addWidget(
            self.nrxPowerLabel, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(self.nrxPower, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            self.btnStartStreamNRX, 2, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self.btnStopStreamNRX, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.groupNRX.setLayout(layout)

    def start_stream_nrx(self):
        self.nrx_stream_thread = QThread()
        self.nrx_stream_worker = NRXBlockStreamWorker()
        self.nrx_stream_worker.moveToThread(self.nrx_stream_thread)

        config.NRX_STREAM = True

        self.nrx_stream_thread.started.connect(self.nrx_stream_worker.run)
        self.nrx_stream_worker.finished.connect(self.nrx_stream_thread.quit)
        self.nrx_stream_worker.finished.connect(self.nrx_stream_worker.deleteLater)
        self.nrx_stream_thread.finished.connect(self.nrx_stream_thread.deleteLater)
        self.nrx_stream_worker.power.connect(
            lambda x: self.nrxPower.setText(f"{round(x, 3)}")
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

    def stop_stream_nrx(self):
        config.NRX_STREAM = False
