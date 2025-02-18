import logging

from PySide6.QtCore import QThread


logger = logging.getLogger(__name__)


class Thread(QThread):
    def pre_exit(self, *args, **kwargs):
        ...

    def terminate(self) -> None:
        self.pre_exit()
        super().terminate()
        logger.info(f"[{self.__class__.__name__}.terminate] Terminated")

    def quit(self) -> None:
        self.pre_exit()
        super().quit()
        logger.info(f"[{self.__class__.__name__}.quit] Quited")

    def exit(self, returnCode: int = ...):
        self.pre_exit()
        super().exit(returnCode)
        logger.info(f"[{self.__class__.__name__}.exit] Exited")
