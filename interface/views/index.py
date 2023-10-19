from PyQt5.QtWidgets import QWidget, QVBoxLayout

from interface.components.ui.DetachableTabWidget import DetachableTabWidget
from interface.views.blockTabWidget import BlockTabWidget
from interface.views.chopperTabWidget import ChopperTabWidget
from interface.views.measureDataTabWidget import MeasureDataTabWidget
from interface.views.nrxTabWidget import NRXTabWidget
from interface.views.setUpTabWidget import SetUpTabWidget
from interface.views.signalGeneratorTabWidget import SignalGeneratorTabWidget
from interface.views.GridTabWidget import GridTabWidget
from interface.views.spectrumTabWidget import SpectrumTabWidget
from interface.views.temperatureControllerTabWidget import (
    TemperatureControllerTabWidget,
)
from interface.views.vnaTabWidget import VNATabWidget


class TabsWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.tabs_list = [
            "Set Up",
            "Data",
            "SIS Block",
            "VNA",
            "Power Meter",
            "Signal Generator",
            "GRID",
            "Temperature",
            "Spectrum",
            "Chopper",
        ]
        # Initialize tab screen
        self.tabs = DetachableTabWidget(self, tabs_list=self.tabs_list)
        self.tab_setup = SetUpTabWidget(self)
        self.tab_data = MeasureDataTabWidget(self)
        self.tab_block = BlockTabWidget(self)
        self.tab_vna = VNATabWidget(self)
        self.tab_nrx = NRXTabWidget(self)
        self.tab_signal_generator = SignalGeneratorTabWidget(self)
        self.tab_grid = GridTabWidget(self)
        self.tab_temperature = TemperatureControllerTabWidget(self)
        self.tab_spectrum = SpectrumTabWidget(self)
        self.tab_chopper = ChopperTabWidget(self)
        self.tabs.resize(300, 200)

        # Add tabs
        self.tabs.addTab(self.tab_setup, "Set Up")
        self.tabs.addTab(self.tab_data, "Data")
        self.tabs.addTab(self.tab_block, "SIS Block")
        self.tabs.addTab(self.tab_vna, "VNA")
        self.tabs.addTab(self.tab_nrx, "Power Meter")
        self.tabs.addTab(self.tab_signal_generator, "Signal Generator")
        self.tabs.addTab(self.tab_grid, "GRID")
        self.tabs.addTab(self.tab_temperature, "Temperature")
        self.tabs.addTab(self.tab_spectrum, "Spectrum")
        self.tabs.addTab(self.tab_chopper, "Chopper")

        # Add tabs to widget
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)
