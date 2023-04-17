import logging
import time

from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from config import (
    BLOCK_ADDRESS,
    BLOCK_PORT,
    BLOCK_CTRL_DEV,
    BLOCK_BIAS_DEV,
    VNA_ADDRESS,
    VNA_TEST_MAP,
)
from interactors.block import Block
from interactors.vna import VNABlock

logger = logging.getLogger(__name__)


class VNAWorker(QObject):
    finished = pyqtSignal()
    status = pyqtSignal(str)

    def run(self, vna_ip: str):
        vna = VNABlock()
        vna.update(vna_ip=vna_ip)
        result = vna.test()
        self.status.emit(VNA_TEST_MAP.get(result, "Error"))
        self.finished.emit()


class SetUpTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.createGroupBlock()
        self.createGroupVna()
        self.layout.addWidget(self.groupBlock)
        self.layout.addWidget(self.groupVna)
        self.setLayout(self.layout)

    def createGroupBlock(self):
        self.groupBlock = QGroupBox("Block config")
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

        self.btnInitBlock = QPushButton("Initialize Block")
        self.btnInitBlock.clicked.connect(self.initialize_block)

        layout.addWidget(self.blockIPLabel, 1, 0)
        layout.addWidget(self.block_ip, 1, 1)
        layout.addWidget(self.blockPortLabel, 2, 0)
        layout.addWidget(self.block_port, 2, 1)
        layout.addWidget(self.ctrlDevLabel, 3, 0)
        layout.addWidget(self.ctrlDev, 3, 1)
        layout.addWidget(self.biasDevLabel, 4, 0)
        layout.addWidget(self.biasDev, 4, 1)
        layout.addWidget(self.btnInitBlock, 5, 0, 1, 2)

        self.groupBlock.setLayout(layout)

    def createGroupVna(self):
        self.groupVna = QGroupBox("VNA config")
        layout = QGridLayout()

        self.vnaIPLabel = QLabel(self)
        self.vnaIPLabel.setText("VNA IP:")
        self.vna_ip = QLineEdit(self)
        self.vna_ip.setText(VNA_ADDRESS)

        self.vnaStatusLabel = QLabel(self)
        self.vnaStatusLabel.setText("VNA status:")
        self.vnaStatus = QLabel(self)
        self.vnaStatus.setText("VNA is not checked yet!")

        self.btnInitVna = QPushButton("Initialize VNA")
        self.btnInitVna.clicked.connect(self.initialize_vna)

        layout.addWidget(self.vnaIPLabel, 1, 0)
        layout.addWidget(self.vna_ip, 1, 1)
        layout.addWidget(self.vnaStatusLabel, 2, 0)
        layout.addWidget(self.vnaStatus, 2, 1)
        layout.addWidget(self.btnInitVna, 3, 0, 1, 2)

        self.groupVna.setLayout(layout)

    def initialize_block(self):
        block = Block()
        block.update(host=self.block_ip.text(), port=self.block_port.text())
        result = block.get_bias_data()
        logger.info(f"Health check SIS block {result}")

    def set_vna_status(self, status: str):
        self.vnaStatus.setText(status)

    def initialize_vna(self):
        self.thread = QThread()
        self.vna_worker = VNAWorker()

        self.vna_worker.moveToThread(self.thread)
        self.thread.started.connect(lambda: self.vna_worker.run(vna_ip=self.vna_ip.text()))
        self.vna_worker.finished.connect(self.thread.quit)
        self.vna_worker.finished.connect(self.vna_worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.vna_worker.status.connect(self.set_vna_status)
        self.thread.start()

        self.btnInitVna.setEnabled(False)
        self.thread.finished.connect(
            lambda: self.btnInitVna.setEnabled(True)
        )
