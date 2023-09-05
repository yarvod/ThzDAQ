import asyncio

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QGroupBox, QGridLayout, QPushButton

from api.Chopper.chopper import chopper
from interface.threads import chopper_thread


class ChopperThread(QThread):
    def run(self):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(chopper.path0())
        self.finished.emit()


class ChopperManagingGroup(QGroupBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Chopper")
        layout = QGridLayout(self)

        self.btnRotate = QPushButton("Rotate")
        self.btnRotate.clicked.connect(self.rotate)

        layout.addWidget(self.btnRotate)

        self.setLayout(layout)

    def rotate(self):
        self.btnRotate.setEnabled(False)
        chopper_thread.method = "path0"
        chopper_thread.finished.connect(lambda: self.btnRotate.setEnabled(True))
        chopper_thread.start()
        # loop = asyncio.get_event_loop()
        # for i in range(10):
        #     loop.run_until_complete(chopper.path0())
