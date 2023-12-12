from PyQt5.QtWidgets import (
    QGroupBox,
    QWidget,
    QSpinBox,
    QLabel,
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
)

import settings
from interface.components.ui.Button import Button


class KeithleyForm(QDialog):
    def __init__(self, parent):
        super().__init__(parent)

        layout = QVBoxLayout()
        flayout = QFormLayout()
        hlayout = QHBoxLayout()

        self.gpibAddressLabel = QLabel(self)
        self.gpibAddressLabel.setText("GPIB address:")
        self.gpibAddress = QSpinBox(self)
        self.gpibAddress.setRange(1, 31)
        self.gpibAddress.setValue(20)
        self.statusLabel = QLabel(self)
        self.statusLabel.setText("Status:")
        self.status = QLabel(self)
        self.status.setText(settings.NOT_INITIALIZED)

        flayout.addRow(self.gpibAddressLabel, self.gpibAddress)
        flayout.addRow(self.statusLabel, self.status)

        self.btnSubmit = Button(self)
        self.btnSubmit.setText("Initialize")

        self.setLayout(layout)

    def initSignal(self):
        ...

    def initilize(self):
        ...


class SetUpKeithley(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QVBoxLayout()
        self.btn = Button("Add")
        self.btn.clicked.connect(self.show_dialog)

        self.layout.addWidget(self.btn)
        self.setLayout(self.layout)

    def show_dialog(self):
        form = KeithleyForm(self)
        form.show()
