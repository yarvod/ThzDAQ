from PyQt6.QtWidgets import QWidget, QVBoxLayout

from interface.components.ChopperManagingGroup import ChopperManagingGroup


class ChopperTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(ChopperManagingGroup(self))
        layout.addStretch()
        self.setLayout(layout)
