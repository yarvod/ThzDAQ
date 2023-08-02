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

from api.adapters.prologix_ethernet_adapter import PrologixEthernetAdapter
from state import state
from api.block import Block
from api.rs_nrx import NRXBlock
from api.vna import VNABlock
from interface.components import CustomQDoubleSpinBox

logger = logging.getLogger(__name__)


class VNAThread(QThread):
    status = pyqtSignal(str)

    def run(self):
        logger.info(f"[{self.__class__.__name__}.run] Running...")
        vna = VNABlock(vna_ip=state.VNA_ADDRESS)
        result = vna.test()
        self.status.emit(state.VNA_TEST_MAP.get(result, "Error"))
        self.finished.emit()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")

    def quit(self) -> None:
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")


class SISBlockThread(QThread):
    status = pyqtSignal(str)

    def run(self):
        logger.info(f"[{self.__class__.__name__}.run] Running...")
        block = Block(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()
        result = block.test()
        logger.info(f"[{self.__class__.__name__}.run]Health check SIS block {result}")
        self.status.emit(result)
        self.finished.emit()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")

    def quit(self) -> None:
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")


class NRXBlockThread(QThread):
    status = pyqtSignal(str)

    def run(self):
        logger.info(f"[{self.__class__.__name__}.run] Running...")
        block = NRXBlock(
            ip=state.NRX_IP,
            filter_time=state.NRX_FILTER_TIME,
            aperture_time=state.NRX_APER_TIME,
        )
        result = block.test()
        self.status.emit(state.NRX_TEST_MAP.get(result, "Error"))
        self.finished.emit()

    def terminate(self):
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")

    def quit(self) -> None:
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")


class PrologixEthernetThread(QThread):
    status = pyqtSignal(bool)

    def run(self):
        try:
            # define and close existing prologix instance
            prologix = PrologixEthernetAdapter(host=state.PROLOGIX_IP)
            prologix.close()
            # Set new IP for prologix and connect again
            prologix.host = state.PROLOGIX_IP
            prologix.init()
            logger.info(
                f"[{self.__class__.__name__}.run] Prologix Ethernet Initialized"
            )
            self.status.emit(True)
        except:
            logger.error(
                f"[{self.__class__.__name__}.run] Prologix Ethernet unable to initialize"
            )
            self.status.emit(False)

        self.finished.emit()


class SetUpTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.createGroupBlock()
        self.createGroupVna()
        self.createGroupNRX()
        self.createGroupPrologixEthernet()
        self.layout.addWidget(self.groupBlock)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupVna)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupNRX)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupPrologixEthernet)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupBlock(self):
        self.groupBlock = QGroupBox(self)
        self.groupBlock.setTitle("SIS Block")
        self.groupBlock.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.blockIPLabel = QLabel(self)
        self.blockIPLabel.setText("Block IP:")
        self.block_ip = QLineEdit(self)
        self.block_ip.setText(state.BLOCK_ADDRESS)

        self.blockPortLabel = QLabel(self)
        self.blockPortLabel.setText("Block Port:")
        self.block_port = QDoubleSpinBox(self)
        self.block_port.setMaximum(10000)
        self.block_port.setDecimals(0)
        self.block_port.setValue(state.BLOCK_PORT)

        self.ctrlDevLabel = QLabel(self)
        self.biasDevLabel = QLabel(self)
        self.ctrlDev = QLineEdit(self)
        self.biasDev = QLineEdit(self)
        self.ctrlDevLabel.setText("CTRL Device:")
        self.biasDevLabel.setText("BIAS Device:")
        self.ctrlDev.setText(state.BLOCK_CTRL_DEV)
        self.biasDev.setText(state.BLOCK_BIAS_DEV)

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
        self.groupVna.setTitle("VNA")
        self.groupVna.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.vnaIPLabel = QLabel(self)
        self.vnaIPLabel.setText("VNA IP:")
        self.vna_ip = QLineEdit(self)
        self.vna_ip.setText(state.VNA_ADDRESS)

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
        self.groupNRX.setTitle("Power meter")
        self.groupNRX.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.nrxIPLabel = QLabel(self)
        self.nrxIPLabel.setText("PM IP:")
        self.nrxIP = QLineEdit(self)
        self.nrxIP.setText(state.NRX_IP)

        self.nrxAperTimeLabel = QLabel(self)
        self.nrxAperTimeLabel.setText("PM Averaging time, s:")
        self.nrxAperTime = CustomQDoubleSpinBox(self)
        self.nrxAperTime.setDecimals(2)
        self.nrxAperTime.setRange(1e-5, 1000)
        self.nrxAperTime.setValue(state.NRX_APER_TIME)

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

    def createGroupPrologixEthernet(self):
        self.groupPrologixEthernet = QGroupBox("Prologix Ethernet")
        self.groupPrologixEthernet.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.prologixIPAdressLabel = QLabel(self)
        self.prologixIPAdressLabel.setText("IP address:")
        self.prologixIPAdress = QLineEdit(self)
        self.prologixIPAdress.setText(state.PROLOGIX_IP)

        self.prologixEthernetStatusLabel = QLabel(self)
        self.prologixEthernetStatusLabel.setText("Status:")
        self.prologixEthernetStatus = QLabel(self)
        self.prologixEthernetStatus.setText("Prologix is not initialized yet!")

        self.btnInitPrologixEthernet = QPushButton("Initialize Prologix")
        self.btnInitPrologixEthernet.clicked.connect(self.initialize_prologix_ethernet)

        layout.addWidget(self.prologixIPAdressLabel, 1, 0)
        layout.addWidget(self.prologixIPAdress, 1, 1)
        layout.addWidget(self.prologixEthernetStatusLabel, 2, 0)
        layout.addWidget(self.prologixEthernetStatus, 2, 1)
        layout.addWidget(self.btnInitPrologixEthernet, 3, 0, 1, 2)

        self.groupPrologixEthernet.setLayout(layout)

    def initialize_prologix_ethernet(self):
        self.prologix_ethernet_thread = PrologixEthernetThread()

        state.PROLOGIX_IP = self.prologixIPAdress.text()

        self.prologix_ethernet_thread.status.connect(self.set_prologix_ethernet_status)
        self.prologix_ethernet_thread.start()

        self.btnInitPrologixEthernet.setEnabled(False)
        self.prologix_ethernet_thread.finished.connect(
            lambda: self.btnInitPrologixEthernet.setEnabled(True)
        )

    def set_prologix_ethernet_status(self, status: bool):
        if status:
            self.prologixEthernetStatus.setText("Ok")
        else:
            self.prologixEthernetStatus.setText("Error!")

    def set_sis_block_status(self, status: str):
        self.sisBlockStatus.setText(status)

    def initialize_block(self):
        self.sis_block_thread = SISBlockThread()

        state.BLOCK_ADDRESS = self.block_ip.text()
        state.BLOCK_PORT = int(self.block_port.value())
        state.BLOCK_BIAS_DEV = self.biasDev.text()
        state.BLOCK_CTRL_DEV = self.ctrlDev.text()

        self.sis_block_thread.status.connect(self.set_sis_block_status)
        self.sis_block_thread.start()

        self.btnInitBlock.setEnabled(False)
        self.sis_block_thread.finished.connect(
            lambda: self.btnInitBlock.setEnabled(True)
        )

    def set_vna_status(self, status: str):
        self.vnaStatus.setText(status)

    def initialize_vna(self):
        self.vna_thread = VNAThread()
        self.vna_thread.status.connect(self.set_vna_status)

        state.VNA_ADDRESS = self.vna_ip.text()
        self.vna_thread.start()

        self.btnInitVna.setEnabled(False)
        self.vna_thread.finished.connect(lambda: self.btnInitVna.setEnabled(True))

    def set_nrx_status(self, status: str):
        self.nrxStatus.setText(status)

    def initialize_nrx(self):
        self.nrx_thread = NRXBlockThread()
        self.nrx_thread.status.connect(self.set_nrx_status)
        state.NRX_IP = self.nrxIP.text()
        state.NRX_APER_TIME = self.nrxAperTime.value()
        self.nrx_thread.start()

        self.btnInitNRX.setEnabled(False)
        self.nrx_thread.finished.connect(lambda: self.btnInitNRX.setEnabled(True))
