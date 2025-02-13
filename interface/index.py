from typing import Literal
from PySide6.QtCore import QSignalBlocker, QSettings
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QApplication,
    QMenu,
    QWidgetAction,
    QWidgetAction,
    QComboBox,
    QSizePolicy,
    QInputDialog,
    QToolBar,
)
from PySide6 import QtGui
import PySide6QtAds as QtAds

from interface import style
from interface.components.ExitMessageBox import ExitMessageBox
from interface.views.measureDataTabWidget import MeasureDataTabWidget
from interface.views.setUpTabWidget import SetUpTabWidget
import interface.windows  # noqa
from store import store_configs
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
        self.perspective = None
        self.left = 0
        self.top = 0
        self.width = 1300
        self.height = 700
        self.icon = QtGui.QIcon("./assets/logo_small.png")
        self.setWindowIcon(self.icon)
        self.setStyleSheet(style.GLOBAL_STYLE)
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

        self.settings = QSettings("settings.ini", QSettings.IniFormat)
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
            QtAds.SideBarLocation.SideBarLeft, self.setup_dock_widget
        )

        self.data_dock_widget = QtAds.CDockWidget("Data")
        self.tab_data = MeasureDataTabWidget(self)
        self.data_dock_widget.setWidget(self.tab_data)
        self.menuBase.addAction(self.data_dock_widget.toggleViewAction())
        self.dock_manager.addAutoHideDockWidget(
            QtAds.SideBarLocation.SideBarLeft, self.data_dock_widget
        )

        # Add devices widgets
        self.add_dock_widget(
            "Scontel SIS block",
            import_class("interface.views.BlockTabWidget"),
            "device",
        )
        self.add_dock_widget(
            "RohdeSchwarz Power Meter",
            import_class("interface.views.PowerMeterTabWidget"),
            "device",
        )
        self.add_dock_widget(
            "GRID", import_class("interface.views.GridTabWidget"), "device"
        )

        self.add_dock_widget(
            "Chopper", import_class("interface.views.ChopperTabWidget"), "device"
        )
        self.add_dock_widget(
            "YIG filter", import_class("interface.views.YIGWidget"), "device"
        )

        # Add measures widgets
        self.add_dock_widget(
            "Shot noise IF measure",
            import_class("interface.views.SisRnPowerMeasureTabWidget"),
            "measure",
        )
        self.add_dock_widget(
            "Sis reflection measure",
            import_class("interface.views.SisReflectionMeasureWidget"),
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
        self.dock_manager.addDockWidget(
            QtAds.DockWidgetArea.NoDockWidgetArea, dock_widget
        )
        dock_widget.closeDockWidget()

    def delete_dock_widget(self, name: str):
        dock_widget = self.dock_manager.findDockWidget(name)
        self.menuBase.removeAction(dock_widget.toggleViewAction())
        self.dock_manager.removeDockWidget(dock_widget)

    def init_settings(self):
        settings_ini = QSettings("settings_default.ini", QSettings.IniFormat)
        if "Perspectives" not in self.settings.childGroups():
            for key in settings_ini.allKeys():
                if "Perspectives" not in key:
                    continue
                self.settings.setValue(key, settings_ini.value(key))
            self.settings.sync()
        if "Configs" not in self.settings.childGroups():
            for key in settings_ini.allKeys():
                if "Configs" not in key:
                    continue
                self.settings.setValue(key, settings_ini.value(key))
            self.settings.sync()

    def restore_state(self):
        self.dock_manager.loadPerspectives(self.settings)
        if not len(self.dock_manager.perspectiveNames()):
            settings = QSettings("settings_default.ini", QSettings.IniFormat)
            self.dock_manager.loadPerspectives(settings)
        self.perspective_combobox.addItems(self.dock_manager.perspectiveNames())
        try:
            self.dock_manager.perspectiveNames().index("SIS measuring")
            self.perspective_combobox.setCurrentText("SIS measuring")
        except ValueError:
            pass

    def delete_perspective(self):
        perspective = self.perspective_combobox.currentText()
        perspective_index = self.perspective_combobox.currentIndex()
        reply = QMessageBox(self)
        reply.setWindowTitle(f"Deleting perspective {perspective}")
        reply.setText(f"Are you sure want to delete perspective {perspective} !?")
        reply.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        reply.setDefaultButton(QMessageBox.StandardButton.No)
        reply.setIcon(QMessageBox.Icon.Warning)
        button = reply.exec()
        if button == QMessageBox.StandardButton.Yes:
            self.dock_manager.removePerspective(perspective)
            self.perspective = None
            self.perspective_combobox.removeItem(perspective_index)
        else:
            pass

    def restore_from_ini_file(self):
        reply = QMessageBox(self)
        reply.setWindowTitle("Restoring default perspectives")
        reply.setText("Are you sure want to restore default perspectives?")
        reply.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        reply.setDefaultButton(QMessageBox.StandardButton.No)
        reply.setIcon(QMessageBox.Icon.Question)
        button = reply.exec()
        if button == QMessageBox.StandardButton.Yes:
            settings = QSettings("settings_default.ini", QSettings.IniFormat)
            self.dock_manager.loadPerspectives(settings)
            self.store_state()
            try:
                self.dock_manager.perspectiveNames().index("SIS measuring")
                self.perspective_combobox.setCurrentText("SIS measuring")
            except ValueError:
                pass
        else:
            pass

    def store_state(self):
        for name in self.settings.allKeys():
            if "Perspective" in name:
                self.settings.remove(name)
        self.settings.sync()
        self.dock_manager.savePerspectives(self.settings)
        store_configs(self.settings)
        self.settings.sync()

    def create_perspective_ui(self):
        create_perspective_action = QWidgetAction("Create Perspective", self)
        create_perspective_action.triggered.connect(self.create_perspective)

        update_perspective_action = QWidgetAction("Update Current Perspective", self)
        update_perspective_action.triggered.connect(self.update_perspective)

        delete_perspective_action = QWidgetAction("Delete Current Perspective", self)
        delete_perspective_action.setToolTip("DANGER! You will lost this perspective!")
        delete_perspective_action.triggered.connect(self.delete_perspective)

        restore_default_perspectives_action = QWidgetAction("!Restore Defaults!", self)
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
        self.perspective_combobox.currentTextChanged.connect(self.open_perspective)
        perspective_list_action.setDefaultWidget(self.perspective_combobox)
        self.toolBar.addSeparator()
        self.toolBar.addAction(perspective_list_action)
        self.toolBar.addAction(create_perspective_action)
        self.toolBar.addAction(update_perspective_action)
        self.toolBar.addAction(delete_perspective_action)
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

    def open_perspective(self, name: str):
        if self.perspective:
            self.dock_manager.addPerspective(self.perspective)
        self.dock_manager.openPerspective(name)
        self.perspective = name

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
