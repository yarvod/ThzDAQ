from typing import Union

from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
)

from interface.components.deviceAddForm import DeviceAddForm
from interface.components.deviceInfo import DeviceInfo
from interface.components.ui.Button import Button
from interface.components.ui.Lines import HLine
from threads.deviceInitThread import DeviceInitThread


class SetUpDeviceWidget(QGroupBox):
    title = ""
    manager_class = None
    device_api_class = None

    def __init__(self, parent):
        super().__init__(parent)
        self.manager_class.setup_widget = self
        self.setTitle(self.title)
        self.form: Union[None, DeviceAddForm] = None
        self.instances = {}
        self.layout = QVBoxLayout()
        self.btn = Button("Add Device")
        self.btn.clicked.connect(self.open_form_add_device)

        self.layout.addWidget(self.btn)
        self.layout.addWidget(HLine(self))
        self.setLayout(self.layout)

    def open_form_add_device(self):
        self.form = DeviceAddForm(self)
        self.form.init.connect(self.init_device)
        self.form.show()

    def add_device_info_widget(self, cid, dev_info):
        self.instances[cid] = dev_info
        self.layout.addWidget(dev_info)
        self.layout.addWidget(HLine(self))

    def init_device(self, kwargs):
        cid = self.manager_class.add_config(**kwargs)
        config = self.manager_class.get_config(cid)
        dev_info = self.create_device_info_widget(config, **kwargs)
        dev_info.initialize()

    def create_device_info_widget(self, config, **kwargs):
        dev_info = DeviceInfo(
            self, config, DeviceInitThread, self.device_api_class, **kwargs
        )
        self.add_device_info_widget(config.cid, dev_info)
        return dev_info
