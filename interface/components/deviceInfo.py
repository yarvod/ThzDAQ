from typing import Union, Optional

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
)

import settings
from interface.components.deviceAddForm import DeviceAddForm
from interface.components.ui.Button import Button
from interface.components.ui.Lines import HLine
from store.deviceConfig import DeviceConfig
from threads import Thread


class DeviceInfo(QWidget):
    device_add_form_class = DeviceAddForm

    def __init__(
        self,
        parent,
        config: DeviceConfig,
        thread_class=None,
        device_api_class=None,
        adapter: str = settings.SOCKET,
        host: str = "",
        port: str = "",
        gpib: Optional[int] = 0,
        status: str = settings.NOT_INITIALIZED,
        **form_kwargs,
    ):
        super().__init__(parent)
        self.form_kwargs = form_kwargs
        self.config: DeviceConfig = config
        self.thread_class = thread_class
        self.init_thread: Union[None, Thread] = None
        self.device_api_class = device_api_class

        self.form = None

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
        self.add_custom_form_fields(flayout)
        flayout.addRow(self.statusLabel, self.status)

        self.btnInitialize = Button(
            "Initialize", icon=QIcon("assets/init-icon.png"), animate=True
        )
        self.btnInitialize.clicked.connect(self.initialize)
        self.btnEdit = Button("Edit", icon=QIcon("assets/edit-icon.png"))
        self.btnEdit.clicked.connect(self.edit)
        self.btnDelete = Button("Delete", icon=QIcon("assets/delete-icon.png"))
        self.btnDelete.clicked.connect(self.delete)

        hlayout.addWidget(self.btnInitialize)
        hlayout.addWidget(self.btnEdit)
        hlayout.addWidget(self.btnDelete)

        layout.addLayout(flayout)
        layout.addLayout(hlayout)
        layout.addWidget(HLine(self))
        self.setLayout(layout)

    def initialize(self):
        self.init_thread = self.thread_class(
            self.device_api_class,
            **self.get_initialize_kwargs(),
        )
        self.init_thread.status.connect(self.config.set_status)
        self.init_thread.finished.connect(lambda: self.btnInitialize.setEnabled(True))
        self.init_thread.start()
        self.btnInitialize.setEnabled(False)

    def update_config_initialize(self, kwargs):
        for k, v in kwargs.items():
            self.config.__setattr__(k, v)
        self.initialize()

    def edit(self):
        self.form = self.device_add_form_class(
            self,
            **self.get_initialize_kwargs(),
        )
        self.form.init.connect(self.update_config_initialize)
        self.form.show()

    def delete(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"Deleting device '{self.config.name}'")
        box.setText(f"Are you sure want to delete device '{self.config.name}' ?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        action = box.exec()
        if action == QMessageBox.StandardButton.Yes:
            self.config.config_manager.delete_config(self.config.cid)
            self.parent().delete_device_info(self.config.cid)
            del self.config
            self.deleteLater()

    def add_custom_form_fields(self, flayout):
        ...

    def get_initialize_kwargs(self):
        return dict(
            adapter=self.adapter.text(),
            host=self.host.text(),
            port=self.port.text(),
            gpib=self.gpib.text(),
        )
