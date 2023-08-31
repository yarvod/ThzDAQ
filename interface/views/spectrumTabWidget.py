from PyQt6.QtWidgets import QWidget, QVBoxLayout
from interface.components.SpectrumMonitor import SpectrumMonitor


class SpectrumTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)

        self.layout.addWidget(SpectrumMonitor(self))
        self.layout.addStretch()

        self.setLayout(self.layout)
