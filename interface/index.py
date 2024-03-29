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
)
from interface import style
from interface.components.ExitMessageBox import ExitMessageBox
from interface.views.GridTabWidget import GridTabWidget
from interface.views.YIG.YigWidget import YIGWidget
from interface.views.blockTabWidget import BlockTabWidget
from interface.views.chopperTabWidget import ChopperTabWidget
from interface.views.measureDataTabWidget import MeasureDataTabWidget
from interface.views.powerMeterTabWidget import PowerMeterTabWidget
from interface.views.setUpTabWidget import SetUpTabWidget
from interface.views.spectrumTabWidget import SpectrumTabWidget
from interface.views.temperatureControllerTabWidget import (
    TemperatureControllerTabWidget,
)
from interface.views.vnaTabWidget import VNATabWidget
from interface.windows.biasGraphWindow import BiasGraphWindow
from interface.windows.biasPowerGraphWindow import (
    BiasPowerGraphWindow,
    BiasPowerDiffGraphWindow,
    TnGraphWindow,
    BiasCurrentGraphWindow,
)
from interface.windows.gridGraphs import (
    GridBiasPowerGraphWindow,
    GridBiasCurrentGraphWindow,
    GridBiasPowerDiffGraphWindow,
    GridTnGraphWindow,
    GridAngleCurrentGraphWindow,
)
from interface.windows.clGraphWindow import CLGraphWindow
from interface.windows.nrxStreamGraph import NRXStreamGraphWindow
from interface.windows.spectrumGraphWindow import SpectrumGraphWindow
from interface.windows.temperatureGraphWindow import TemperatureGraphWindow
from interface.windows.vnaGraphWindow import VNAGraphWindow
from interface.windows.yigGraphWindow import (
    PowerIFGraphWindow,
    YIFGraphWindow,
    TnIFGraphWindow,
)
from store.base import MeasureManager


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
        self.menuView = QMenu("Views", self)
        self.menuGraph = QMenu("Graphs", self)
        self.menuBar.addMenu(self.menuView)
        self.menuBar.addMenu(self.menuGraph)

        # Add toolbar
        self.toolBar = QToolBar("Main ToolBar")
        self.addToolBar(self.toolBar)

        self.show()

    def add_views(self):
        # Add base widgets
        self.setup_dock_widget = QtAds.CDockWidget("SetUp")
        self.tab_setup = SetUpTabWidget(self)
        self.setup_dock_widget.setWidget(self.tab_setup)
        self.menuView.addAction(self.setup_dock_widget.toggleViewAction())
        self.dock_manager.addAutoHideDockWidget(
            QtAds.SideBarLeft, self.setup_dock_widget
        )

        self.data_dock_widget = QtAds.CDockWidget("Data")
        self.tab_data = MeasureDataTabWidget(self)
        self.data_dock_widget.setWidget(self.tab_data)
        self.menuView.addAction(self.data_dock_widget.toggleViewAction())
        self.dock_manager.addAutoHideDockWidget(
            QtAds.SideBarLeft, self.data_dock_widget
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
        self.tab_nrx = PowerMeterTabWidget(self)
        self.nrx_dock_widget.setWidget(self.tab_nrx)
        self.menuView.addAction(self.nrx_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.nrx_dock_widget
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

        self.yig_dock_widget = QtAds.CDockWidget("YIG filter")
        self.yig_widget = YIGWidget(self)
        self.yig_dock_widget.setWidget(self.yig_widget)
        self.menuView.addAction(self.yig_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.yig_dock_widget
        )

        # Add graph widgets
        self.graph_iv_curve_dock_widget = QtAds.CDockWidget("I-V curve")
        self.tab_graph_iv_curve = BiasGraphWindow(self)
        self.graph_iv_curve_dock_widget.setWidget(self.tab_graph_iv_curve)
        self.menuGraph.addAction(self.graph_iv_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_iv_curve_dock_widget
        )
        self.tab_sis_block.biasGraphDockWidget = self.graph_iv_curve_dock_widget

        self.graph_cli_curve_dock_widget = QtAds.CDockWidget("CL-I curve")
        self.tab_graph_cli_curve = CLGraphWindow(self)
        self.graph_cli_curve_dock_widget.setWidget(self.tab_graph_cli_curve)
        self.menuGraph.addAction(self.graph_cli_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_cli_curve_dock_widget
        )
        self.tab_sis_block.ctrlGraphDockWidget = self.graph_cli_curve_dock_widget

        self.graph_power_stream_curve_dock_widget = QtAds.CDockWidget("P-t curve")
        self.tab_graph_power_stream_curve = NRXStreamGraphWindow(self)
        self.graph_power_stream_curve_dock_widget.setWidget(
            self.tab_graph_power_stream_curve
        )
        self.menuGraph.addAction(
            self.graph_power_stream_curve_dock_widget.toggleViewAction()
        )
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_power_stream_curve_dock_widget
        )
        self.tab_nrx.powerStreamGraphDockWidget = (
            self.graph_power_stream_curve_dock_widget
        )

        self.graph_pv_curve_dock_widget = QtAds.CDockWidget("P-V curve")
        self.tab_graph_pv_curve = BiasPowerGraphWindow(self)
        self.graph_pv_curve_dock_widget.setWidget(self.tab_graph_pv_curve)
        self.menuGraph.addAction(self.graph_pv_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_pv_curve_dock_widget
        )
        self.tab_nrx.biasPowerGraphWindow = self.graph_pv_curve_dock_widget

        self.graph_p_iv_curve_dock_widget = QtAds.CDockWidget("Power I-V curve")
        self.tab_graph_p_iv_curve = BiasCurrentGraphWindow(self)
        self.graph_p_iv_curve_dock_widget.setWidget(self.tab_graph_p_iv_curve)
        self.menuGraph.addAction(self.graph_p_iv_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_p_iv_curve_dock_widget
        )
        self.tab_nrx.biasCurrentGraphWindow = self.graph_p_iv_curve_dock_widget

        self.graph_yv_curve_dock_widget = QtAds.CDockWidget("Y-V curve")
        self.tab_graph_yv_curve = BiasPowerDiffGraphWindow(self)
        self.graph_yv_curve_dock_widget.setWidget(self.tab_graph_yv_curve)
        self.menuGraph.addAction(self.graph_yv_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_yv_curve_dock_widget
        )
        self.tab_nrx.biasPowerDiffGraphWindow = self.graph_yv_curve_dock_widget

        self.graph_tnv_curve_dock_widget = QtAds.CDockWidget("Tn-V curve")
        self.tab_graph_tnv_curve = TnGraphWindow(self)
        self.graph_tnv_curve_dock_widget.setWidget(self.tab_graph_tnv_curve)
        self.menuGraph.addAction(self.graph_tnv_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_tnv_curve_dock_widget
        )
        self.tab_nrx.biasTnGraphWindow = self.graph_tnv_curve_dock_widget

        self.graph_grid_pv_curve_dock_widget = QtAds.CDockWidget("GRID P-V curve")
        self.tab_graph_grid_pv_curve = GridBiasPowerGraphWindow(self)
        self.graph_grid_pv_curve_dock_widget.setWidget(self.tab_graph_grid_pv_curve)
        self.menuGraph.addAction(
            self.graph_grid_pv_curve_dock_widget.toggleViewAction()
        )
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_grid_pv_curve_dock_widget
        )
        self.tab_grid.gridBiasPowerGraphWindow = self.graph_grid_pv_curve_dock_widget

        self.graph_grid_iv_curve_dock_widget = QtAds.CDockWidget("GRID I-V curve")
        self.tab_graph_grid_iv_curve = GridBiasCurrentGraphWindow(self)
        self.graph_grid_iv_curve_dock_widget.setWidget(self.tab_graph_grid_iv_curve)
        self.menuGraph.addAction(
            self.graph_grid_iv_curve_dock_widget.toggleViewAction()
        )
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_grid_iv_curve_dock_widget
        )
        self.tab_grid.gridBiasCurrentGraphWindow = self.graph_grid_iv_curve_dock_widget

        self.graph_grid_yv_curve_dock_widget = QtAds.CDockWidget("GRID Y-V curve")
        self.tab_graph_grid_yv_curve = GridBiasPowerDiffGraphWindow(self)
        self.graph_grid_yv_curve_dock_widget.setWidget(self.tab_graph_grid_yv_curve)
        self.menuGraph.addAction(
            self.graph_grid_yv_curve_dock_widget.toggleViewAction()
        )
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_grid_yv_curve_dock_widget
        )
        self.tab_grid.gridBiasPowerDiffGraphWindow = (
            self.graph_grid_yv_curve_dock_widget
        )

        self.graph_grid_tnv_curve_dock_widget = QtAds.CDockWidget("GRID Tn-V curve")
        self.tab_graph_grid_tnv_curve = GridTnGraphWindow(self)
        self.graph_grid_tnv_curve_dock_widget.setWidget(self.tab_graph_grid_tnv_curve)
        self.menuGraph.addAction(
            self.graph_grid_tnv_curve_dock_widget.toggleViewAction()
        )
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_grid_tnv_curve_dock_widget
        )
        self.tab_grid.biasTnGraphWindow = self.graph_grid_tnv_curve_dock_widget

        self.graph_grid_ia_curve_dock_widget = QtAds.CDockWidget("GRID I-A curve")
        self.tab_graph_grid_ia_curve = GridAngleCurrentGraphWindow(self)
        self.graph_grid_ia_curve_dock_widget.setWidget(self.tab_graph_grid_ia_curve)
        self.menuGraph.addAction(
            self.graph_grid_ia_curve_dock_widget.toggleViewAction()
        )
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_grid_ia_curve_dock_widget
        )
        self.tab_grid.gridAngleCurrentScan.gridBiasCurrentAngleGraphWindow = (
            self.graph_grid_ia_curve_dock_widget
        )

        self.graph_spectrum_dock_widget = QtAds.CDockWidget("Spectrum curve")
        self.tab_graph_spectrum_curve = SpectrumGraphWindow(self)
        self.graph_spectrum_dock_widget.setWidget(self.tab_graph_spectrum_curve)
        self.menuGraph.addAction(self.graph_spectrum_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_spectrum_dock_widget
        )
        self.tab_spectrum.spectrum_monitor.spectrumStreamGraphWindow = (
            self.graph_spectrum_dock_widget
        )

        self.graph_vna_dock_widget = QtAds.CDockWidget("VNA curve")
        self.tab_graph_vna_curve = VNAGraphWindow(self)
        self.graph_vna_dock_widget.setWidget(self.tab_graph_vna_curve)
        self.menuGraph.addAction(self.graph_vna_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_vna_dock_widget
        )
        self.tab_vna.vnaGraphWindow = self.graph_vna_dock_widget

        self.graph_temperature_dock_widget = QtAds.CDockWidget("Temperature curve")
        self.tab_graph_temperature_curve = TemperatureGraphWindow(self)
        self.graph_temperature_dock_widget.setWidget(self.tab_graph_temperature_curve)
        self.menuGraph.addAction(self.graph_temperature_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_temperature_dock_widget
        )
        self.tab_temperature.temperatureStreamGraphWindow = (
            self.graph_temperature_dock_widget
        )

        self.pif_curve_dock_widget = QtAds.CDockWidget("P-IF curve")
        self.pif_curve_widget = PowerIFGraphWindow(self)
        self.pif_curve_dock_widget.setWidget(self.pif_curve_widget)
        self.menuGraph.addAction(self.pif_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.pif_curve_dock_widget
        )
        self.yig_widget.powerIfGraphWindow = self.pif_curve_dock_widget

        self.yif_curve_dock_widget = QtAds.CDockWidget("Y-IF curve")
        self.yif_curve_widget = YIFGraphWindow(self)
        self.yif_curve_dock_widget.setWidget(self.yif_curve_widget)
        self.menuGraph.addAction(self.yif_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.yif_curve_dock_widget
        )
        self.yig_widget.yIfGraphWindow = self.yif_curve_dock_widget

        self.tnif_curve_dock_widget = QtAds.CDockWidget("Tn-IF curve")
        self.tnif_curve_widget = TnIFGraphWindow(self)
        self.tnif_curve_dock_widget.setWidget(self.tnif_curve_widget)
        self.menuGraph.addAction(self.tnif_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.tnif_curve_dock_widget
        )
        self.yig_widget.tnIfGraphWindow = self.tnif_curve_dock_widget

    def add_dock_widget(
        self,
        name: str,
        widget_class,
        **kwargs,
    ):
        dock_widget = QtAds.CDockWidget(name)
        widget = widget_class(self, **kwargs)
        dock_widget.setWidget(widget)
        self.menuView.addAction(dock_widget.toggleViewAction())
        self.dock_manager.addDockWidget(QtAds.RightDockWidgetArea, dock_widget)
        dock_widget.closeDockWidget()

    def delete_dock_widget(self, name: str):
        dock_widget = self.dock_manager.findDockWidget(name)
        self.menuView.removeAction(dock_widget.toggleViewAction())
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
        self.settings.sync()

    def create_perspective_ui(self):
        create_perspective_action = QAction("Create Perspective", self)
        create_perspective_action.triggered.connect(self.create_perspective)
        update_perspective_action = QAction("Update Perspective", self)
        update_perspective_action.triggered.connect(self.update_perspective)
        restore_default_perspectives_action = QAction("!Restore Defaults!", self)
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
