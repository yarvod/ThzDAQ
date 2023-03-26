from PyQt6.QtWidgets import *
import sys

from block import Block
from config import BLOCK_ADDRESS, BLOCK_PORT


def update_block(block_ip, block_port):
    block = Block(block_ip, block_port)
    block.host = block_ip
    block.port = int(block_port)


class UtilsMixin:

    @property
    def block(self):
        return Block()

    def set_voltage(self):
        self.block.set_voltage(float(self.voltage_s.text()))
        current = self.block.get_current()
        self.current_g.setText(current)
        voltage = self.block.get_voltage()
        self.voltage_g.setText(voltage)

    def get_voltage_current(self):
        current = self.block.get_current()
        self.current_g.setText(current)
        voltage = self.block.get_voltage()
        self.voltage_g.setText(voltage)


class App(QMainWindow):

    def __init__(self):
        super().__init__()
        self.title = 'CL manager'
        self.left = 0
        self.top = 0
        self.width = 400
        self.height = 300
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
        self.tabs = QTabWidget(self)
        self.tab_setup = SetUpTabWidget(self)
        self.tab_block = BlockTabWidget(self)
        self.tabs.resize(300, 200)

        # Add tabs
        self.tabs.addTab(self.tab_setup, "Set Up")
        self.tabs.addTab(self.tab_block, "SIS Block")

        # Add tabs to widget
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)


class SetUpTabWidget(QWidget):

    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.blockIPLabel = QLabel(self)
        self.blockIPLabel.setText('Block IP:')
        self.block_ip = QLineEdit(self)
        self.block_ip.setText(BLOCK_ADDRESS)

        self.block_ip.move(80, 20)
        self.block_ip.resize(200, 32)
        self.blockIPLabel.move(20, 20)

        self.blockPortLabel = QLabel(self)
        self.blockPortLabel.setText('Block Port:')
        self.block_port = QLineEdit(self)
        self.block_port.setText(BLOCK_PORT)

        self.block_port.move(80, 60)
        self.block_port.resize(200, 32)
        self.blockPortLabel.move(20, 60)

        # update_block(self.block_ip.text(), self.block_port.text())

        self.btn_update = QPushButton("Update")
        self.layout.addWidget(self.btn_update)
        self.btn_update.clicked.connect(
            lambda: update_block(self.block_ip.text(), self.block_port.text())
        )


class BlockTabWidget(QWidget, UtilsMixin):

    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.voltGLabel = QLabel(self)
        self.voltGLabel.setText('V Bias, V:')
        self.voltGLabel.move(20, 20)
        self.voltage_g = QLabel(self)
        self.voltage_g.move(80, 20)

        self.currGLabel = QLabel(self)
        self.currGLabel.setText('I, A:')
        self.currGLabel.move(160, 20)
        self.current_g = QLabel(self)
        self.current_g.move(200, 20)

        self.voltGLabel = QLabel(self)
        self.voltGLabel.setText('V Bias, V:')
        self.voltGLabel.move(20, 80)
        self.voltage_s = QDoubleSpinBox(self)
        self.voltage_s.move(80, 80)
        self.voltage_s.resize(100, 32)

        self.btn_set_voltage = QPushButton("Set Voltage")
        self.btn_set_voltage.clicked.connect(lambda: self.set_voltage())
        self.layout.addWidget(self.btn_set_voltage)

        # self.get_voltage_current()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = App()
    sys.exit(app.exec())
