from PySide6.QtWidgets import QWidget, QVBoxLayout
from interface.components.RohdeSchwarz.SpectrumMonitor import SpectrumMonitor
from interface.components.RohdeSchwarz.spectrumConfigWidget import SpectrumConfigWidget


class SpectrumTabWidget(QWidget):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(SpectrumConfigWidget(self, cid))
        self.layout.addWidget(SpectrumMonitor(self, cid))
        self.layout.addStretch()

        self.setLayout(self.layout)
