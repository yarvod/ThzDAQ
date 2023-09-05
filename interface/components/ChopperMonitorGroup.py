import time

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import QGroupBox, QPushButton, QVBoxLayout, QLabel, QGridLayout

from api.Chopper.chopper_sync import chopper


class ChopperRotateThread(QThread):
    def run(self):
        if not chopper.client.connected:
            self.finished.emit()
            return
        chopper.path0()
        self.finished.emit()


class ChopperSetZeroThread(QThread):
    def run(self):
        if not chopper.client.connected:
            self.finished.emit()
            return
        chopper.align()
        chopper.set_origin()
        chopper.go_to_pos(0)
        self.finished.emit()


class ChopperMonitorThread(QThread):
    position = pyqtSignal(int)

    def run(self):
        if not chopper.client.connected:
            self.finished.emit()
            return
        while 1:
            pos = chopper.get_actual_pos()
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
        self.btnSetZero = QPushButton("New zero")
        self.btnSetZero.clicked.connect(self.setZero)

        self.btnStartMonitor = QPushButton("Start monitor")
        self.btnStartMonitor.clicked.connect(self.startMonitor)
        self.btnStopMonitor = QPushButton("Stop monitor")
        self.btnStopMonitor.clicked.connect(self.stopMonitor)
        self.btnStopMonitor.setEnabled(False)

        self.btnRotate = QPushButton("Rotate")
        self.btnRotate.clicked.connect(self.rotate)

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

        layout.addWidget(self.btnRotate)

        self.setLayout(layout)

    def rotate(self):
        self.btnRotate.setEnabled(False)
        self.chopper_thread = ChopperRotateThread()
        self.chopper_thread.finished.connect(lambda: self.btnRotate.setEnabled(True))
        self.chopper_thread.start()

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
        self.chopper_monitor_thread.position.connect(
            lambda pos: self.currentPosition.setText(f"{pos}")
        )
        self.chopper_monitor_thread.finished.connect(
            lambda: self.btnStartMonitor.setEnabled(True)
        )
        self.chopper_monitor_thread.finished.connect(
            lambda: self.btnStopMonitor.setEnabled(False)
        )

    def stopMonitor(self):
        self.chopper_monitor_thread.terminate()
