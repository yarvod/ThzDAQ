import requests.exceptions
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QGroupBox, QFormLayout, QLabel, QLineEdit

from api.NationalInstruments.yig_filter import NiYIGManager
from interface.components.ui.Button import Button
from store.state import state


class DigitalYigTestThread(QThread):
    status = Signal(bool)

    def run(self):
        ni = NiYIGManager(host=state.NI_IP)
        try:
            test = ni.test()
            self.status.emit(test)
        except requests.exceptions.ConnectTimeout:
            self.status.emit(False)
        self.finished.emit()


class SetUpDigitalYigGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QFormLayout()
        self.createGroupDigitalYig()
        self.setLayout(self.layout)

    def createGroupDigitalYig(self):
        self.setTitle("Digital YIG (NI)")

        self.digitalYigAddressLabel = QLabel(self)
        self.digitalYigAddressLabel.setText("IP address")
        self.digitalYigAddress = QLineEdit(self)
        self.digitalYigAddress.setText(state.NI_IP)

        self.digitalYigStatusLabel = QLabel(self)
        self.digitalYigStatusLabel.setText("Status")
        self.digitalYigStatus = QLabel(self)
        self.digitalYigStatus.setText("Not initialized yet!")

        self.btnInitDigitalYig = Button("Initialize", animate=True)
        self.btnInitDigitalYig.clicked.connect(self.initialize_digital_yig)

        self.layout.addRow(self.digitalYigAddressLabel, self.digitalYigAddress)
        self.layout.addRow(self.digitalYigStatusLabel, self.digitalYigStatus)
        self.layout.addRow(self.btnInitDigitalYig)

    def initialize_digital_yig(self):
        state.NI_IP = self.digitalYigAddress.text()
        self.digital_yig_thread = DigitalYigTestThread()
        self.digital_yig_thread.start()
        self.btnInitDigitalYig.setEnabled(False)
        self.digital_yig_thread.finished.connect(
            lambda: self.btnInitDigitalYig.setEnabled(True)
        )
        self.digital_yig_thread.status.connect(self.set_digital_yig_status)

    def set_digital_yig_status(self, status: bool):
        if status:
            self.digitalYigStatus.setText("Ok")
        else:
            self.digitalYigStatus.setText("Error")
