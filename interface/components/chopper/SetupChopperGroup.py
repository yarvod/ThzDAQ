from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QFormLayout, QLineEdit, QLabel, QComboBox

from api.Chopper import chopper_manager
from interface.components.ui.Button import Button
from settings import NOT_INITIALIZED, WAVESHARE_ETHERNET, SERIAL_USB
from store.state import state


class ChopperThread(QThread):
    status = pyqtSignal(bool)

    def run(self):
        chopper_manager.init_adapter(
            adapter=state.CHOPPER_ADAPTER,
            host=state.CHOPPER_HOST,
            port=state.CHOPPER_PORT,
        )
        status = chopper_manager.chopper.connect()
        self.status.emit(status)
        self.finished.emit()


class SetupChopperGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Chopper")
        layout = QFormLayout(self)
        self.adapter = QComboBox(self)
        self.adapter.addItems(chopper_manager.adapters_classes.keys())
        self.adapter.currentTextChanged.connect(self.adapterChanged)
        self.chopperHost = QLineEdit(self)
        self.chopperHost.setText(state.CHOPPER_HOST)
        self.chopperPort = QLineEdit(self)
        self.chopperPort.setText(f"{state.CHOPPER_PORT}")
        self.chopperStatus = QLabel(self)
        self.chopperStatus.setText(NOT_INITIALIZED)
        self.btnInitChopper = Button("Initialize", animate=True)
        self.btnInitChopper.clicked.connect(self.initializeChopper)

        layout.addRow("Adapter:", self.adapter)
        layout.addRow("Host:", self.chopperHost)
        layout.addRow("Port:", self.chopperPort)
        layout.addRow("Status:", self.chopperStatus)
        layout.addRow(self.btnInitChopper)

        self.setLayout(layout)

    def initializeChopper(self):
        state.CHOPPER_HOST = self.chopperHost.text()
        state.CHOPPER_PORT = self.chopperPort.text()
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

    def adapterChanged(self, value):
        if value == WAVESHARE_ETHERNET:
            state.CHOPPER_ADAPTER = WAVESHARE_ETHERNET
            state.CHOPPER_HOST = state.WAVESHARE_HOST
            state.CHOPPER_PORT = state.WAVESHARE_PORT
            self.chopperHost.setEnabled(True)
            self.chopperHost.setText(state.CHOPPER_HOST)
            self.chopperPort.setText(f"{state.CHOPPER_PORT}")
        elif value == SERIAL_USB:
            state.CHOPPER_ADAPTER = SERIAL_USB
            state.CHOPPER_PORT = state.CHOPPER_DEFAULT_SERIAL_PORT
            self.chopperHost.setEnabled(False)
            self.chopperPort.setText(f"{state.CHOPPER_PORT}")
