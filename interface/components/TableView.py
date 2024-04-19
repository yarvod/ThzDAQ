from PyQt5 import QtGui, QtWidgets, QtCore
from PyQt5.QtWidgets import QAbstractItemView, QMessageBox

from interface.components.CommentDialogBox import CommentDialogBox


class TableView(QtWidgets.QTableView):
    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.menu = QtWidgets.QMenu(self)

        self.action_comment = QtWidgets.QAction("Comment", self)
        self.action_save = QtWidgets.QAction("Save", self)
        self.action_delete = QtWidgets.QAction("Delete", self)

        self.action_comment.setIcon(QtGui.QIcon("assets/edit-icon.png"))
        self.action_save.setIcon(QtGui.QIcon("assets/save-icon.png"))
        self.action_delete.setIcon(QtGui.QIcon("assets/delete-icon.png"))

        self.menu.addAction(self.action_comment)
        self.menu.addAction(self.action_save)
        self.menu.addAction(self.action_delete)

        self.action_comment.triggered.connect(self.commentSelectedRow)
        self.action_save.triggered.connect(self.saveSelectedRow)
        self.action_delete.triggered.connect(self.deleteSelectedRows)
        self.customContextMenuRequested.connect(self.showContextMenu)

    def showContextMenu(self, pos: QtCore.QPoint):
        self.menu.exec(self.mapToGlobal(pos))

    def saveSelectedRow(self):
        model = self.model()
        selection = self.selectionModel()
        rows = list(set(index.row() for index in selection.selectedIndexes()))
        if not len(rows):
            return
        model.manager.save_by_index(rows[0])

    def commentSelectedRow(self):
        model = self.model()
        selection = self.selectionModel()
        selected_index = list(set(index for index in selection.selectedIndexes()))
        if not len(selected_index):
            return
        selected_index = selected_index[0]
        measure_model_id = selected_index.model()._data[selected_index.row()][0]
        measure_model = model.manager.get(id=measure_model_id)

        reply = CommentDialogBox(self, measure_model.comment)
        button = reply.exec()
        if button == 1:
            measure_model.comment = reply.commentEdit.toPlainText()
            model.manager.update_table()

    def deleteSelectedRows(self):
        model = self.model()
        selection = self.selectionModel()
        row = list(set(index.row() for index in selection.selectedIndexes()))
        if not len(row):
            return
        row = row[0]
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
