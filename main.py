# import sys
#
# from PyQt6.QtWidgets import QApplication
#
# from interface.index import App
#
# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     ex = App()
#     sys.exit(app.exec())


from PyQt6 import QtWidgets, QtCore, QtGui
import sys


class Window(QtWidgets.QWidget):
    def __init__(self, first_column, second_column, parent=None):
        super(Window, self).__init__(parent)

        self.view = QtWidgets.QTableView(self)
        self.view.setShowGrid(False)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.model = QtGui.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["name", "quantity"])
        self.view.setModel(self.model)

        for first_text, second_text in zip(first_column, second_column):
            item_1 = QtGui.QStandardItem(first_text)
            item_1.setCheckable(True)
            item_1.setCheckState(QtCore.Qt.CheckState.Unchecked)

            item_2 = QtGui.QStandardItem(second_text)

            self.model.appendRow([item_1, item_2])

        button = QtWidgets.QPushButton("Add Item")
        button.clicked.connect(self.onClick)

        # layout
        layout = QtWidgets.QVBoxLayout(self)
        #
        layout.addWidget(self.view)
        layout.addWidget(button)

    def onClick(self):
        item_1 = QtGui.QStandardItem("mango")
        item_1.setCheckable(True)
        item_1.setCheckState(QtCore.Qt.CheckState.Unchecked)

        item_2 = QtGui.QStandardItem("10")

        self.model.appendRow([item_1, item_2])


if __name__ == "__main__":

    Mylist = ["Apple", "Orange", "lemon"]
    Quantity = ["5", "2", "7"]

    app = QtWidgets.QApplication(sys.argv)
    window = Window(Mylist, Quantity)
    window.show()
    sys.exit(app.exec())
