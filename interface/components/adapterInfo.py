from typing import Union

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
)

import settings
from interface.components.adapterAddForm import AdapterAddForm
from interface.components.ui.Button import Button
from interface.components.ui.Lines import HLine
from store.adapterConfig import AdapterConfig
from threads import Thread


class AdapterInfo(QWidget):
    def __init__(
        self,
        parent,
        config: AdapterConfig,
        thread_class=None,
        adapter_class=None,
        host: str = "",
        port: str = "",
        status: str = settings.NOT_INITIALIZED,
        **kwargs,
    ):
        super().__init__(parent)

        self.config: AdapterConfig = config
        self.thread_class = thread_class
        self.init_thread: Union[None, Thread] = None
        self.adapter_class = adapter_class

        self.form = None

        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.nameLabel = QLabel(self)
        self.nameLabel.setText("Name:")
        self.name = QLabel(self)
        self.name.setText(self.config.name)

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

        self.statusLabel = QLabel(self)
        self.statusLabel.setText("Status:")
        self.status = QLabel(self)
        self.status.setText(status)
        self.config.signal_status.connect(lambda x: self.status.setText(f"{x}"))

        flayout.addRow(self.nameLabel, self.name)
        flayout.addRow(self.hostLabel, self.host)
        flayout.addRow(self.portLabel, self.port)
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
            self.adapter_class,
            host=self.host.text(),
            port=self.port.text(),
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
        self.form = AdapterAddForm(
            self,
            host=self.host.text(),
            port=self.port.text(),
        )
        self.form.init.connect(self.update_config_initialize)
        self.form.show()

    def delete(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"Deleting adapter '{self.config.name}'")
        box.setText(f"Are you sure want to delete adapter '{self.config.name}' ?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        action = box.exec()
        if action == QMessageBox.StandardButton.Yes:
            self.config.config_manager.delete_config(self.config.cid)
            self.parent().delete_adapter_info(self.config.cid)
            self.deleteLater()
