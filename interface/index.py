from typing import Literal
from PyQt5.QtCore import QSignalBlocker, QSettings
from PyQt5.QtWidgets import (
    QMainWindow,
    QMessageBox,
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
import PyQtAds as QtAds

from store import (
    KeithleyPowerSupplyManager,
    AgilentSignalGeneratorManager,
    PrologixManager,
    RigolPowerSupplyManager,
    SumitomoF70Manager,
    LakeShoreTemperatureControllerManager,
)
from interface import style
from interface.components.ExitMessageBox import ExitMessageBox
from interface.views.GridTabWidget import GridTabWidget
from interface.views.blockTabWidget import BlockTabWidget
from interface.views.measureDataTabWidget import MeasureDataTabWidget
from interface.views.powerMeterTabWidget import PowerMeterTabWidget
from interface.views.setUpTabWidget import SetUpTabWidget
from interface.views.vnaTabWidget import VNATabWidget
from store.base import MeasureManager
from utils.functions import import_class


class App(QMainWindow):
    def __init__(
        self,
        title: str = "SIS manager",
        company: str = "ASC",
    ):
        super().__init__()
        self.title = title
        self.company = company
        self.left = 0
        self.top = 0
        self.width = 1300
        self.height = 700
        self.icon = QtGui.QIcon("./assets/logo_small.png")
        self.setWindowIcon(self.icon)
        self.setStyleSheet(style.GLOBAL_STYLE)
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

        self.settings = QSettings(self.company, self.title)
        self.dock_manager = None

        self.menuBar = self.menuBar()
        self.menuBase = QMenu("Base", self)
        self.menuDevice = QMenu("Devices", self)
        self.menuGraph = QMenu("Graphs", self)
        self.menuMeasure = QMenu("Measures", self)

        self.menuBar.addMenu(self.menuBase)
        self.menuBar.addMenu(self.menuDevice)
        self.menuBar.addMenu(self.menuGraph)
        self.menuBar.addMenu(self.menuMeasure)

        # Add toolbar
        self.toolBar = QToolBar("Main ToolBar")
        self.addToolBar(self.toolBar)

        self.show()

    def add_views(self):
        # Add base widgets
        self.setup_dock_widget = QtAds.CDockWidget("SetUp")
        self.tab_setup = SetUpTabWidget(self)
        self.setup_dock_widget.setWidget(self.tab_setup)
        self.menuBase.addAction(self.setup_dock_widget.toggleViewAction())
        self.dock_manager.addAutoHideDockWidget(
            QtAds.SideBarLeft, self.setup_dock_widget
        )

        self.data_dock_widget = QtAds.CDockWidget("Data")
        self.tab_data = MeasureDataTabWidget(self)
        self.data_dock_widget.setWidget(self.tab_data)
        self.menuBase.addAction(self.data_dock_widget.toggleViewAction())
        self.dock_manager.addAutoHideDockWidget(
            QtAds.SideBarLeft, self.data_dock_widget
        )

        # Add devices widgets
        self.sis_block_dock_widget = QtAds.CDockWidget("SIS Block")
        self.tab_sis_block = BlockTabWidget(self)
        self.sis_block_dock_widget.setWidget(self.tab_sis_block)
        self.menuBase.addAction(self.sis_block_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidget(
            QtAds.RightDockWidgetArea, self.sis_block_dock_widget
        )

        self.vna_dock_widget = QtAds.CDockWidget("VNA")
        self.tab_vna = VNATabWidget(self)
        self.vna_dock_widget.setWidget(self.tab_vna)
        self.menuBase.addAction(self.vna_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.vna_dock_widget
        )

        self.nrx_dock_widget = QtAds.CDockWidget("Power Meter")
        self.tab_nrx = PowerMeterTabWidget(self)
        self.nrx_dock_widget.setWidget(self.tab_nrx)
        self.menuBase.addAction(self.nrx_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.nrx_dock_widget
        )

        self.grid_dock_widget = QtAds.CDockWidget("GRID")
        self.tab_grid = GridTabWidget(self)
        self.grid_dock_widget.setWidget(self.tab_grid)
        self.menuBase.addAction(self.grid_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.grid_dock_widget
        )

        self.add_dock_widget(
            "Rohde Schwarz Spectrum",
            import_class("interface.views.SpectrumTabWidget"),
            "device",
        )
        self.add_dock_widget(
            "Chopper", import_class("interface.views.ChopperTabWidget"), "device"
        )
        self.add_dock_widget(
            "YIG filter", import_class("interface.views.YIGWidget"), "device"
        )

        # Add measures widgets
        self.add_dock_widget(
            "Sis power Rn measure",
            import_class("interface.views.SisRnPowerMeasureTabWidget"),
            "measure",
        )

        # Add graph widgets
        self.add_dock_widget(
            "I-V curve", import_class("interface.windows.BiasGraphWindow"), "graph"
        )
        self.add_dock_widget(
            "I-CL curve", import_class("interface.windows.CLGraphWindow"), "graph"
        )
        self.add_dock_widget(
            "P-t curve", import_class("interface.windows.NRXStreamGraphWindow"), "graph"
        )
        self.add_dock_widget(
            "P-V curve", import_class("interface.windows.BiasPowerGraphWindow"), "graph"
        )
        self.add_dock_widget(
            "Y-V curve",
            import_class("interface.windows.BiasPowerDiffGraphWindow"),
            "graph",
        )
        self.add_dock_widget(
            "Tn-V curve", import_class("interface.windows.TnGraphWindow"), "graph"
        )
        self.add_dock_widget(
            "GRID I-A curve",
            import_class("interface.windows.GridAngleCurrentGraphWindow"),
            "graph",
        )
        self.add_dock_widget(
            "Spectrum P-F curve",
            import_class("interface.windows.SpectrumGraphWindow"),
            "graph",
        )
        self.add_dock_widget(
            "VNA P-F curve", import_class("interface.windows.VNAGraphWindow"), "graph"
        )
        self.add_dock_widget(
            "T-t curve",
            import_class("interface.windows.TemperatureGraphWindow"),
            "graph",
        )
        self.add_dock_widget(
            "P-IF curve", import_class("interface.windows.PowerIFGraphWindow"), "graph"
        )
        self.add_dock_widget(
            "Y-IF curve", import_class("interface.windows.YIFGraphWindow"), "graph"
        )
        self.add_dock_widget(
            "Tn-IF curve", import_class("interface.windows.TnIFGraphWindow"), "graph"
        )

    def add_dock_widget(
        self,
        name: str,
        widget_class,
        menu: Literal["base", "device", "graph", "measure"] = "base",
        **kwargs,
    ):
        dock_widget = QtAds.CDockWidget(name)
        widget = widget_class(self, **kwargs)
        dock_widget.setWidget(widget)
        if menu == "base":
            self.menuBase.addAction(dock_widget.toggleViewAction())
        elif menu == "graph":
            self.menuGraph.addAction(dock_widget.toggleViewAction())
        elif menu == "measure":
            self.menuMeasure.addAction(dock_widget.toggleViewAction())
        elif menu == "device":
            self.menuDevice.addAction(dock_widget.toggleViewAction())
        self.dock_manager.addDockWidget(QtAds.RightDockWidgetArea, dock_widget)
        dock_widget.closeDockWidget()

    def delete_dock_widget(self, name: str):
        dock_widget = self.dock_manager.findDockWidget(name)
        self.menuBase.removeAction(dock_widget.toggleViewAction())
        self.dock_manager.removeDockWidget(dock_widget)

    def restore_state(self):
        # dock_manager_state = self.settings.value("dock_manager_state")
        # if dock_manager_state:
        #     self.dock_manager.restoreState(dock_manager_state)
        self.dock_manager.loadPerspectives(self.settings)
        if not len(self.dock_manager.perspectiveNames()):
            settings = QSettings("settings.ini", QSettings.IniFormat)
            self.dock_manager.loadPerspectives(settings)
        self.perspective_combobox.addItems(self.dock_manager.perspectiveNames())
        try:
            self.dock_manager.perspectiveNames().index("SIS measuring")
            self.perspective_combobox.setCurrentText("SIS measuring")
        except ValueError:
            pass

    def restore_from_ini_file(self):
        settings = QSettings("settings.ini", QSettings.IniFormat)
        self.dock_manager.loadPerspectives(settings)
        self.store_state()
        try:
            self.dock_manager.perspectiveNames().index("SIS measuring")
            self.perspective_combobox.setCurrentText("SIS measuring")
        except ValueError:
            pass

    def store_state(self):
        # self.settings.setValue("dock_manager_state", self.dock_manager.saveState())
        self.dock_manager.savePerspectives(self.settings)
        KeithleyPowerSupplyManager.store_config()
        PrologixManager.store_config()
        AgilentSignalGeneratorManager.store_config()
        RigolPowerSupplyManager.store_config()
        SumitomoF70Manager.store_config()
        LakeShoreTemperatureControllerManager.store_config()
        self.settings.sync()

    def create_perspective_ui(self):
        create_perspective_action = QAction("Create Perspective", self)
        create_perspective_action.triggered.connect(self.create_perspective)
        update_perspective_action = QAction("Update Perspective", self)
        update_perspective_action.triggered.connect(self.update_perspective)
        restore_default_perspectives_action = QAction("!Restore Defaults!", self)
        restore_default_perspectives_action.setToolTip(
            "DANGER! Restoring default perspectives!\nOnly for those in the know!"
        )
        restore_default_perspectives_action.triggered.connect(
            self.restore_from_ini_file
        )
        perspective_list_action = QWidgetAction(self)
        self.perspective_combobox = QComboBox(self)
        self.perspective_combobox.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.perspective_combobox.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Preferred
        )
        self.perspective_combobox.currentTextChanged.connect(
            self.dock_manager.openPerspective
        )
        perspective_list_action.setDefaultWidget(self.perspective_combobox)
        self.toolBar.addSeparator()
        self.toolBar.addAction(perspective_list_action)
        self.toolBar.addAction(create_perspective_action)
        self.toolBar.addAction(update_perspective_action)
        self.toolBar.addAction(restore_default_perspectives_action)

    def create_perspective(self):
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

    def update_perspective(self):
        perspective_name = self.perspective_combobox.currentText()
        self.dock_manager.addPerspective(perspective_name)

    def closeEvent(self, event):
        reply = ExitMessageBox(self)
        button = reply.exec()
        if button == QMessageBox.StandardButton.Yes:
            if reply.dumpDataCheck.isChecked():
                MeasureManager.save_all()
            if reply.storeStateCheck.isChecked():
                self.store_state()
            for window in QApplication.topLevelWidgets():
                window.close()
            self.dock_manager.deleteLater()
            event.accept()
        else:
            event.ignore()
