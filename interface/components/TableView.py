from typing import Optional

from PySide6 import QtGui, QtWidgets, QtCore
from PySide6.QtWidgets import QAbstractItemView, QMessageBox

from interface.components.CommentDialogBox import CommentDialogBox
from interface.components.dataViewBox import DataViewBox
from store.base import MeasureModel


class TableView(QtWidgets.QTableView):
    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.menu = QtWidgets.QMenu(self)

        self.action_comment = QtWidgets.QWidgetAction("Comment", self)
        self.action_view = QtWidgets.QWidgetAction("View", self)
        self.action_save = QtWidgets.QWidgetAction("Save", self)
        self.action_delete = QtWidgets.QWidgetAction("Delete", self)

        self.action_comment.setIcon(QtGui.QIcon("assets/edit-icon.png"))
        self.action_view.setIcon(QtGui.QIcon("assets/search-icon.png"))
        self.action_save.setIcon(QtGui.QIcon("assets/save-icon.png"))
        self.action_delete.setIcon(QtGui.QIcon("assets/delete-icon.png"))

        self.menu.addAction(self.action_comment)
        self.menu.addAction(self.action_view)
        self.menu.addAction(self.action_save)
        self.menu.addAction(self.action_delete)

        self.action_comment.triggered.connect(self.commentSelectedRow)
        self.action_view.triggered.connect(self.viewSelectedRow)
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

    def get_selected_measure_model(self) -> Optional[MeasureModel]:
        model = self.model()
        selection = self.selectionModel()
        selected_index = list(set(index for index in selection.selectedIndexes()))
        if not len(selected_index):
            return
        selected_index = selected_index[0]
        measure_model_id = selected_index.model()._data[selected_index.row()][0]
        return model.manager.get(id=measure_model_id)

    def commentSelectedRow(self):
        measure_model = self.get_selected_measure_model()
        if not measure_model:
            return
        reply = CommentDialogBox(self, measure_model.comment)
        button = reply.exec()
        if button == 1:
            measure_model.comment = reply.commentEdit.toPlainText()
            measure_model.objects.update_table()

    def viewSelectedRow(self):
        measure_model = self.get_selected_measure_model()
        if not measure_model:
            return
        reply = DataViewBox(self, measure_model)
        button = reply.exec()

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
