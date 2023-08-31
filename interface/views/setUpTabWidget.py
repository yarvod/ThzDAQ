import logging

from PyQt6.QtCore import pyqtSignal, QThread, Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDoubleSpinBox,
    QSizePolicy,
    QComboBox,
    QScrollArea,
)

from api.Agilent.signal_generator import SignalGenerator
from api.LakeShore.temperature_controller import TemperatureController
from api.adapters.prologix_ethernet_adapter import PrologixEthernetAdapter
from api.Arduino.grid import GridManager
from interface.components.SetupSpectrum import SetupSpectrumWidget
from store.state import state
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from api.RohdeSchwarz.vna import VNABlock
from interface.components.DoubleSpinBox import DoubleSpinBox

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
        block = SisBlock(
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
        block = NRXPowerMeter(
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


class GridThread(QThread):
    status = pyqtSignal(str)

    def run(self):
        test_result, test_message = GridManager(host=state.GRID_ADDRESS).test()
        self.status.emit(test_message)
        self.finished.emit()


class SetUpTabWidget(QScrollArea):
    def __init__(self, parent):
        super().__init__(parent)
        self.widget = QWidget()
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.createGroupBlock()
        self.createGroupVna()
        self.createGroupNRX()
        self.createGroupPrologixEthernet()
        self.createGroupGrid()
        self.createGroupSignalGenerator()
        self.createGroupTemperatureController()

        self.layout.addWidget(self.groupBlock)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupVna)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupNRX)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupPrologixEthernet)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupGrid)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupSignalGenerator)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupTemperatureController)
        self.layout.addSpacing(10)
        self.layout.addWidget(SetupSpectrumWidget(self))
        self.layout.addStretch()

        self.widget.setLayout(self.layout)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setWidget(self.widget)

    def createGroupBlock(self):
        self.groupBlock = QGroupBox(self)
        self.groupBlock.setTitle("SIS Block")
        self.groupBlock.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.blockIPLabel = QLabel(self)
        self.blockIPLabel.setText("IP Address:")
        self.block_ip = QLineEdit(self)
        self.block_ip.setText(state.BLOCK_ADDRESS)

        self.blockPortLabel = QLabel(self)
        self.blockPortLabel.setText("Port:")
        self.block_port = QDoubleSpinBox(self)
        self.block_port.setMaximum(10000)
        self.block_port.setDecimals(0)
        self.block_port.setValue(state.BLOCK_PORT)

        self.ctrlDevLabel = QLabel(self)
        self.biasDevLabel = QLabel(self)
        self.ctrlDev = QComboBox(self)
        self.ctrlDev.addItems(["DEV1", "DEV3"])
        self.biasDev = QComboBox(self)
        self.biasDev.addItems(["DEV2", "DEV4"])
        self.ctrlDevLabel.setText("CTRL Device:")
        self.biasDevLabel.setText("BIAS Device:")
        self.ctrlDev.setCurrentText(state.BLOCK_CTRL_DEV)
        self.biasDev.setCurrentText(state.BLOCK_BIAS_DEV)

        self.sisBlockStatusLabel = QLabel(self)
        self.sisBlockStatusLabel.setText("Status:")
        self.sisBlockStatus = QLabel(self)
        self.sisBlockStatus.setText("Doesn't initialized yet!")

        self.btnInitBlock = QPushButton("Initialize")
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
        self.vnaIPLabel.setText("IP Address:")
        self.vna_ip = QLineEdit(self)
        self.vna_ip.setText(state.VNA_ADDRESS)

        self.vnaStatusLabel = QLabel(self)
        self.vnaStatusLabel.setText("Status:")
        self.vnaStatus = QLabel(self)
        self.vnaStatus.setText("Doesn't initialized yet!")

        self.btnInitVna = QPushButton("Initialize")
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
        self.nrxIPLabel.setText("IP Address:")
        self.nrxIP = QLineEdit(self)
        self.nrxIP.setText(state.NRX_IP)

        self.nrxAperTimeLabel = QLabel(self)
        self.nrxAperTimeLabel.setText("Averaging time, s:")
        self.nrxAperTime = DoubleSpinBox(self)
        self.nrxAperTime.setDecimals(2)
        self.nrxAperTime.setRange(0.01, 1000)
        self.nrxAperTime.setValue(state.NRX_APER_TIME)

        self.nrxStatusLabel = QLabel(self)
        self.nrxStatusLabel.setText("Status:")
        self.nrxStatus = QLabel(self)
        self.nrxStatus.setText("Doesn't initialized yet!")

        self.btnInitNRX = QPushButton("Initialize")
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
        self.prologixIPAdressLabel.setText("IP Address:")
        self.prologixIPAdress = QLineEdit(self)
        self.prologixIPAdress.setText(state.PROLOGIX_IP)

        self.prologixEthernetStatusLabel = QLabel(self)
        self.prologixEthernetStatusLabel.setText("Status:")
        self.prologixEthernetStatus = QLabel(self)
        self.prologixEthernetStatus.setText("Doesn't initialized yet!")

        self.btnInitPrologixEthernet = QPushButton("Initialize Prologix")
        self.btnInitPrologixEthernet.clicked.connect(self.initialize_prologix_ethernet)

        layout.addWidget(self.prologixIPAdressLabel, 1, 0)
        layout.addWidget(self.prologixIPAdress, 1, 1)
        layout.addWidget(self.prologixEthernetStatusLabel, 2, 0)
        layout.addWidget(self.prologixEthernetStatus, 2, 1)
        layout.addWidget(self.btnInitPrologixEthernet, 3, 0, 1, 2)

        self.groupPrologixEthernet.setLayout(layout)

    def createGroupGrid(self):
        self.groupGrid = QGroupBox("GRID")
        self.groupGrid.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.gridAddressLabel = QLabel(self)
        self.gridAddressLabel.setText("IP Address:")
        self.gridAddress = QLineEdit(self)
        self.gridAddress.setText(state.GRID_ADDRESS)

        self.gridStatusLabel = QLabel(self)
        self.gridStatusLabel.setText("Status:")
        self.gridStatus = QLabel(self)
        self.gridStatus.setText("Doesn't initialized yet!")

        self.btnInitGrid = QPushButton("Initialize")
        self.btnInitGrid.clicked.connect(self.initialize_grid)

        layout.addWidget(self.gridAddressLabel, 1, 0)
        layout.addWidget(self.gridAddress, 1, 1)
        layout.addWidget(self.gridStatusLabel, 2, 0)
        layout.addWidget(self.gridStatus, 2, 1)
        layout.addWidget(self.btnInitGrid, 3, 0, 1, 2)

        self.groupGrid.setLayout(layout)

    def createGroupSignalGenerator(self):
        self.groupSignalGenerator = QGroupBox("Signal generator")
        self.groupGrid.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.signalGeneratorAddressLabel = QLabel(self)
        self.signalGeneratorAddressLabel.setText("GPIB Address:")
        self.signalGeneratorAddress = QDoubleSpinBox(self)
        self.signalGeneratorAddress.setRange(1, 32)
        self.signalGeneratorAddress.setValue(state.AGILENT_SIGNAL_GENERATOR_GPIB)
        self.signalGeneratorAddress.setDecimals(0)

        self.signalGeneratorStatusLabel = QLabel(self)
        self.signalGeneratorStatusLabel.setText("Status:")
        self.signalGeneratorStatus = QLabel(self)
        self.signalGeneratorStatus.setText("Doesn't initialized yet!")

        self.btnSignalGeneratorInit = QPushButton("Initialize")
        self.btnSignalGeneratorInit.clicked.connect(self.initialize_signal_generator)

        layout.addWidget(self.signalGeneratorAddressLabel, 1, 0)
        layout.addWidget(self.signalGeneratorAddress, 1, 1)
        layout.addWidget(self.signalGeneratorStatusLabel, 2, 0)
        layout.addWidget(self.signalGeneratorStatus, 2, 1)
        layout.addWidget(self.btnSignalGeneratorInit, 3, 0, 1, 2)

        self.groupSignalGenerator.setLayout(layout)

    def createGroupTemperatureController(self):
        self.groupTemperatureController = QGroupBox("Temperature controller")
        self.groupGrid.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QGridLayout()

        self.temperatureControllerAddressLabel = QLabel(self)
        self.temperatureControllerAddressLabel.setText("IP Address:")
        self.temperatureControllerAddress = QLineEdit(self)
        self.temperatureControllerAddress.setText(state.LAKE_SHORE_IP)

        self.temperatureControllerStatusLabel = QLabel(self)
        self.temperatureControllerStatusLabel.setText("Status:")
        self.temperatureControllerStatus = QLabel(self)
        self.temperatureControllerStatus.setText("Doesn't initialized yet!")

        self.btnTemperatureControllerInit = QPushButton("Initialize")
        self.btnTemperatureControllerInit.clicked.connect(
            self.initialize_temperature_controller
        )

        layout.addWidget(self.temperatureControllerAddressLabel, 1, 0)
        layout.addWidget(self.temperatureControllerAddress, 1, 1)
        layout.addWidget(self.temperatureControllerStatusLabel, 2, 0)
        layout.addWidget(self.temperatureControllerStatus, 2, 1)
        layout.addWidget(self.btnTemperatureControllerInit, 3, 0, 1, 2)

        self.groupTemperatureController.setLayout(layout)

    def initialize_temperature_controller(self):
        state.LAKE_SHORE_IP = self.temperatureControllerAddress.text()
        tc = TemperatureController(host=state.LAKE_SHORE_IP, port=state.LAKE_SHORE_PORT)
        result = tc.test()
        self.temperatureControllerStatus.setText(result)

    def initialize_signal_generator(self):
        state.AGILENT_SIGNAL_GENERATOR_GPIB = self.signalGeneratorAddress.value()
        sg = SignalGenerator(
            host=state.PROLOGIX_IP, gpib=state.AGILENT_SIGNAL_GENERATOR_GPIB
        )
        result = sg.test()
        self.signalGeneratorStatus.setText(result)

    def initialize_grid(self):
        state.GRID_ADDRESS = self.gridAddress.text()
        self.grid_thread = GridThread()
        self.grid_thread.status.connect(self.set_grid_status)
        self.grid_thread.start()
        self.btnInitGrid.setEnabled(False)
        self.grid_thread.finished.connect(lambda: self.btnInitGrid.setEnabled(True))

    def set_grid_status(self, status):
        self.gridStatus.setText(status)

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
        state.BLOCK_BIAS_DEV = self.biasDev.currentText()
        state.BLOCK_CTRL_DEV = self.ctrlDev.currentText()

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
