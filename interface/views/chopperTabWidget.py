from PySide6.QtWidgets import QWidget, QVBoxLayout

from interface.components.chopper.ChopperManagingGroup import ChopperManagingGroup
from interface.components.chopper.ChopperMonitorGroup import ChopperMonitorGroup


class ChopperTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(ChopperMonitorGroup(self))
        layout.addWidget(ChopperManagingGroup(self))
        layout.addStretch()
        self.setLayout(layout)
