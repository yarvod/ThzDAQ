from PyQt6.QtWidgets import QGroupBox, QPushButton, QVBoxLayout, QLabel, QFormLayout

from interface.threads import chopper_thread


class ChopperManagingGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Chopper")
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.currentPositionLabel = QLabel(self)
        self.currentPositionLabel.setText("Position:")
        self.currentPosition = QLabel(self)
        self.currentPosition.setText("Unknown")

        self.btnRotate = QPushButton("Rotate")
        self.btnRotate.clicked.connect(self.rotate)

        form_layout.addRow(self.currentPositionLabel, self.currentPosition)
        layout.addLayout(form_layout)

        layout.addWidget(self.btnRotate)

        self.setLayout(layout)

        # self.monitorCurrentPosition()

    def rotate(self):
        self.btnRotate.setEnabled(False)
        chopper_thread.method = chopper_thread.PATH0
        chopper_thread.finished.connect(lambda: self.btnRotate.setEnabled(True))
        chopper_thread.start()

    def monitorCurrentPosition(self):
        chopper_thread.method = chopper_thread.GET_ACTUAL_POS
        chopper_thread.start()
        chopper_thread.position.connect(
            lambda pos: self.currentPosition.setText(f"{pos}")
        )
