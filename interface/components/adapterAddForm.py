from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
)

from interface.components.ui.Button import Button


class AdapterAddForm(QDialog):
    init = pyqtSignal(dict)

    def __init__(
        self,
        parent,
        host: str = "",
        port: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Add new adapter")
        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.hostLabel = QLabel(self)
        self.hostLabel.setText("Host:")
        self.host = QLineEdit(self)
        self.host.setText(host)
        self.host.setPlaceholderText("0.0.0.0")
        self.host.setToolTip("IPv4 address")

        self.portLabel = QLabel(self)
        self.portLabel.setText("Port:")
        self.port = QLineEdit(self)
        self.port.setText(port)
        self.port.setPlaceholderText("1234")
        self.port.setToolTip("Device/Usb port")

        flayout.addRow(self.hostLabel, self.host)
        flayout.addRow(self.portLabel, self.port)

        self.btnSubmit = Button(self)
        self.btnSubmit.setText("Initialize")
        self.btnSubmit.clicked.connect(self.initilize)
        hlayout.addWidget(self.btnSubmit)

        layout.addLayout(flayout)
        layout.addLayout(hlayout)

        self.setLayout(layout)

    def initilize(self):
        self.init.emit(
            {
                "host": self.host.text(),
                "port": self.port.text(),
            }
        )
        self.close()
