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
from PyQtAds import ads as QtAds


from interface import style
from interface.components.ExitMessageBox import ExitMessageBox
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
from interface.windows.biasGraphWindow import BiasGraphWindow
from interface.windows.biasPowerGraphWindow import (
    BiasPowerGraphWindow,
    BiasPowerDiffGraphWindow,
    GridBiasPowerGraphWindow,
    GridBiasCurrentGraphWindow,
    GridBiasPowerDiffGraphWindow,
)
from interface.windows.clGraphWindow import CLGraphWindow
from interface.windows.nrxStreamGraph import NRXStreamGraphWindow
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
        self.menuView = QMenu("Views", self)
        self.menuGraph = QMenu("Graphs", self)
        self.menuBar.addMenu(self.menuView)
        self.menuBar.addMenu(self.menuGraph)

        self.dock_manager = QtAds.CDockManager(self)

        # Add base widgets
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

        self.graph_yv_curve_dock_widget = QtAds.CDockWidget("Y-V curve")
        self.tab_graph_yv_curve = BiasPowerDiffGraphWindow(self)
        self.graph_yv_curve_dock_widget.setWidget(self.tab_graph_yv_curve)
        self.menuGraph.addAction(self.graph_yv_curve_dock_widget.toggleViewAction())
        self.dock_manager.addDockWidgetTab(
            QtAds.RightDockWidgetArea, self.graph_yv_curve_dock_widget
        )
        self.tab_nrx.biasPowerDiffGraphWindow = self.graph_yv_curve_dock_widget

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

        # Set widgets active
        self.setup_dock_widget.raise_()
        self.sis_block_dock_widget.raise_()

        # Add toolbar
        self.toolBar = QToolBar("Main ToolBar")
        self.addToolBar(self.toolBar)

        self.create_perspective_ui()
        self.restore_state()

        self.show()

    def restore_state(self):
        # dock_manager_state = self.settings.value("dock_manager_state")
        # if dock_manager_state:
        #     self.dock_manager.restoreState(dock_manager_state)
        self.dock_manager.loadPerspectives(self.settings)
        self.perspective_combobox.addItems(self.dock_manager.perspectiveNames())
        try:
            last_perspective = self.dock_manager.perspectiveNames()[-1]
            self.perspective_combobox.setCurrentText(last_perspective)
        except IndexError:
            pass

    def store_state(self):
        # self.settings.setValue("dock_manager_state", self.dock_manager.saveState())
        self.dock_manager.savePerspectives(self.settings)

    def create_perspective_ui(self):
        create_perspective_action = QAction("Create Perspective", self)
        create_perspective_action.triggered.connect(self.create_perspective)
        update_perspective_action = QAction("Update Perspective", self)
        update_perspective_action.triggered.connect(self.update_perspective)
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
