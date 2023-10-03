from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QGroupBox, QGridLayout, QLabel

from api.Arduino.grid import GridManager
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store.state import state


class GridThread(QThread):
    def run(self):
        grid = GridManager(host=state.GRID_ADDRESS)
        grid.rotate(state.GRID_ANGLE_ROTATE)
        self.finished.emit()


class GridManagingGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("GRID")

        layout = QGridLayout()

        self.angleCurrentLabel = QLabel(self)
        self.angleCurrentLabel.setText("Current angle")
        self.angleCurrent = QLabel(self)
        self.angleCurrent.setText(f"{state.GRID_ANGLE} °")
        self.angleLabel = QLabel(self)
        self.angleLabel.setText("Angle, °")
        self.angle = DoubleSpinBox(self, lambda: self.rotate())
        self.angle.setRange(-720, 720)
        self.angle.setValue(state.GRID_ANGLE)
        self.btnRotate = Button("Rotate", animate=True)
        self.btnRotate.clicked.connect(self.rotate)
        self.btnSetZero = Button("Set new zero", animate=True)
        self.btnSetZero.clicked.connect(self.setZero)

        layout.addWidget(self.angleCurrentLabel, 0, 0)
        layout.addWidget(self.angleCurrent, 0, 1)
        layout.addWidget(self.btnSetZero, 0, 2)
        layout.addWidget(self.angleLabel, 1, 0)
        layout.addWidget(self.angle, 1, 1)
        layout.addWidget(self.btnRotate, 1, 2)

        self.setLayout(layout)

    def setZero(self):
        state.GRID_ANGLE = 0
        state.GRID_ANGLE_ROTATE = 0
        self.angle.setValue(0)
        self.angleCurrent.setText("0 °")

    def rotate(self):
        if state.GRID_ANGLE == self.angle.value():
            return
        state.GRID_ANGLE_ROTATE = self.angle.value()
        self.grid_thread = GridThread()
        self.grid_thread.start()
        self.btnRotate.setEnabled(False)
        self.grid_thread.finished.connect(lambda: self.btnRotate.setEnabled(True))
        self.grid_thread.finished.connect(
            lambda: self.angleCurrent.setText(f"{state.GRID_ANGLE} °")
        )
