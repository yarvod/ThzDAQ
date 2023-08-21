from PyQt6.QtWidgets import QMainWindow
from PyQt6 import QtGui

from interface import style
from interface.views.index import TabsWidget


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.title = "SIS manager"
        self.left = 0
        self.top = 0
        self.width = 450
        self.height = 700
        self.setWindowIcon(QtGui.QIcon("./assets/logo_small.png"))
        self.setStyleSheet(style.GLOBAL_STYLE)
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

        self.table_widget = TabsWidget(self)
        self.setCentralWidget(self.table_widget)
        self.setFixedWidth(self.width)

        self.show()
