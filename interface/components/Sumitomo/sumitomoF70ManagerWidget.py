from PySide6.QtWidgets import QSizePolicy, QGroupBox, QHBoxLayout

from api import F70Rest
from interface.components.ui.Button import Button
from store import SumitomoF70Manager


class SumitomoF70ManagerWidget(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.setTitle("Manager")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cid = cid

        layout = QHBoxLayout()

        self.btnTurnOn = Button("Turn On", animate=True)
        self.btnTurnOn.clicked.connect(self.turn_on)

        self.btnTurnOff = Button("Turn Off", animate=True)
        self.btnTurnOff.clicked.connect(self.turn_off)

        layout.addWidget(self.btnTurnOn)
        layout.addWidget(self.btnTurnOff)
        self.setLayout(layout)

    def turn_on(self):
        config = SumitomoF70Manager.get_config(self.cid)
        compressor = F70Rest(**config.dict())
        compressor.turn_on()

    def turn_off(self):
        config = SumitomoF70Manager.get_config(self.cid)
        compressor = F70Rest(**config.dict())
        compressor.turn_off()
