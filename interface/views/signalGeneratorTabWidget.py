from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
)

from interface.components.Agilent.monitorSignalGenerator import (
    AgilentSignalGeneratorMonitorWidget,
)
from interface.components.Agilent.signalGeneratorConfig import (
    AgilentSignalGeneratorConfigWidget,
)
from interface.components.Agilent.signalGeneratorManager import (
    AgilentSignalGeneratorManagerWidget,
)


class SignalGeneratorTabWidget(QScrollArea):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self.widget = QWidget()
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(AgilentSignalGeneratorMonitorWidget(self, self.cid))
        self.layout.addSpacing(10)
        self.layout.addWidget(AgilentSignalGeneratorManagerWidget(self, self.cid))
        self.layout.addSpacing(10)
        self.layout.addWidget(AgilentSignalGeneratorConfigWidget(self, self.cid))
        self.layout.addStretch()

        self.widget.setLayout(self.layout)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setWidget(self.widget)
