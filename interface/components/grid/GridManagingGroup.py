from PySide6.QtWidgets import QGroupBox, QGridLayout, QLabel

from api.Arduino.grid import GridDevice
from interface.components.ui.Button import Button
from interface.components.ui.DoubleSpinBox import DoubleSpinBox
from store import GridManager, GridConfig
from threads import Thread
from utils.exceptions import DeviceConnectionError


class GridThread(Thread):
    def __init__(self, cid: int, angle_rotate: float):
        super().__init__()
        self.cid = cid
        self.config: GridConfig = GridManager.get_config(cid)
        self.config.thread_rotate = True
        self.angle_rotate = angle_rotate

    def run(self):
        try:
            grid = GridDevice(**self.config.dict())
        except DeviceConnectionError as e:
            self.pre_exit()
            self.finished.emit()
            return
        angle = grid.rotate(self.angle_rotate, self.config.current_angle.value)
        if angle:
            self.config.current_angle.value = angle
        self.pre_exit()
        self.finished.emit()

    def pre_exit(self, *args, **kwargs):
        self.config.thread_rotate = False


class GridManagingGroup(QGroupBox):
    def __init__(self, parent, cid: int):
        super().__init__(parent)
        self.cid = cid
        self.setTitle("GRID")

        self.config: GridConfig = GridManager.get_config(cid)
        self.grid_thread = None

        layout = QGridLayout()

        self.angleCurrentLabel = QLabel(self)
        self.angleCurrentLabel.setText("Current angle")
        self.angleCurrent = QLabel(self)
        self.angleCurrent.setText(f"{self.config.current_angle.value} °")
        self.config.current_angle.value_signal.connect(
            lambda x: self.angleCurrent.setText(f"{round(x, 2)} °")
        )
        self.angleLabel = QLabel(self)
        self.angleLabel.setText("Angle, °")
        self.angle = DoubleSpinBox(self, lambda: self.rotate())
        self.angle.setRange(-720, 720)
        self.angle.setValue(self.config.current_angle.value)
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
        self.config.current_angle.value = 0
        self.angle.setValue(0)

    def rotate(self):
        if self.config.current_angle.value == self.angle.value():
            return
        self.grid_thread = GridThread(cid=self.cid, angle_rotate=self.angle.value())
        self.grid_thread.start()
        self.btnRotate.setEnabled(False)
        self.grid_thread.finished.connect(lambda: self.btnRotate.setEnabled(True))
