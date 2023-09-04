import asyncio

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QFormLayout, QLineEdit, QPushButton, QLabel

from api.Chopper.chopper import Chopper
from settings import NOT_INITIALIZED
from store.state import state


class ChopperThread(QThread):
    status = pyqtSignal(bool)

    def run(self):
        chopper = Chopper(host=state.CHOPPER_HOST)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(chopper.connect())
        status = chopper.client.connected
        chopper.client.close()
        del chopper
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
        self.chopper_thread = ChopperThread()

        state.CHOPPER_HOST = self.chopperAddress.text()

        self.chopper_thread.status.connect(self.setStatus)
        self.chopper_thread.start()

    def setStatus(self, status: bool = False):
        if status:
            self.chopperStatus.setText("Ok")
        else:
            self.chopperStatus.setText("Error!")
