import logging

from PySide6.QtCore import Signal

from threads import Thread
from utils.exceptions import DeviceConnectionError

logger = logging.getLogger(__name__)


class AdapterInitThread(Thread):
    status = Signal(str)

    def __init__(self, adapter_class, **kwargs):
        super().__init__()
        self.adapter_class = adapter_class
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            adapter = self.adapter_class(**self.kwargs)
            adapter.close()
            # Set new IP for prologix and connect again
            adapter.host = self.kwargs.get("host")
            adapter.port = int(self.kwargs.get("port", 1234))
            adapter.socket = None
            adapter.init()
            adapter.setup()
            logger.info(
                f"[{self.__class__.__name__}.run] Prologix Ethernet Initialized"
            )
            self.status.emit("OK")
        except (TimeoutError, OSError, DeviceConnectionError) as e:
            logger.warning(f"[{self.__class__.__name__}.run] Error: {e}")
            self.status.emit("Connection Error!")
        self.finished.emit()
