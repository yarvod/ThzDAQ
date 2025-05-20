from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from interface.components.RohdeSchwarz.RSPowerSupplyManagerWidget import ManagerWidget
from interface.components.RohdeSchwarz.RSPowerSupplyMonitorWidget import MonitorWidget


class RohdeSchwarzPowerSupplyWidget(QScrollArea):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.widget = QWidget()
        self.cid = cid

        layout = QVBoxLayout()
        layout.addWidget(MonitorWidget(self, cid=self.cid))
        layout.addWidget(ManagerWidget(self, cid=self.cid))
        layout.addStretch()

        self.widget.setLayout(layout)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setWidget(self.widget)
