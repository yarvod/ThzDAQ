import asyncio

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QGroupBox, QGridLayout, QPushButton

from api.Chopper.chopper import Chopper
from store.state import state


class ChopperThread(QThread):
    def run(self):
        chopper = Chopper(host=state.CHOPPER_HOST)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
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
        self.chopper_thread = ChopperThread()
        self.btnRotate.setEnabled(False)
        self.chopper_thread.finished.connect(lambda: self.btnRotate.setEnabled(True))
        self.chopper_thread.start()
        # chopper = Chopper(host=state.CHOPPER_HOST)
        # loop = asyncio.new_event_loop()
        # asyncio.set_event_loop(loop)
        # loop.run_until_complete(chopper.path0())
        # loop.close()
