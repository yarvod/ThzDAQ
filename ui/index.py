from PyQt6.QtWidgets import QMainWindow
from PyQt6 import QtGui

from ui.views.index import TabsWidget


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.title = "SIS manager"
        self.left = 0
        self.top = 0
        self.width = 400
        self.height = 300
        self.setWindowIcon(QtGui.QIcon("./assets/logo_small.ico"))
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

        self.table_widget = TabsWidget(self)
        self.setCentralWidget(self.table_widget)

        self.show()
