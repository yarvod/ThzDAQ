from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTreeView, QHeaderView

from store.treeModel import JsonModel


class DataViewBox(QDialog):
    def __init__(self, parent, measure_model):
        super().__init__(parent)
        self.setWindowTitle(f"View data ID {measure_model.id}")
        layout = QVBoxLayout()
        data_layout = QVBoxLayout()

        view = QTreeView(self)
        model = JsonModel()
        view.setModel(model)
        model.load(measure_model.to_json())

        view.header().setSectionResizeMode(0, QHeaderView.Stretch)
        view.setAlternatingRowColors(True)
        view.resize(500, 300)

        data_layout.addWidget(view)
        layout.addLayout(data_layout)
        self.setLayout(layout)
