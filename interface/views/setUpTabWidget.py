import logging

from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt
from PyQt6.QtWidgets import (
    QStackedLayout,
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDoubleSpinBox,
    QSizePolicy,
)

from config import config
from api.block import Block
from api.rs_nrx import NRXBlock
from api.vna import VNABlock
from interface.components import CustomQDoubleSpinBox

logger = logging.getLogger(__name__)


class VNAWorker(QObject):
    finished = pyqtSignal()
    status = pyqtSignal(str)

    def run(self):
        vna = VNABlock(vna_ip=config.VNA_ADDRESS)
        result = vna.test()
        self.status.emit(config.VNA_TEST_MAP.get(result, "Error"))
        self.finished.emit()


class SISBlockWorker(QObject):
    finished = pyqtSignal()
    status = pyqtSignal(str)

    def run(self):
        block = Block(
            host=config.BLOCK_ADDRESS,
            port=config.BLOCK_PORT,
            bias_dev=config.BLOCK_BIAS_DEV,
            ctrl_dev=config.BLOCK_CTRL_DEV,
        )
        block.connect()
        result = block.test()
        # block.disconnect()
        logger.info(f"Health check SIS block {result}")
        self.status.emit(result)
        self.finished.emit()


class NRXBlockWorker(QObject):
    finished = pyqtSignal()
    status = pyqtSignal(str)

    def run(self):
        block = NRXBlock(
            ip=config.NRX_IP,
            filter_time=config.NRX_FILTER_TIME,
            aperture_time=config.NRX_APER_TIME,
        )
        result = block.test()
        block.disconnect()
        self.status.emit(config.NRX_TEST_MAP.get(result, "Error"))
        self.finished.emit()


class SetUpTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.createGroupBlock()
        self.createGroupVna()
        self.createGroupNRX()
        self.layout.addWidget(self.groupBlock)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupVna)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupNRX)
        self.layout.addSpacing(10)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupBlock(self):
        self.groupBlock = QGroupBox(self)
        self.groupBlock.setTitle("SIS Block config")
        self.groupBlock.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.blockIPLabel = QLabel(self)
        self.blockIPLabel.setText("Block IP:")
        self.block_ip = QLineEdit(self)
        self.block_ip.setText(config.BLOCK_ADDRESS)

        self.blockPortLabel = QLabel(self)
        self.blockPortLabel.setText("Block Port:")
        self.block_port = QDoubleSpinBox(self)
        self.block_port.setMaximum(10000)
        self.block_port.setDecimals(0)
        self.block_port.setValue(config.BLOCK_PORT)

        self.ctrlDevLabel = QLabel(self)
        self.biasDevLabel = QLabel(self)
        self.ctrlDev = QLineEdit(self)
        self.biasDev = QLineEdit(self)
        self.ctrlDevLabel.setText("CTRL Device:")
        self.biasDevLabel.setText("BIAS Device:")
        self.ctrlDev.setText(config.BLOCK_CTRL_DEV)
        self.biasDev.setText(config.BLOCK_BIAS_DEV)

        self.sisBlockStatusLabel = QLabel(self)
        self.sisBlockStatusLabel.setText("Block status:")
        self.sisBlockStatus = QLabel(self)
        self.sisBlockStatus.setText("SIS Block is not initialized yet!")

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
        layout.addWidget(self.sisBlockStatusLabel, 5, 0)
        layout.addWidget(self.sisBlockStatus, 5, 1)
        layout.addWidget(self.btnInitBlock, 6, 0, 1, 2)

        self.groupBlock.setLayout(layout)

    def createGroupVna(self):
        self.groupVna = QGroupBox(self)
        self.groupVna.setTitle("VNA config")
        self.groupVna.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.vnaIPLabel = QLabel(self)
        self.vnaIPLabel.setText("VNA IP:")
        self.vna_ip = QLineEdit(self)
        self.vna_ip.setText(config.VNA_ADDRESS)

        self.vnaStatusLabel = QLabel(self)
        self.vnaStatusLabel.setText("VNA status:")
        self.vnaStatus = QLabel(self)
        self.vnaStatus.setText("VNA is not initialized yet!")

        self.btnInitVna = QPushButton("Initialize VNA")
        self.btnInitVna.clicked.connect(self.initialize_vna)

        layout.addWidget(self.vnaIPLabel, 1, 0)
        layout.addWidget(self.vna_ip, 1, 1)
        layout.addWidget(self.vnaStatusLabel, 2, 0)
        layout.addWidget(self.vnaStatus, 2, 1)
        layout.addWidget(self.btnInitVna, 3, 0, 1, 2)

        self.groupVna.setLayout(layout)

    def createGroupNRX(self):
        self.groupNRX = QGroupBox(self)
        self.groupNRX.setTitle("Power meter config")
        self.groupNRX.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.nrxIPLabel = QLabel(self)
        self.nrxIPLabel.setText("PM IP:")
        self.nrxIP = QLineEdit(self)
        self.nrxIP.setText(config.NRX_IP)

        self.nrxAperTimeLabel = QLabel(self)
        self.nrxAperTimeLabel.setText("PM Averaging time, s:")
        self.nrxAperTime = CustomQDoubleSpinBox(self)
        self.nrxAperTime.setDecimals(2)
        self.nrxAperTime.setRange(1e-5, 1000)
        self.nrxAperTime.setValue(config.NRX_APER_TIME)

        self.nrxStatusLabel = QLabel(self)
        self.nrxStatusLabel.setText("PM status:")
        self.nrxStatus = QLabel(self)
        self.nrxStatus.setText("PM is not initialized yet!")

        self.btnInitNRX = QPushButton("Initialize PM")
        self.btnInitNRX.clicked.connect(self.initialize_nrx)

        layout.addWidget(self.nrxIPLabel, 1, 0)
        layout.addWidget(self.nrxIP, 1, 1)
        layout.addWidget(self.nrxAperTimeLabel, 2, 0)
        layout.addWidget(self.nrxAperTime, 2, 1)
        layout.addWidget(self.nrxStatusLabel, 3, 0)
        layout.addWidget(self.nrxStatus, 3, 1)
        layout.addWidget(self.btnInitNRX, 4, 0, 1, 2)

        self.groupNRX.setLayout(layout)

    def set_sis_block_status(self, status: str):
        self.sisBlockStatus.setText(status)

    def initialize_block(self):
        self.sis_thread = QThread()
        self.sis_worker = SISBlockWorker()

        config.BLOCK_ADDRESS = self.block_ip.text()
        config.BLOCK_PORT = int(self.block_port.value())
        config.BLOCK_BIAS_DEV = self.biasDev.text()
        config.BLOCK_CTRL_DEV = self.ctrlDev.text()

        self.sis_worker.moveToThread(self.sis_thread)
        self.sis_thread.started.connect(self.sis_worker.run)
        self.sis_worker.finished.connect(self.sis_thread.quit)
        self.sis_worker.finished.connect(self.sis_worker.deleteLater)
        self.sis_thread.finished.connect(self.sis_thread.deleteLater)
        self.sis_worker.status.connect(self.set_sis_block_status)
        self.sis_thread.start()

        self.btnInitBlock.setEnabled(False)
        self.sis_thread.finished.connect(lambda: self.btnInitBlock.setEnabled(True))

    def set_vna_status(self, status: str):
        self.vnaStatus.setText(status)

    def initialize_vna(self):
        self.vna_thread = QThread()
        self.vna_worker = VNAWorker()

        config.VNA_ADDRESS = self.vna_ip.text()

        self.vna_worker.moveToThread(self.vna_thread)
        self.vna_thread.started.connect(self.vna_worker.run)
        self.vna_worker.finished.connect(self.vna_thread.quit)
        self.vna_worker.finished.connect(self.vna_worker.deleteLater)
        self.vna_thread.finished.connect(self.vna_thread.deleteLater)
        self.vna_worker.status.connect(self.set_vna_status)
        self.vna_thread.start()

        self.btnInitVna.setEnabled(False)
        self.vna_thread.finished.connect(lambda: self.btnInitVna.setEnabled(True))

    def set_nrx_status(self, status: str):
        self.nrxStatus.setText(status)

    def initialize_nrx(self):
        self.nrx_thread = QThread()
        self.nrx_worker = NRXBlockWorker()

        config.NRX_IP = self.nrxIP.text()
        config.NRX_APER_TIME = self.nrxAperTime.value()

        self.nrx_worker.moveToThread(self.nrx_thread)
        self.nrx_thread.started.connect(self.nrx_worker.run)
        self.nrx_worker.finished.connect(self.nrx_thread.quit)
        self.nrx_worker.finished.connect(self.nrx_worker.deleteLater)
        self.nrx_thread.finished.connect(self.nrx_thread.deleteLater)
        self.nrx_worker.status.connect(self.set_nrx_status)
        self.nrx_thread.start()

        self.btnInitNRX.setEnabled(False)
        self.nrx_thread.finished.connect(lambda: self.btnInitNRX.setEnabled(True))
