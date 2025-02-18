from typing import Union

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
)

from store import PrologixManager
from api.adapters.prologix import Prologix
from interface.components.adapterAddForm import AdapterAddForm
from interface.components.adapterInfo import AdapterInfo
from interface.components.ui.Button import Button
from interface.components.ui.Lines import HLine
from threads.adapterInitThread import AdapterInitThread


class SetUpPrologix(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        PrologixManager.setup_widget = self
        self.setTitle("Prologix Ethernet")
        self.form: Union[None, AdapterAddForm] = None
        self.instances = {}
        self.layout = QVBoxLayout()
        self.btn = Button("Add Adapter", icon=QIcon("assets/add-icon.png"))
        self.btn.clicked.connect(self.open_form_add_adapter)

        self.layout.addWidget(self.btn)
        self.layout.addWidget(HLine(self))
        self.setLayout(self.layout)

    def open_form_add_adapter(self):
        self.form = AdapterAddForm(self)
        self.form.init.connect(self.init_adapter)
        self.form.show()

    def add_adapter_info_widget(self, cid, dev_info):
        self.instances[cid] = dev_info
        self.layout.addWidget(dev_info)

    def init_adapter(self, kwargs):
        cid = PrologixManager.add_config(**kwargs)
        config = PrologixManager.get_config(cid)
        dev_info = self.create_adapter_info_widget(config, **kwargs)
        dev_info.initialize()

    def create_adapter_info_widget(self, config, **kwargs):
        dev_info = AdapterInfo(self, config, AdapterInitThread, Prologix, **kwargs)
        self.add_adapter_info_widget(config.cid, dev_info)
        return dev_info

    def delete_adapter_info(self, cid: int):
        self.layout.removeWidget(self.instances[cid])
        del self.instances[cid]
