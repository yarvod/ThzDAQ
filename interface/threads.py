import asyncio

from PyQt6.QtCore import QThread, pyqtSignal

from api.Chopper.chopper import Chopper
from store.state import state


class ChopperThread(QThread):
    status = pyqtSignal(bool)
    method = "connect"

    def __init__(self):
        super().__init__()
        self.chopper = None
        self.init_chopper()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def run(self):
        self.loop.run_until_complete(self.chopper_loop())
        self.finished.emit()

    def init_chopper(self):
        if self.chopper is not None:
            self.chopper.close()
            del self.chopper
        self.chopper = Chopper(host=state.CHOPPER_HOST)

    async def chopper_loop(self):
        await self.chopper.connect()
        method = self.__getattribute__(self.method)
        await method()

    async def connect(self):
        self.status.emit(self.chopper.client.connected)

    async def path0(self):
        await self.chopper.path0()


chopper_thread = ChopperThread()
