import asyncio

from PyQt6.QtCore import QThread, pyqtSignal

from api.Chopper.chopper import chopper


class ChopperThread(QThread):
    status = pyqtSignal(bool)
    method = "connect"

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def run(self):
        self.loop.run_until_complete(self.chopper_loop())
        self.finished.emit()

    async def chopper_loop(self):
        await chopper.connect()
        method = self.__getattribute__(self.method)
        await method()

    async def connect(self):
        self.status.emit(chopper.client.connected)

    async def path0(self):
        await chopper.path0()


chopper_thread = ChopperThread()
