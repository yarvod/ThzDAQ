"""Log dock: application log records as they come, and what the
measurements tell (their runs, what the scripts of the bench's own print),
shown all together or of one measurement.

A record about a measurement carries it (tell): the filter offers every
measurement that told something.
"""

import logging
from collections import deque
from dataclasses import dataclass
from html import escape
from typing import Deque, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme

LEVEL_COLORS = {
    logging.WARNING: theme.ACCENT,
    logging.ERROR: theme.BAD,
    logging.CRITICAL: theme.BAD,
}
KEPT = 5000  # records the log keeps, of all measurements
ALL = "All"

# Attributes of a log record about a measurement
MEASUREMENT = "measurement"  # its procedure
MEASUREMENT_TITLE = "measurement_title"


# What measurements tell is logged whatever level the program logs at
_measurements = logging.getLogger("thzdaq_gui.measurements")
_measurements.setLevel(logging.INFO)


def tell(procedure: str, title: str, text: str, level: int = logging.INFO) -> None:
    """A line about a measurement: the log shows it under the measurement's
    title and filters by it."""
    _measurements.log(
        level, text, extra={MEASUREMENT: procedure, MEASUREMENT_TITLE: title}
    )


@dataclass(frozen=True)
class Record:
    level: int
    text: str
    measurement: str = ""  # the procedure it is about; empty: the program's
    title: str = ""  # of the measurement


class _Bridge(QObject):
    record = Signal(object)  # Record


class RecordFormatter(logging.Formatter):
    """Time, who tells (the measurement's title, else the logger), message."""

    def __init__(self):
        super().__init__("%(asctime)s  %(source)s  %(message)s", datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        record.source = getattr(record, MEASUREMENT_TITLE, "") or record.name
        return super().format(record)


class QtLogHandler(logging.Handler):
    """Thread-safe: records from worker threads reach the widget through a signal."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.bridge = _Bridge()
        self.setFormatter(RecordFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.record.emit(
                Record(
                    record.levelno,
                    self.format(record),
                    getattr(record, MEASUREMENT, ""),
                    getattr(record, MEASUREMENT_TITLE, ""),
                )
            )
        except RuntimeError:  # the window is gone
            pass


class LogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: Deque[Record] = deque(maxlen=KEPT)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        label = QLabel("Show")
        label.setProperty("role", "muted")
        row.addWidget(label)
        self.filter = QComboBox()
        self.filter.setToolTip("The whole log, or what one measurement told")
        self.filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.filter.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.filter.addItem(ALL, "")
        self.filter.currentIndexChanged.connect(self.show_records)
        row.addWidget(self.filter)
        row.addStretch()
        layout.addLayout(row)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(KEPT)
        layout.addWidget(self.text, 1)
        self.handler = QtLogHandler()
        self.handler.bridge.record.connect(self.add)
        logging.getLogger().addHandler(self.handler)

    def shown(self) -> Optional[str]:
        """The measurement shown alone; None: all."""
        return self.filter.currentData() or None

    def show_measurement(self, procedure: Optional[str]) -> None:
        """Only what this measurement told (None: all of the log)."""
        self.filter.setCurrentIndex(max(self.filter.findData(procedure or ""), 0))

    def add(self, record: Record) -> None:
        self.records.append(record)
        if record.measurement and self.filter.findData(record.measurement) < 0:
            self.filter.addItem(record.title or record.measurement, record.measurement)
        shown = self.shown()
        if shown is None or record.measurement == shown:
            self.append(record)

    def append(self, record: Record) -> None:
        color = LEVEL_COLORS.get(record.level)
        if color:
            self.text.appendHtml(
                f"<span style='color:{color}'>{escape(record.text)}</span>"
            )
        else:
            self.text.appendPlainText(record.text)

    def show_records(self, *_) -> None:
        shown = self.shown()
        self.text.clear()
        for record in self.records:
            if shown is None or record.measurement == shown:
                self.append(record)

    def detach(self) -> None:
        logging.getLogger().removeHandler(self.handler)
