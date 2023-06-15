from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from interface.views.blockTabWidget import BlockTabWidget
from interface.views.nrxTabWidget import NRXTabWidget
from interface.views.setUpTabWidget import SetUpTabWidget
from interface.views.vnaTabWidget import VNATabWidget


class TabsWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)

        # Initialize tab screen
        self.tabs = QTabWidget(self)
        self.tab_setup = SetUpTabWidget(self)
        self.tab_block = BlockTabWidget(self)
        self.tab_vna = VNATabWidget(self)
        self.tab_nrx = NRXTabWidget(self)
        self.tabs.resize(300, 200)

        # Add tabs
        self.tabs.addTab(self.tab_setup, "Set Up")
        self.tabs.addTab(self.tab_block, "SIS Block")
        self.tabs.addTab(self.tab_vna, "VNA")
        self.tabs.addTab(self.tab_nrx, "Power Meter")

        # Add tabs to widget
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)
