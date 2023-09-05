import time

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import QGroupBox, QPushButton, QVBoxLayout, QLabel, QGridLayout

from api.Chopper.chopper_sync import ChopperManager


class ChopperSetZeroThread(QThread):
    def run(self):
        if not ChopperManager.chopper.client.connected:
            self.finished.emit()
            return
        ChopperManager.chopper.align()
        ChopperManager.chopper.set_origin()
        ChopperManager.chopper.go_to_pos(0)
        self.finished.emit()


class ChopperMonitorThread(QThread):
    position = pyqtSignal(int)

    def run(self):
        if not ChopperManager.chopper.client.connected:
            self.finished.emit()
            return
        while 1:
            pos = ChopperManager.chopper.get_actual_pos()
            self.position.emit(pos)
            time.sleep(0.2)


class ChopperMonitorGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Monitor")
        layout = QVBoxLayout(self)
        grid_layout = QGridLayout()

        self.currentPositionLabel = QLabel(self)
        self.currentPositionLabel.setText("Position:")
        self.currentPosition = QLabel(self)
        self.currentPosition.setText("Undefined")
        self.currentPosition.setStyleSheet("font-size: 20px; color: #1d1128;")
        self.btnSetZero = QPushButton("New zero")
        self.btnSetZero.clicked.connect(self.setZero)

        self.btnStartMonitor = QPushButton("Start monitor")
        self.btnStartMonitor.clicked.connect(self.startMonitor)
        self.btnStopMonitor = QPushButton("Stop monitor")
        self.btnStopMonitor.clicked.connect(self.stopMonitor)
        self.btnStopMonitor.setEnabled(False)

        grid_layout.addWidget(
            self.currentPositionLabel, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid_layout.addWidget(
            self.currentPosition, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid_layout.addWidget(self.btnSetZero, 0, 2)
        grid_layout.addWidget(self.btnStartMonitor, 1, 0)
        grid_layout.addWidget(self.btnStopMonitor, 1, 2)
        layout.addLayout(grid_layout)

        self.setLayout(layout)

    def setZero(self):
        self.btnSetZero.setEnabled(False)
        self.chopper_zero_thread = ChopperSetZeroThread()
        self.chopper_zero_thread.finished.connect(
            lambda: self.btnSetZero.setEnabled(True)
        )
        self.chopper_zero_thread.start()

    def startMonitor(self):
        self.chopper_monitor_thread = ChopperMonitorThread()
        self.chopper_monitor_thread.start()
        self.btnStartMonitor.setEnabled(False)
        self.btnStopMonitor.setEnabled(True)
        self.chopper_monitor_thread.position.connect(self.setCurrentPosition)
        self.chopper_monitor_thread.finished.connect(
            lambda: self.btnStartMonitor.setEnabled(True)
        )
        self.chopper_monitor_thread.finished.connect(
            lambda: self.btnStopMonitor.setEnabled(False)
        )

    def setCurrentPosition(self, position: int):
        degree = (360 * position // 10000) % 360
        minutes = int(60 * (position % 10) / 10)
        self.currentPosition.setText(f"{degree} ° {minutes} `")

    def stopMonitor(self):
        self.chopper_monitor_thread.terminate()
