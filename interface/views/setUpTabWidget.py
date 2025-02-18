import logging
import textwrap

from PySide6.QtCore import Signal, QThread
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QDoubleSpinBox,
    QSizePolicy,
    QComboBox,
)

from api.Arduino.grid import GridManager
from interface.components.Agilent.setUpSignalGenerator import (
    SetUpAgilentSignalGenerator,
)
from interface.components.Lakeshore.setUpTemperatureController import (
    SetUpLakeshoreTemperatureControllerWidget,
)
from interface.components.Rigol.setUpRigolPowerSupply import SetUpRigolPowerSupplyWidget
from interface.components.RohdeSchwarz.setUpVnaZva67 import SetUpVnaZva67Widget
from interface.components.Sumitomo import SetUpSumitomoF70Widget
from interface.components.chopper.SetupChopperGroup import SetupChopperGroup
from interface.components.RohdeSchwarz.setUpSpectrumFsek30 import (
    SetUpSpectrumFsek30Widget,
)
from interface.components.keithley.setUpKeithley import SetUpKeithley
from interface.components.power_meter.setUpPowerMeter import SetUpPowerMeter
from interface.components.prologix.setUpPrologix import SetUpPrologix
from interface.components.ui.Button import Button
from interface.components.yig.setupDigitalYig import SetUpDigitalYigGroup
from store.state import state
from api.Scontel.sis_block import SisBlock

logger = logging.getLogger(__name__)


class SISBlockThread(QThread):
    status = Signal(str)

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
    status = Signal(str)

    def run(self):
        test_result, test_message = GridManager(host=state.GRID_ADDRESS).test()
        self.status.emit(test_message)
        self.finished.emit()


class SetUpTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)

        self.searchLine = QLineEdit(self)
        self.searchLine.setPlaceholderText("Search device")
        self.searchLine.textChanged.connect(self.search_device)

        self.createGroupBlock()
        self.createGroupGrid()

        self.layout.addWidget(self.searchLine)
        self.layout.addWidget(self.groupBlock)
        self.layout.addWidget(SetUpVnaZva67Widget(self))
        self.layout.addWidget(SetUpPowerMeter(self))
        self.layout.addWidget(SetUpPrologix(self))
        self.layout.addWidget(self.groupGrid)
        self.layout.addWidget(SetUpAgilentSignalGenerator(self))
        self.layout.addWidget(SetUpLakeshoreTemperatureControllerWidget(self))
        self.layout.addWidget(SetUpSpectrumFsek30Widget(self))
        self.layout.addWidget(SetupChopperGroup(self))
        self.layout.addWidget(SetUpDigitalYigGroup(self))
        self.layout.addWidget(SetUpKeithley(self))
        self.layout.addWidget(SetUpRigolPowerSupplyWidget(self))
        self.layout.addWidget(SetUpSumitomoF70Widget(self))
        self.layout.addStretch()

        self.setLayout(self.layout)

        self.widgets = []
        self.load_widgets()

    def load_widgets(self):
        for i in range(self.layout.count()):
            widget = self.layout.itemAt(i).widget()
            if not widget or type(widget) == QLineEdit:
                continue
            self.widgets.append(widget)

    def search_device(self, value: str):
        if not value:
            for widget in self.widgets:
                widget.show()
            return
        for widget in self.widgets:
            if value.lower() in widget.title().lower():
                widget.show()
            else:
                widget.hide()

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
