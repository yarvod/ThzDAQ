from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton, QGridLayout

from api.Chopper.chopper_sync import ChopperManager


class ChopperRotateCwThread(QThread):
    def __init__(self, angle: float = 90):
        super().__init__()
        self.angle = angle

    def run(self):
        if not ChopperManager.chopper.client.connected:
            self.finished.emit()
            return
        ChopperManager.chopper.path0(self.angle)
        self.finished.emit()


class ChopperManagingGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Managing")
        layout = QVBoxLayout(self)
        grid_layout = QGridLayout()

        self.btnRotateCw = QPushButton("Rotate +90")
        self.btnRotateCw.clicked.connect(lambda: self.rotateCw(90))
        grid_layout.addWidget(self.btnRotateCw, 0, 0)
        layout.addLayout(grid_layout)

        self.setLayout(layout)

    def rotateCw(self, angle: float):
        self.btnRotateCw.setEnabled(False)
        self.chopper_rotate_cw_thread = ChopperRotateCwThread(angle=angle)
        self.chopper_rotate_cw_thread.finished.connect(
            lambda: self.btnRotateCw.setEnabled(True)
        )
        self.chopper_rotate_cw_thread.start()
