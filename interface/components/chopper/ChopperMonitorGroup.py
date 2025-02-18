import time

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QGridLayout

from api.Chopper import chopper_manager
from interface.components.ui.Button import Button
from store.state import state


class ChopperSetZeroThread(QThread):
    def run(self):
        if not chopper_manager.chopper.client.connected:
            self.finished.emit()
            return
        chopper_manager.chopper.align()
        chopper_manager.chopper.set_origin()
        chopper_manager.chopper.go_to_pos(0)
        self.finished.emit()


class ChopperMonitorThread(QThread):
    position = Signal(int)
    speed = Signal(float)

    def run(self):
        if not chopper_manager.chopper.client.connected:
            self.finished.emit()
            return
        while state.CHOPPER_MONITOR:
            if not chopper_manager.chopper.client.connected:
                self.finished.emit()
                return
            pos = chopper_manager.chopper.get_actual_pos()
            # speed = chopper_manager.chopper.get_actual_speed()
            self.position.emit(pos)
            # self.speed.emit(speed)
            time.sleep(0.1)


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
        self.btnSetZero = Button("New zero", animate=True)
        self.btnSetZero.clicked.connect(self.setZero)
        # self.actualSpeedLabel = QLabel(self)
        # self.actualSpeedLabel.setText("Speed")
        # self.actualSpeed = QLabel(self)
        # self.actualSpeed.setStyleSheet("font-size: 20px; color: #1d1128;")
        # self.actualSpeed.setText("Unknown")

        self.btnStartMonitor = Button("Start monitor", animate=True)
        self.btnStartMonitor.clicked.connect(self.startMonitor)
        self.btnStopMonitor = Button("Stop monitor")
        self.btnStopMonitor.clicked.connect(self.stopMonitor)
        self.btnStopMonitor.setEnabled(False)

        grid_layout.addWidget(
            self.currentPositionLabel, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid_layout.addWidget(
            self.currentPosition, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid_layout.addWidget(self.btnSetZero, 0, 2)
        # grid_layout.addWidget(
        #     self.actualSpeedLabel, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter
        # )
        # grid_layout.addWidget(
        #     self.actualSpeed, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter
        # )
        grid_layout.addWidget(self.btnStartMonitor, 2, 0)
        grid_layout.addWidget(self.btnStopMonitor, 2, 2)
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
        state.CHOPPER_MONITOR = True
        self.chopper_monitor_thread = ChopperMonitorThread()
        self.chopper_monitor_thread.start()
        self.btnStartMonitor.setEnabled(False)
        self.btnStopMonitor.setEnabled(True)
        self.chopper_monitor_thread.position.connect(self.setCurrentPosition)
        # self.chopper_monitor_thread.speed.connect(self.setActualSpeed)
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

    # def setActualSpeed(self, speed: float):
    #     self.actualSpeed.setText(f"{round(speed, 1)} Hz")

    def stopMonitor(self):
        state.CHOPPER_MONITOR = False
        self.chopper_monitor_thread.exit(0)
