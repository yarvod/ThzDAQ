from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QGroupBox,
    QLabel,
    QPushButton,
    QGridLayout,
)

from api.arduino.arduino import StepMotorManager
from interface.components import CustomQDoubleSpinBox
from state import state


class StepMotorTabWidget(QWidget):
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.createGroupStepMotor()
        self.layout.addWidget(self.groupStepMotor)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def createGroupStepMotor(self):
        self.groupStepMotor = QGroupBox("Step Motor")
        layout = QGridLayout()

        self.angleLabel = QLabel(self)
        self.angleLabel.setText("Angle, degree")
        self.angle = CustomQDoubleSpinBox(self)
        self.angle.setRange(-720, 720)
        self.angle.setValue(90)
        self.btnRotate = QPushButton("Rotate")
        self.btnRotate.clicked.connect(self.rotate)

        layout.addWidget(self.angleLabel, 1, 0)
        layout.addWidget(self.angle, 1, 1)
        layout.addWidget(self.btnRotate, 1, 2)

        self.groupStepMotor.setLayout(layout)

    def rotate(self):
        state.AGILENT_SIGNAL_GENERATOR_FREQUENCY = self.angle.value()
        motor = StepMotorManager(address=state.STEP_MOTOR_ADDRESS)
        motor.rotate(self.angle.value())
