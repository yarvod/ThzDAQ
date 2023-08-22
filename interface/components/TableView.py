from PyQt6 import QtGui, QtWidgets, QtCore
from PyQt6.QtWidgets import QAbstractItemView, QMessageBox


class TableView(QtWidgets.QTableView):
    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.menu = QtWidgets.QMenu(self)

        self.action_save = QtGui.QAction("Save", self)
        self.action_delete = QtGui.QAction("Delete", self)

        self.action_save.setIcon(QtGui.QIcon("assets/save-icon.png"))
        self.action_delete.setIcon(QtGui.QIcon("assets/delete-icon.png"))

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
        row = list(set(index.row() for index in selection.selectedIndexes()))[0]
        measure = model.manager.all()[row]

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Deleting data")
        dlg.setText(
            f"Аre you sure you want to delete the data '{measure.type_display} {measure.finished.__str__()}'"
        )
        dlg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dlg.setIcon(QMessageBox.Icon.Question)
        button = dlg.exec()

        if button == QMessageBox.StandardButton.Yes:
            model.manager.delete_by_index(row)
        else:
            return
