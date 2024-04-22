from PyQt5.QtWidgets import QWidget, QVBoxLayout
from interface.components.RohdeSchwarz.SpectrumMonitor import SpectrumMonitor


class SpectrumTabWidget(QWidget):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self.layout = QVBoxLayout(self)
        self.spectrum_monitor = SpectrumMonitor(self, cid)
        self.layout.addWidget(self.spectrum_monitor)
        self.layout.addStretch()

        self.setLayout(self.layout)
