from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel

import settings
from interface.components.ui.Button import Button
from store.deviceConfig import DeviceConfig


class DeviceInfo(QWidget):
    def __init__(
        self,
        parent,
        config: DeviceConfig,
        adapter: str = settings.SOCKET,
        host: str = "",
        port: str = "",
        gpib: int = 0,
        status: str = settings.NOT_INITIALIZED,
    ):
        super().__init__(parent)

        self.config: DeviceConfig = config

        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.nameLabel = QLabel(self)
        self.nameLabel.setText("Name:")
        self.name = QLabel(self)
        self.name.setText(self.config.name)

        self.adapterLabel = QLabel(self)
        self.adapterLabel.setText("Adapter:")
        self.adapter = QLabel(self)
        self.adapter.setText(f"{adapter}")
        self.config.signal_adapter.connect(lambda x: self.adapter.setText(f"{x}"))

        self.hostLabel = QLabel(self)
        self.hostLabel.setText("Host:")
        self.host = QLabel(self)
        self.host.setText(f"{host}")
        self.config.signal_host.connect(lambda x: self.host.setText(f"{x}"))

        self.portLabel = QLabel(self)
        self.portLabel.setText("Port:")
        self.port = QLabel(self)
        self.port.setText(f"{port}")
        self.config.signal_port.connect(lambda x: self.port.setText(f"{x}"))

        self.gpibLabel = QLabel(self)
        self.gpibLabel.setText("GPIB:")
        self.gpib = QLabel(self)
        self.gpib.setText(f"{gpib}")
        self.config.signal_gpib.connect(lambda x: self.gpib.setText(f"{x}"))

        self.statusLabel = QLabel(self)
        self.statusLabel.setText("Status:")
        self.status = QLabel(self)
        self.status.setText(status)
        self.config.signal_status.connect(lambda x: self.status.setText(f"{x}"))

        flayout.addRow(self.nameLabel, self.name)
        flayout.addRow(self.adapterLabel, self.adapter)
        flayout.addRow(self.hostLabel, self.host)
        flayout.addRow(self.portLabel, self.port)
        flayout.addRow(self.gpibLabel, self.gpib)
        flayout.addRow(self.statusLabel, self.status)

        self.btnInitialize = Button("Initialize")
        self.btnInitialize.clicked.connect(self.initialize)
        self.btnEdit = Button("Edit")
        self.btnEdit.clicked.connect(self.edit)

        hlayout.addWidget(self.btnInitialize)
        hlayout.addWidget(self.btnEdit)

        layout.addLayout(flayout)
        layout.addLayout(hlayout)
        self.setLayout(layout)

    def initialize(self):
        ...

    def edit(self):
        ...
