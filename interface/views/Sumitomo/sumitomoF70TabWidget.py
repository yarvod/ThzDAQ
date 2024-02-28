from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QScrollArea, QWidget, QVBoxLayout

from interface.components.Sumitomo import SumitomoF70ManagerWidget


class SumitomoF70TabWidget(QScrollArea):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.widget = QWidget()
        self.cid = cid

        layout = QVBoxLayout()
        layout.addWidget(SumitomoF70ManagerWidget(self, cid=self.cid))
        layout.addStretch()

        self.widget.setLayout(layout)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setWidget(self.widget)
