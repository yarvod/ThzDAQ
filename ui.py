from PyQt5.QtWidgets import *
import sys


class App(QMainWindow):

    def __init__(self):
        super().__init__()
        self.title = 'CL manager'
        self.left = 0
        self.top = 0
        self.width = 300
        self.height = 200
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

        self.table_widget = TabsWidget(self)
        self.setCentralWidget(self.table_widget)

        self.show()


class TabsWidget(QWidget):

    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)

        # Initialize tab screen
        self.tabs = QTabWidget()
        self.tab_setup = SetupTabWidget()
        self.tab_block = QWidget()
        self.tabs.resize(300, 200)

        # Add tabs
        self.tabs.addTab(self.tab_setup, "Set Up")
        self.tabs.addTab(self.tab_block, "SIS Block")

        # Add tabs to widget
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)


class SetupTabWidget(QWidget):

    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.blockIPLabel = QLabel(self)
        self.blockIPLabel.setText('Block IP:')
        self.block_ip = QLineEdit(self)

        self.block_ip.move(80, 20)
        self.block_ip.resize(200, 32)
        self.blockIPLabel.move(20, 20)

        self.pushButton1 = QPushButton("PyQt5 button")
        self.layout.addWidget(self.pushButton1)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = App()
    sys.exit(app.exec_())
