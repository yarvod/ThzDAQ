import logging
import time
from datetime import datetime

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QGroupBox,
    QLabel,
    QPushButton,
    QGridLayout,
    QComboBox,
    QFormLayout,
)

from api.Arduino.grid import GridManager
from api.Scontel.sis_block import SisBlock
from api.RohdeSchwarz.power_meter_nrx import NRXPowerMeter
from interface.components.DoubleSpinBox import DoubleSpinBox
from interface.windows.biasPowerGraphWindow import (
    GridBiasPowerGraphWindow,
    GridBiasGraphWindow,
)
from settings import GridPlotTypes
from store.base import MeasureModel, MeasureType
from store.state import state


logger = logging.getLogger(__name__)


class GridThread(QThread):
    def run(self):
        GridManager(host=state.GRID_ADDRESS).rotate(state.GRID_ANGLE)
        self.finished.emit()


class StepBiasPowerThread(QThread):
    results = pyqtSignal(list)
    stream_results = pyqtSignal(dict)

    def run(self):
        motor = GridManager(host=state.GRID_ADDRESS)
        nrx = NRXPowerMeter(
            ip=state.NRX_IP,
            filter_time=state.NRX_FILTER_TIME,
            aperture_time=state.NRX_APER_TIME,
        )
        block = SisBlock(
            host=state.BLOCK_ADDRESS,
            port=state.BLOCK_PORT,
            bias_dev=state.BLOCK_BIAS_DEV,
            ctrl_dev=state.BLOCK_CTRL_DEV,
        )
        block.connect()
        results_list = []
        angle_range = np.arange(
            state.GRID_ANGLE_START,
            state.GRID_ANGLE_STOP + state.GRID_ANGLE_STEP,
            state.GRID_ANGLE_STEP,
        )
        volt_range = np.linspace(
            state.BLOCK_BIAS_VOLT_FROM * 1e-3,
            state.BLOCK_BIAS_VOLT_TO * 1e-3,
            state.BLOCK_BIAS_VOLT_POINTS,
        )
        initial_v = block.get_bias_voltage()
        initial_time = time.time()
        motor.rotate(state.GRID_ANGLE_START)
        measure = MeasureModel.objects.create(
            measure_type=MeasureType.GRID_BIAS_POWER, data={}
        )
        time.sleep(abs(state.GRID_ANGLE_START) / state.GRID_SPEED)
        for ind, angle in enumerate(angle_range):
            if not state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD:
                break

            results = {
                "id": ind,
                "step": state.GRID_ANGLE_STEP,
                "angle": angle,
                "current_get": [],
                "voltage_set": [],
                "voltage_get": [],
                "power": [],
                "time": [],
            }
            if ind != 0:
                motor.rotate(state.GRID_ANGLE_STEP)
            time.sleep(abs(state.GRID_ANGLE_STEP) / state.GRID_SPEED)

            for i, voltage_set in enumerate(volt_range):
                if not state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD:
                    break

                block.set_bias_voltage(voltage_set)
                if i == 0:  # block ned time to set first point
                    time.sleep(0.5)
                time.sleep(state.BLOCK_BIAS_STEP_DELAY)
                voltage_get = block.get_bias_voltage()
                if not voltage_get:
                    continue
                current_get = block.get_bias_current()
                if not current_get:
                    continue
                power = nrx.get_power()
                time_step = time.time() - initial_time

                self.stream_results.emit(
                    {
                        "x": [voltage_get * 1e3],
                        "y": [power]
                        if state.GRID_PLOT_TYPE == GridPlotTypes.PV_CURVE
                        else [current_get],
                        "new_plot": i == 0,
                    }
                )

                results["voltage_set"].append(voltage_set)
                results["voltage_get"].append(voltage_get)
                results["current_get"].append(current_get)
                results["power"].append(power)
                results["time"].append(time_step)

                if i == 0:
                    results_list.append(results)
                else:
                    results_list[ind] = results

                measure.data = results_list

        block.set_bias_voltage(initial_v)
        measure.finished = datetime.now()
        measure.save()
        self.results.emit(results_list)
        self.finished.emit()

    def terminate(self) -> None:
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False

    def quit(self) -> None:
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False

    def exit(self, returnCode: int = ...):
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")
        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = False


class GridTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.gridBiasPowerGraphWindow = None
        self.gridBiasGraphWindow = None
        self.createGroupGrid()
        self.createGroupGridBiasPowerScan()
        self.layout.addWidget(self.groupGrid)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.groupGridBiasPowerScan)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupGrid(self):
        self.groupGrid = QGroupBox("GRID")
        layout = QGridLayout()

        self.angleLabel = QLabel(self)
        self.angleLabel.setText("Angle, degree")
        self.angle = DoubleSpinBox(self)
        self.angle.setRange(-720, 720)
        self.angle.setValue(90)
        self.btnRotate = QPushButton("Rotate")
        self.btnRotate.clicked.connect(self.rotate)

        layout.addWidget(self.angleLabel, 1, 0)
        layout.addWidget(self.angle, 1, 1)
        layout.addWidget(self.btnRotate, 1, 2)

        self.groupGrid.setLayout(layout)

    def createGroupGridBiasPowerScan(self):
        self.groupGridBiasPowerScan = QGroupBox("Grid Power Bias Scan")
        self.groupGridBiasPowerScan.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout = QFormLayout()

        self.angleStartLabel = QLabel(self)
        self.angleStartLabel.setText("Angle start, degree")
        self.angleStart = DoubleSpinBox(self)
        self.angleStart.setRange(-180, 180)
        self.angleStart.setValue(state.GRID_ANGLE_START)

        self.angleStopLabel = QLabel(self)
        self.angleStopLabel.setText("Angle stop, degree")
        self.angleStop = DoubleSpinBox(self)
        self.angleStop.setRange(-180, 180)
        self.angleStop.setValue(state.GRID_ANGLE_STOP)

        self.angleStepLabel = QLabel(self)
        self.angleStepLabel.setText("Angle step, degree")
        self.angleStep = DoubleSpinBox(self)
        self.angleStep.setRange(-180, 180)
        self.angleStep.setValue(state.GRID_ANGLE_STEP)

        self.voltFromLabel = QLabel(self)
        self.voltFromLabel.setText("Bias voltage from, mV")
        self.voltFrom = DoubleSpinBox(self)
        self.voltFrom.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltToLabel = QLabel(self)
        self.voltToLabel.setText("Bias voltage to, mV")
        self.voltTo = DoubleSpinBox(self)
        self.voltTo.setRange(
            state.BLOCK_BIAS_VOLT_MIN_VALUE, state.BLOCK_BIAS_VOLT_MAX_VALUE
        )

        self.voltPointsLabel = QLabel(self)
        self.voltPointsLabel.setText("Bias voltage points")
        self.voltPoints = DoubleSpinBox(self)
        self.voltPoints.setMaximum(state.BLOCK_BIAS_VOLT_POINTS_MAX)
        self.voltPoints.setDecimals(0)
        self.voltPoints.setValue(state.BLOCK_BIAS_VOLT_POINTS)

        self.voltStepDelayLabel = QLabel(self)
        self.voltStepDelayLabel.setText("Step delay, s")
        self.voltStepDelay = DoubleSpinBox(self)
        self.voltStepDelay.setRange(0.01, 10)
        self.voltStepDelay.setValue(state.BLOCK_BIAS_STEP_DELAY)

        self.gridPlotTypeLabel = QLabel(self)
        self.gridPlotTypeLabel.setText("Plot type")
        self.gridPlotType = QComboBox(self)
        self.gridPlotType.addItems(GridPlotTypes.CHOICES)

        self.btnStartBiasPowerScan = QPushButton("Start Scan")
        self.btnStartBiasPowerScan.clicked.connect(self.start_measure_step_bias_power)

        self.btnStopBiasPowerScan = QPushButton("Stop Scan")
        self.btnStopBiasPowerScan.clicked.connect(self.stop_measure_step_bias_power)
        self.btnStopBiasPowerScan.setEnabled(False)

        layout.addRow(self.angleStartLabel, self.angleStart)
        layout.addRow(self.angleStopLabel, self.angleStop)
        layout.addRow(self.angleStepLabel, self.angleStep)
        layout.addRow(self.voltFromLabel, self.voltFrom)
        layout.addRow(self.voltToLabel, self.voltTo)
        layout.addRow(self.voltPointsLabel, self.voltPoints)
        layout.addRow(self.voltStepDelayLabel, self.voltStepDelay)
        layout.addRow(self.gridPlotTypeLabel, self.gridPlotType)
        layout.addRow(self.btnStartBiasPowerScan)
        layout.addRow(self.btnStopBiasPowerScan)

        self.groupGridBiasPowerScan.setLayout(layout)

    def start_measure_step_bias_power(self):
        self.bias_power_thread = StepBiasPowerThread()

        state.GRID_BLOCK_BIAS_POWER_MEASURE_THREAD = True
        state.GRID_ANGLE_START = self.angleStart.value()
        state.GRID_ANGLE_STOP = self.angleStop.value()
        state.GRID_ANGLE_STEP = self.angleStep.value()
        state.BLOCK_BIAS_VOLT_FROM = self.voltFrom.value()
        state.BLOCK_BIAS_VOLT_TO = self.voltTo.value()
        state.BLOCK_BIAS_VOLT_POINTS = int(self.voltPoints.value())
        state.BLOCK_BIAS_STEP_DELAY = self.voltStepDelay.value()
        state.GRID_PLOT_TYPE = self.gridPlotType.currentIndex()

        self.bias_power_thread.stream_results.connect(self.show_bias_power_graph)
        self.bias_power_thread.start()

        self.btnStartBiasPowerScan.setEnabled(False)
        self.bias_power_thread.finished.connect(
            lambda: self.btnStartBiasPowerScan.setEnabled(True)
        )

        self.btnStopBiasPowerScan.setEnabled(True)
        self.bias_power_thread.finished.connect(
            lambda: self.btnStopBiasPowerScan.setEnabled(False)
        )

    def stop_measure_step_bias_power(self):
        self.bias_power_thread.quit()

    def show_bias_power_graph(self, results):
        if state.GRID_PLOT_TYPE == GridPlotTypes.IV_CURVE:
            if self.gridBiasGraphWindow is None:
                self.gridBiasGraphWindow = GridBiasGraphWindow()
            self.gridBiasGraphWindow.plotNew(
                x=results.get("x", []),
                y=results.get("y", []),
                new_plot=results.get("new_plot", True),
            )
            self.gridBiasGraphWindow.show()

        if state.GRID_PLOT_TYPE == GridPlotTypes.PV_CURVE:
            if self.gridBiasPowerGraphWindow is None:
                self.gridBiasPowerGraphWindow = GridBiasPowerGraphWindow()
            self.gridBiasPowerGraphWindow.plotNew(
                x=results.get("x", []),
                y=results.get("y", []),
                new_plot=results.get("new_plot", True),
            )
            self.gridBiasPowerGraphWindow.show()

    def rotate(self):
        state.GRID_ANGLE = self.angle.value()
        self.grid_thread = GridThread()
        self.grid_thread.start()
        self.btnRotate.setEnabled(False)
        self.grid_thread.finished.connect(lambda: self.btnRotate.setEnabled(True))
