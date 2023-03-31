import logging

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from config import BLOCK_ADDRESS, BLOCK_PORT, BLOCK_CTRL_DEV, BLOCK_BIAS_DEV
from interactors.block import Block


logger = logging.getLogger(__name__)


class SetUpTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.createGridGroupBox()
        self.layout.addWidget(self.gridGroupBox)
        self.setLayout(self.layout)

    def createGridGroupBox(self):
        self.gridGroupBox = QGroupBox("Block config")
        layout = QGridLayout()

        self.blockIPLabel = QLabel(self)
        self.blockIPLabel.setText("Block IP:")
        self.block_ip = QLineEdit(self)
        self.block_ip.setText(BLOCK_ADDRESS)

        self.blockPortLabel = QLabel(self)
        self.blockPortLabel.setText("Block Port:")
        self.block_port = QLineEdit(self)
        self.block_port.setText(str(BLOCK_PORT))

        self.ctrlDevLabel = QLabel(self)
        self.biasDevLabel = QLabel(self)
        self.ctrlDev = QLineEdit(self)
        self.biasDev = QLineEdit(self)
        self.ctrlDevLabel.setText("CTRL Device:")
        self.biasDevLabel.setText("BIAS Device:")
        self.ctrlDev.setText(BLOCK_CTRL_DEV)
        self.biasDev.setText(BLOCK_BIAS_DEV)

        self.btnCheck = QPushButton("Check connection")
        self.btnCheck.clicked.connect(self.update_block)

        layout.addWidget(self.blockIPLabel, 1, 0)
        layout.addWidget(self.block_ip, 1, 1)
        layout.addWidget(self.blockPortLabel, 2, 0)
        layout.addWidget(self.block_port, 2, 1)
        layout.addWidget(self.ctrlDevLabel, 3, 0)
        layout.addWidget(self.ctrlDev, 3, 1)
        layout.addWidget(self.biasDevLabel, 4, 0)
        layout.addWidget(self.biasDev, 4, 1)
        layout.addWidget(self.btnCheck, 5, 0, 1, 2)

        self.gridGroupBox.setLayout(layout)

    def update_block(self):
        block = Block()
        block.update(host=self.block_ip.text(), port=self.block_port.text())
        result = block.get_bias_data()
        logger.info(f"Health check SIS block {result}")
