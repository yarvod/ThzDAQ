"""Event log dock: application log records as they come."""

import logging
from html import escape

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit

from thzdaq_gui import theme

LEVEL_COLORS = {
    logging.WARNING: theme.ACCENT,
    logging.ERROR: "#e57373",
    logging.CRITICAL: "#e57373",
}


class _Bridge(QObject):
    record = Signal(int, str)


class QtLogHandler(logging.Handler):
    """Thread-safe: records from worker threads reach the widget through a signal."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.bridge = _Bridge()
        self.setFormatter(
            logging.Formatter("%(asctime)s  %(name)s  %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.record.emit(record.levelno, self.format(record))
        except RuntimeError:  # the window is gone
            pass


class LogWidget(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.handler = QtLogHandler()
        self.handler.bridge.record.connect(self.add)
        logging.getLogger().addHandler(self.handler)

    def add(self, level: int, text: str) -> None:
        color = LEVEL_COLORS.get(level)
        if color:
            self.appendHtml(f"<span style='color:{color}'>{escape(text)}</span>")
        else:
            self.appendPlainText(text)

    def detach(self) -> None:
        logging.getLogger().removeHandler(self.handler)
