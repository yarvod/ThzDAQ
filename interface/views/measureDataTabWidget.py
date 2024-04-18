from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHeaderView

from interface.components.TableView import TableView
from store.base import MeasureTableModel, MeasureManager


class MeasureDataTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)

        self.tableView = None
        self.model = None
        self.createTableView()
        self.layout.addWidget(self.tableView)

    def createTableView(self):
        self.tableView = TableView(self)
        self.tableView.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.tableView.setAutoScroll(True)
        self.model = MeasureTableModel()
        MeasureManager.table = self.model
        self.tableView.setModel(self.model)
