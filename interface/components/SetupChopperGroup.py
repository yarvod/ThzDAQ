from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QFormLayout, QLineEdit, QPushButton, QLabel

from api.Chopper.chopper_sync import chopper
from settings import NOT_INITIALIZED
from store.state import state


class ChopperThread(QThread):
    status = pyqtSignal(bool)

    def run(self):
        chopper.init_client(host=state.CHOPPER_HOST)
        status = chopper.connect()
        self.status.emit(status)
        self.finished.emit()


class SetupChopperGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Chopper")
        layout = QFormLayout(self)
        self.chopperAddress = QLineEdit(self)
        self.chopperAddress.setText(state.CHOPPER_HOST)
        self.chopperStatus = QLabel(self)
        self.chopperStatus.setText(NOT_INITIALIZED)
        self.btnInitChopper = QPushButton("Initialize")
        self.btnInitChopper.clicked.connect(self.initializeChopper)

        layout.addRow("Address:", self.chopperAddress)
        layout.addRow("Status:", self.chopperStatus)
        layout.addRow(self.btnInitChopper)

        self.setLayout(layout)

    def initializeChopper(self):
        state.CHOPPER_HOST = self.chopperAddress.text()
        chopper_thread = ChopperThread()
        chopper_thread.status.connect(self.setStatus)
        chopper_thread.start()

    def setStatus(self, status: bool = False):
        if status:
            self.chopperStatus.setText("Ok")
        else:
            self.chopperStatus.setText("Error!")
