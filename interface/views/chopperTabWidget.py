from PyQt6.QtWidgets import QWidget, QVBoxLayout

from interface.components.ChopperMonitorGroup import ChopperMonitorGroup


class ChopperTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(ChopperMonitorGroup(self))
        layout.addStretch()
        self.setLayout(layout)
