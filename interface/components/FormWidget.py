from typing import Dict

from PyQt6.QtWidgets import QWidget, QFormLayout


class FormWidget(QWidget):
    def __init__(self, parent, label_widget_map: Dict):
        super().__init__(parent)
        self.layout = QFormLayout(self)
        for label, widget in label_widget_map.items():
            self.layout.addRow(label, widget)
        self.setLayout(self.layout)
