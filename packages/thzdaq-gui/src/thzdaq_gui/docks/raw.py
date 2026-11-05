"""Raw commands to an instrument from its dock, for what its driver does not
wrap yet: a line to type a command in (Up and Down bring back the earlier
ones) and what came back below it. A query (with ?) goes at once; a write is
confirmed first, since no limit checks it. The commands wait their turn in
the instrument's queue, as the dock's reads and sets do."""

from typing import List

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from thzdaq_api.devices import RawReply, raw_query, raw_question

from thzdaq_gui import theme
from thzdaq_gui.models.device import DeviceModel

KEPT = 500  # lines the console keeps
RECALL = {Qt.Key_Up: 1, Qt.Key_Down: -1}  # how far back a key goes in the history


class RawConsole(QWidget):
    def __init__(self, model: DeviceModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.history: List[str] = []
        self.back = 0  # how far back in the history the line is; 0: a new one
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.line = QLineEdit()
        self.line.setPlaceholderText("*IDN?")
        self.line.setToolTip(
            "A command as the instrument takes it: with ? a query, else a write"
        )
        self.line.returnPressed.connect(self.send)
        self.line.installEventFilter(self)
        self.answer = QCheckBox("Answer")
        self.answer.setToolTip(
            "Read the answer of a write too (a query always has one)"
        )
        self.button = QPushButton(theme.icon("send"), "Send")
        self.button.clicked.connect(self.send)
        row.addWidget(self.line, 1)
        row.addWidget(self.answer)
        row.addWidget(self.button)
        layout.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(KEPT)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.log.setPlaceholderText(
            f"Commands to {model.lane} as typed, for what its driver does not "
            "wrap yet. Nothing checks a write: put a command used often into "
            "the driver."
        )
        layout.addWidget(self.log)
        model.raw_done.connect(self.answered)
        model.raw_failed.connect(self.failed)

    def send(self) -> None:
        command = self.line.text().strip()
        if not command:
            return
        if not raw_query(command):
            asked = QMessageBox.question(
                self, "Send a raw command", raw_question(self.model.lane, command)
            )
            if asked != QMessageBox.Yes:
                return
        self.history.append(command)
        self.back = 0
        self.line.clear()
        self.log.appendPlainText(f"> {command}")
        self.model.raw(command, self.answer.isChecked())

    def answered(self, reply: RawReply) -> None:
        if reply.answer is not None:
            self.log.appendPlainText(f"< {reply.answer}")
        else:
            self.log.appendPlainText(f"  sent; read again: {', '.join(reply.unknown)}")

    def failed(self, command: str, message: str) -> None:
        self.log.appendPlainText(f"! {message}")

    def recall(self, step: int) -> None:
        """An earlier command into the line (step 1 back, -1 forth)."""
        self.back = max(0, min(len(self.history), self.back + step))
        self.line.setText(self.history[-self.back] if self.back else "")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.line
            and event.type() == QEvent.KeyPress
            and event.key() in RECALL
        ):
            self.recall(RECALL[event.key()])
            return True
        return super().eventFilter(watched, event)
