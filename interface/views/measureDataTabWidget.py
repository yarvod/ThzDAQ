from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy, QListView


class MeasureDataTabWidget(QWidget):

    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.listView = None
        self.model = None
        self.createListView()
        self.layout.addWidget(self.listView)

    def createListView(self):
        self.listView = QListView(self)
        self.model = QStandardItemModel()
        self.listView.setModel(self.model)
        self.listView.setObjectName("Measurement Data")
