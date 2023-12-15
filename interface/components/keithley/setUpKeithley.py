from typing import Union

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from api.Keithley import KeithleyPowerSupplyManager, PowerSupply
from interface.components.deviceAddForm import DeviceAddForm
from interface.components.deviceInfo import DeviceInfo
from interface.components.ui.Button import Button
from interface.components.ui.Lines import HLine
from threads import Thread


class DeviceInitThread(Thread):
    status = pyqtSignal(str)

    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs

    def run(self) -> None:
        device = PowerSupply(**self.kwargs)
        if device.test():
            self.status.emit("OK")
        else:
            self.status.emit("Error!")
        self.finished.emit()


class SetUpKeithley(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Keithley Power Supply")
        self.device_init_thread: Union[None, DeviceInitThread] = None
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
        cid = KeithleyPowerSupplyManager.add_config(**kwargs)
        config = KeithleyPowerSupplyManager.get_config(cid)
        dev_info = DeviceInfo(self, config, **kwargs)
        self.add_device_info_widget(cid, dev_info)

        self.device_init_thread = DeviceInitThread(**kwargs)
        self.device_init_thread.status.connect(config.set_status)
        self.device_init_thread.start()
