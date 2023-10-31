from PyQt5.QtCore import QSignalBlocker, QSettings
from PyQt5.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QCheckBox,
    QApplication,
    QMenu,
    QAction,
    QWidgetAction,
    QComboBox,
    QSizePolicy,
    QInputDialog,
    QToolBar,
)
from PyQt5 import QtGui
from PyQtAds import ads as QtAds


from interface import style
from interface.views.GridTabWidget import GridTabWidget
from interface.views.blockTabWidget import BlockTabWidget
from interface.views.chopperTabWidget import ChopperTabWidget
from interface.views.measureDataTabWidget import MeasureDataTabWidget
from interface.views.nrxTabWidget import NRXTabWidget
from interface.views.setUpTabWidget import SetUpTabWidget
from interface.views.signalGeneratorTabWidget import SignalGeneratorTabWidget
from interface.views.spectrumTabWidget import SpectrumTabWidget
from interface.views.temperatureControllerTabWidget import (
    TemperatureControllerTabWidget,
)
from interface.views.vnaTabWidget import VNATabWidget
from store.base import MeasureManager


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.title = "SIS manager"
        self.left = 0
        self.top = 0
        self.width = 1300
        self.height = 700
        self.icon = QtGui.QIcon("./assets/logo_small.png")
        self.setWindowIcon(self.icon)
        self.setStyleSheet(style.GLOBAL_STYLE)
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

        self.settings = QSettings("ASC", self.title)

        QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.OpaqueSplitterResize, True)
        QtAds.CDockManager.setConfigFlag(
            QtAds.CDockManager.XmlCompressionEnabled, False
        )
        QtAds.CDockManager.setConfigFlag(QtAds.CDockManager.FocusHighlighting, True)

        self.menuBar = self.menuBar()
        self.menuView = QMenu("View", self)
        self.menuBar.addMenu(self.menuView)

        self.dock_manager = QtAds.CDockManager(self)

        self.setup_dock_widget = QtAds.CDockWidget("SetUp")
        self.tab_setup = SetUpTabWidget(self)
        self.setup_dock_widget.setWidget(self.tab_setup)
        self.menuView.addAction(self.setup_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidget(
            QtAds.LeftDockWidgetArea, self.setup_dock_widget
        )

        self.data_dock_widget = QtAds.CDockWidget("Data")
        self.tab_data = MeasureDataTabWidget(self)
        self.data_dock_widget.setWidget(self.tab_data)
        self.menuView.addAction(self.data_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.LeftDockWidgetArea, self.data_dock_widget
        )

        self.sis_block_dock_widget = QtAds.CDockWidget("SIS Block")
        self.tab_sis_block = BlockTabWidget(self)
        self.sis_block_dock_widget.setWidget(self.tab_sis_block)
        self.menuView.addAction(self.sis_block_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidget(
            QtAds.RightDockWidgetArea, self.sis_block_dock_widget
        )

        self.vna_dock_widget = QtAds.CDockWidget("VNA")
        self.tab_vna = VNATabWidget(self)
        self.vna_dock_widget.setWidget(self.tab_vna)
        self.menuView.addAction(self.vna_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.vna_dock_widget
        )

        self.nrx_dock_widget = QtAds.CDockWidget("Power Meter")
        self.tab_nrx = NRXTabWidget(self)
        self.nrx_dock_widget.setWidget(self.tab_nrx)
        self.menuView.addAction(self.nrx_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.nrx_dock_widget
        )

        self.signal_generator_dock_widget = QtAds.CDockWidget("Signal Generator")
        self.tab_signal_generator = SignalGeneratorTabWidget(self)
        self.signal_generator_dock_widget.setWidget(self.tab_signal_generator)
        self.menuView.addAction(self.signal_generator_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.signal_generator_dock_widget
        )

        self.grid_dock_widget = QtAds.CDockWidget("GRID")
        self.tab_grid = GridTabWidget(self)
        self.grid_dock_widget.setWidget(self.tab_grid)
        self.menuView.addAction(self.grid_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.grid_dock_widget
        )

        self.temperature_dock_widget = QtAds.CDockWidget("Temperature Controller")
        self.tab_temperature = TemperatureControllerTabWidget(self)
        self.temperature_dock_widget.setWidget(self.tab_temperature)
        self.menuView.addAction(self.temperature_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.temperature_dock_widget
        )

        self.spectrum_dock_widget = QtAds.CDockWidget("Spectrum")
        self.tab_spectrum = SpectrumTabWidget(self)
        self.spectrum_dock_widget.setWidget(self.tab_spectrum)
        self.menuView.addAction(self.spectrum_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.spectrum_dock_widget
        )

        self.chopper_dock_widget = QtAds.CDockWidget("Chopper")
        self.tab_chopper = ChopperTabWidget(self)
        self.chopper_dock_widget.setWidget(self.tab_chopper)
        self.menuView.addAction(self.chopper_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.chopper_dock_widget
        )

        self.setup_dock_widget.raise_()
        self.sis_block_dock_widget.raise_()

        self.toolBar = QToolBar("Main ToolBar")
        self.addToolBar(self.toolBar)

        self.create_perspective_ui()
        saved_state = self.settings.value("dock_manager_state")
        if saved_state:
            self.dock_manager.restoreState(saved_state)

        self.show()

    def create_perspective_ui(self):
        save_perspective_action = QAction("Create Perspective", self)
        save_perspective_action.triggered.connect(self.save_perspective)
        perspective_list_action = QWidgetAction(self)
        self.perspective_combobox = QComboBox(self)
        self.perspective_combobox.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.perspective_combobox.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Preferred
        )
        self.perspective_combobox.activated[str].connect(
            self.dock_manager.openPerspective
        )
        perspective_list_action.setDefaultWidget(self.perspective_combobox)
        self.toolBar.addSeparator()
        self.toolBar.addAction(perspective_list_action)
        self.toolBar.addAction(save_perspective_action)

    def save_perspective(self):
        perspective_name, ok = QInputDialog.getText(
            self, "Save Perspective", "Enter Unique name:"
        )
        if not ok or not perspective_name:
            return

        self.dock_manager.addPerspective(perspective_name)
        blocker = QSignalBlocker(self.perspective_combobox)
        self.perspective_combobox.clear()
        self.perspective_combobox.addItems(self.dock_manager.perspectiveNames())
        self.perspective_combobox.setCurrentText(perspective_name)

    def closeEvent(self, event):
        reply = QMessageBox(self)
        reply.setWindowTitle("Exit")
        reply.setText("Are you sure you want to exit?")
        reply.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        reply.setDefaultButton(QMessageBox.StandardButton.No)
        reply.setIcon(QMessageBox.Icon.Question)
        layout = reply.layout()
        dumpDataCheck = QCheckBox(reply)
        dumpDataCheck.setChecked(True)
        dumpDataCheck.setText("Dump all data on exit")
        layout.addWidget(dumpDataCheck)
        reply.setLayout(layout)
        button = reply.exec()
        self.settings.setValue("dock_manager_state", self.dock_manager.saveState())
        if button == QMessageBox.StandardButton.Yes:
            if dumpDataCheck.isChecked():
                MeasureManager.save_all()
            for window in QApplication.topLevelWidgets():
                window.close()
            self.dock_manager.deleteLater()
            event.accept()
        else:
            event.ignore()
