import asyncio

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QFormLayout, QLineEdit, QPushButton, QLabel

from api.Chopper.chopper import chopper
from interface.threads import chopper_thread
from settings import NOT_INITIALIZED
from store.state import state


class ChopperThread(QThread):
    status = pyqtSignal(bool)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(chopper.connect())
        status = chopper.client.connected
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
        chopper_thread.method = "connect"
        chopper_thread.status.connect(self.setStatus)
        chopper_thread.start()
        # loop = asyncio.new_event_loop()
        # asyncio.set_event_loop(loop)
        # loop.run_until_complete(chopper.connect())
        # status = chopper.client.connected
        # self.setStatus(status)

    def setStatus(self, status: bool = False):
        if status:
            self.chopperStatus.setText("Ok")
        else:
            self.chopperStatus.setText("Error!")
