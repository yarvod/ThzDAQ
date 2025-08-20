import logging

from PySide6.QtCore import Signal, QThread
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
)

from api.Arduino.grid import GridDevice
from interface.components.Agilent.setUpSignalGenerator import (
    SetUpAgilentSignalGenerator,
)
from interface.components.Lakeshore.setUpTemperatureController import (
    SetUpLakeshoreTemperatureControllerWidget,
)
from interface.components.Rigol.setUpRigolPowerSupply import SetUpRigolPowerSupplyWidget
from interface.components.RohdeSchwarz.setUpRSPowerSupply import (
    SetUpRSPowerSupplyWidget,
)
from interface.components.RohdeSchwarz.setUpVnaZva67 import SetUpVnaZva67Widget
from interface.components.Scontel.setUpScontelSisBlockWidget import (
    SetUpScontelSisBlockWidget,
)
from interface.components.Sumitomo import SetUpSumitomoF70Widget
from interface.components.chopper.SetupChopperGroup import SetupChopperGroup
from interface.components.RohdeSchwarz.setUpSpectrumFsek30 import (
    SetUpSpectrumFsek30Widget,
)
from interface.components.grid.setUpGridWidget import SetUpGridWidget
from interface.components.keithley.setUpKeithley import SetUpKeithley
from interface.components.power_meter.setUpPowerMeter import SetUpPowerMeter
from interface.components.prologix.setUpPrologix import SetUpPrologix
from interface.components.yig.setupDigitalYig import SetUpDigitalYigGroup
from store.state import state

logger = logging.getLogger(__name__)


class GridThread(QThread):
    status = Signal(str)

    def run(self):
        test_result, test_message = GridDevice(host=state.GRID_ADDRESS).test()
        self.status.emit(test_message)
        self.finished.emit()


class SetUpTabWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)

        self.searchLine = QLineEdit(self)
        self.searchLine.setPlaceholderText("Search device")
        self.searchLine.textChanged.connect(self.search_device)

        self.layout.addWidget(self.searchLine)
        self.layout.addWidget(SetUpScontelSisBlockWidget(self))
        self.layout.addWidget(SetUpVnaZva67Widget(self))
        self.layout.addWidget(SetUpPowerMeter(self))
        self.layout.addWidget(SetUpPrologix(self))
        self.layout.addWidget(SetUpGridWidget(self))
        self.layout.addWidget(SetUpAgilentSignalGenerator(self))
        self.layout.addWidget(SetUpLakeshoreTemperatureControllerWidget(self))
        self.layout.addWidget(SetUpSpectrumFsek30Widget(self))
        self.layout.addWidget(SetupChopperGroup(self))
        self.layout.addWidget(SetUpDigitalYigGroup(self))
        self.layout.addWidget(SetUpKeithley(self))
        self.layout.addWidget(SetUpRigolPowerSupplyWidget(self))
        self.layout.addWidget(SetUpRSPowerSupplyWidget(self))
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
