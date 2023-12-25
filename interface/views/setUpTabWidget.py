import logging
import textwrap

from PyQt5.QtCore import pyqtSignal, QThread, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QDoubleSpinBox,
    QSizePolicy,
    QComboBox,
    QScrollArea,
    QSpinBox,
    QFormLayout,
)

from api.Agilent.signal_generator import SignalGenerator
from api.LakeShore.temperature_controller import TemperatureController
from api.Arduino.grid import GridManager
from interface.components.Agilent.setUpSignalGenerator import (
    SetUpAgilentSignalGenerator,
)
from interface.components.Rigol.setUpRigolPowerSupply import SetUpRigolPowerSupplyWidget
from interface.components.chopper.SetupChopperGroup import SetupChopperGroup
from interface.components.Spectrum.SetupSpectrumGroup import SetupSpectrumGroup
from interface.components.keithley.setUpKeithley import SetUpKeithley
from interface.components.power_meter.setUpPowerMeter import SetUpPowerMeter
from interface.components.prologix.setUpPrologix import SetUpPrologix
from interface.components.ui.Button import Button
from interface.components.yig.setupDigitalYig import SetUpDigitalYigGroup
from store.state import state
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.vna import VNABlock

logger = logging.getLogger(__name__)


class VNAThread(QThread):
    status = pyqtSignal(str)

    def run(self):
        logger.info(f"[{self.__class__.__name__}.run] Running...")
        vna = VNABlock(
            vna_ip=state.VNA_ADDRESS,
            port=state.VNA_PORT,
            start=state.VNA_FREQ_START,
            stop=state.VNA_FREQ_STOP,
            points=state.VNA_POINTS,
            power=state.VNA_POWER,
        )
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
        self.createGroupBlock()
        self.createGroupVna()
        self.createGroupGrid()
        self.createGroupTemperatureController()

        self.layout.addWidget(self.groupBlock)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupVna)
        self.layout.addSpacing(10)
        self.layout.addWidget(SetUpPowerMeter(self))
        self.layout.addSpacing(10)
        self.layout.addWidget(SetUpPrologix(self))
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupGrid)
        self.layout.addSpacing(10)
        self.layout.addWidget(SetUpAgilentSignalGenerator(self))
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupTemperatureController)
        self.layout.addSpacing(10)
        self.layout.addWidget(SetupSpectrumGroup(self))
        self.layout.addSpacing(10)
        self.layout.addWidget(SetupChopperGroup(self))
        self.layout.addSpacing(10)
        self.layout.addWidget(SetUpDigitalYigGroup(self))
        self.layout.addWidget(SetUpKeithley(self))
        self.layout.addWidget(SetUpRigolPowerSupplyWidget(self))
        self.layout.addStretch()

        self.widget.setLayout(self.layout)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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

        self.btnInitBlock = Button("Initialize", animate=True)
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

        self.btnInitVna = Button("Initialize", animate=True)
        self.btnInitVna.clicked.connect(self.initialize_vna)

        layout.addWidget(self.vnaIPLabel, 1, 0)
        layout.addWidget(self.vna_ip, 1, 1)
        layout.addWidget(self.vnaStatusLabel, 2, 0)
        layout.addWidget(self.vnaStatus, 2, 1)
        layout.addWidget(self.btnInitVna, 3, 0, 1, 2)

        self.groupVna.setLayout(layout)

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

        self.btnInitGrid = Button("Initialize", animate=True)
        self.btnInitGrid.clicked.connect(self.initialize_grid)

        layout.addWidget(self.gridAddressLabel, 1, 0)
        layout.addWidget(self.gridAddress, 1, 1)
        layout.addWidget(self.gridStatusLabel, 2, 0)
        layout.addWidget(self.gridStatus, 2, 1)
        layout.addWidget(self.btnInitGrid, 3, 0, 1, 2)

        self.groupGrid.setLayout(layout)

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

        self.btnTemperatureControllerInit = Button("Initialize", animate=True)
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

    def initialize_grid(self):
        state.GRID_ADDRESS = self.gridAddress.text()
        self.grid_thread = GridThread()
        self.grid_thread.status.connect(self.set_grid_status)
        self.grid_thread.start()
        self.btnInitGrid.setEnabled(False)
        self.grid_thread.finished.connect(lambda: self.btnInitGrid.setEnabled(True))

    def set_grid_status(self, status: str):
        status = status.replace("'", "")
        short_status = textwrap.shorten(status, width=40, placeholder="...")
        self.gridStatus.setText(short_status)
        self.gridStatus.setToolTip(status)

    def initialize_block(self):
        self.sis_block_thread = SISBlockThread()

        state.BLOCK_ADDRESS = self.block_ip.text()
        state.BLOCK_PORT = int(self.block_port.value())
        state.BLOCK_BIAS_DEV = self.biasDev.currentText()
        state.BLOCK_CTRL_DEV = self.ctrlDev.currentText()

        self.sis_block_thread.status.connect(
            lambda status: self.sisBlockStatus.setText(status)
        )
        self.sis_block_thread.start()

        self.btnInitBlock.setEnabled(False)
        self.sis_block_thread.finished.connect(
            lambda: self.btnInitBlock.setEnabled(True)
        )

    def initialize_vna(self):
        self.vna_thread = VNAThread()
        self.vna_thread.status.connect(lambda x: self.vnaStatus.setText(x))

        state.VNA_ADDRESS = self.vna_ip.text()
        self.vna_thread.start()

        self.btnInitVna.setEnabled(False)
        self.vna_thread.finished.connect(lambda: self.btnInitVna.setEnabled(True))
