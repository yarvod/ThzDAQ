from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QLineEdit,
    QComboBox,
)

import settings
from interface.components.ui.Button import Button


class DeviceAddForm(QDialog):
    init = Signal(dict)

    def __init__(
        self,
        parent,
        adapter: str = settings.SOCKET,
        host: str = "",
        port: str = "",
        gpib: int = 0,
    ):
        super().__init__(parent)
        self.setWindowTitle("Add new device")
        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.adapterLabel = QLabel(self)
        self.adapterLabel.setText("Adapter:")
        self.adapter = QComboBox(self)
        self.adapter.addItems(settings.ADAPTERS.keys())
        self.adapter.setCurrentText(adapter)

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

        self.gpibLabel = QLabel(self)
        self.gpibLabel.setText("GPIB:")
        self.gpib = QSpinBox(self)
        self.gpib.setRange(1, 31)
        self.gpib.setValue(int(gpib))
        self.gpib.setToolTip("GPIB address")

        flayout.addRow(self.adapterLabel, self.adapter)
        flayout.addRow(self.hostLabel, self.host)
        flayout.addRow(self.portLabel, self.port)
        flayout.addRow(self.gpibLabel, self.gpib)

        self.btnSubmit = Button(self, icon=QIcon("assets/init-icon.png"))
        self.btnSubmit.setText("Initialize")
        self.btnSubmit.clicked.connect(self.initilize)
        hlayout.addWidget(self.btnSubmit)

        layout.addLayout(flayout)
        layout.addLayout(hlayout)

        self.setLayout(layout)

    def initilize(self):
        self.init.emit(
            {
                "adapter": self.adapter.currentText(),
                "host": self.host.text(),
                "port": self.port.text(),
                "gpib": self.gpib.value(),
            }
        )
        self.close()
