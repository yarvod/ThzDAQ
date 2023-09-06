from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QFormLayout, QLineEdit, QLabel

from api.Chopper.chopper_sync import ChopperManager
from interface.components.ui.Button import Button
from settings import NOT_INITIALIZED
from store.state import state


class ChopperThread(QThread):
    status = pyqtSignal(bool)

    def run(self):
        ChopperManager.chopper.init_client(host=state.CHOPPER_HOST)
        status = ChopperManager.chopper.connect()
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
        self.btnInitChopper = Button("Initialize", animate=True)
        self.btnInitChopper.clicked.connect(self.initializeChopper)

        layout.addRow("Address:", self.chopperAddress)
        layout.addRow("Status:", self.chopperStatus)
        layout.addRow(self.btnInitChopper)

        self.setLayout(layout)

    def initializeChopper(self):
        state.CHOPPER_HOST = self.chopperAddress.text()
        self.chopper_thread = ChopperThread()
        self.btnInitChopper.setEnabled(False)
        self.chopper_thread.finished.connect(
            lambda: self.btnInitChopper.setEnabled(True)
        )
        self.chopper_thread.status.connect(self.setStatus)
        self.chopper_thread.start()

    def setStatus(self, status: bool = False):
        if status:
            self.chopperStatus.setText("Ok")
        else:
            self.chopperStatus.setText("Error!")
