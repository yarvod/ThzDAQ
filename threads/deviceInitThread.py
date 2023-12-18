import logging

from PyQt5.QtCore import pyqtSignal

from threads import Thread


logger = logging.getLogger(__name__)


class DeviceInitThread(Thread):
    status = pyqtSignal(str)

    def __init__(self, device_api_class, **kwargs):
        super().__init__()
        self.device_api_class = device_api_class
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            device = self.device_api_class(**self.kwargs)
            if device.test():
                self.status.emit("OK")
            else:
                self.status.emit("Error!")
        except TimeoutError as e:
            logger.warning(f"[{self.__class__.__name__}.run] Timeout error")
            self.status.emit("Timeout Error")
        self.finished.emit()
