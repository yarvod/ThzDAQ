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
    QSizePolicy,
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
from interface.components.Scontel.setUpScontelSisBlockWidget import (
    SetUpScontelSisBlockWidget,
)
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

logger = logging.getLogger(__name__)


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

        self.createGroupGrid()

        self.layout.addWidget(self.searchLine)
        self.layout.addWidget(SetUpScontelSisBlockWidget(self))
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
