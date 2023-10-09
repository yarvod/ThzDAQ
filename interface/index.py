from PyQt5.QtWidgets import QMainWindow, QMessageBox, QCheckBox, QApplication
from PyQt5 import QtGui

from interface import style
from interface.views.index import TabsWidget
from store.base import MeasureManager


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.title = "SIS manager"
        self.left = 0
        self.top = 0
        self.width = 650
        self.height = 700
        self.setWindowIcon(QtGui.QIcon("./assets/logo_small.png"))
        self.setStyleSheet(style.GLOBAL_STYLE)
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

        self.table_widget = TabsWidget(self)
        self.setCentralWidget(self.table_widget)
        self.setFixedWidth(self.width)

        self.show()

    def closeEvent(self, event):
        reply = QMessageBox(self)
        reply.setWindowTitle("Exit")
        reply.setText("Are you sure you want to exit?")
        reply.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        reply.setDefaultButton(QMessageBox.StandardButton.No)
        reply.setIcon(QMessageBox.Icon.Question)
        layout = reply.layout()
        dumpDataCheck = QCheckBox(reply)
        dumpDataCheck.setChecked(True)
        dumpDataCheck.setText("Dump all data on exit")
        layout.addWidget(dumpDataCheck)
        reply.setLayout(layout)
        button = reply.exec()
        if button == QMessageBox.StandardButton.Yes:
            if dumpDataCheck.isChecked():
                MeasureManager.save_all()
            for window in QApplication.topLevelWidgets():
                window.close()
            event.accept()
        else:
            event.ignore()
