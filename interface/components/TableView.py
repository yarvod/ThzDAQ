from PyQt6 import QtGui, QtWidgets, QtCore


class TableView(QtWidgets.QTableView):
    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.menu = QtWidgets.QMenu(self)
        self.action_save = QtGui.QAction("Save", self)
        self.action_delete = QtGui.QAction("Delete", self)
        self.menu.addAction(self.action_save)
        self.menu.addAction(self.action_delete)
        self.action_save.triggered.connect(self.saveSelectedRow)
        self.action_delete.triggered.connect(self.deleteSelectedRows)
        self.customContextMenuRequested.connect(self.showContextMenu)

    def showContextMenu(self, pos: QtCore.QPoint):
        self.menu.exec(self.mapToGlobal(pos))

    def saveSelectedRow(self):
        model = self.model()
        selection = self.selectionModel()
        rows = list(set(index.row() for index in selection.selectedIndexes()))
        model.manager.save_by_index(rows[0])

    def deleteSelectedRows(self):
        model = self.model()
        selection = self.selectionModel()
        rows = set(index.row() for index in selection.selectedIndexes())
        model.manager.delete_by_indexes(rows)
