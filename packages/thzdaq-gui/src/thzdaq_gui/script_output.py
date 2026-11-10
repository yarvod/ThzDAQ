"""What a script printed, as a view: places of a traceback are links (a
double click opens the file at that line), its first and last lines errors.
The dock of a measurement of the bench's own and the dock of a script's file
show it."""

import re
from pathlib import Path
from typing import Callable, Optional, Tuple

from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QPlainTextEdit

from thzdaq_gui import theme

# A line of a traceback that names a place: File "/x/scan.py", line 12, in <module>
PLACE = re.compile(r'^\s*File "(?P<file>.+)", line (?P<line>\d+)')
FAILURE = re.compile(r"^(Traceback \(most recent call last\):|\w+(Error|Exception)\b)")

OpenPlace = Callable[[Path, int], None]


def traceback_place(line: str) -> Optional[Tuple[Path, int]]:
    """The file and line a line of a traceback names; None for another line."""
    found = PLACE.match(line)
    if found is None:
        return None
    return Path(found["file"]), int(found["line"])


class Traceback(QSyntaxHighlighter):
    """Places in a traceback as links, its first and last lines as errors."""

    def __init__(self, document):
        super().__init__(document)
        self.place = QTextCharFormat()
        self.place.setForeground(QColor(theme.ACCENT))
        self.place.setFontUnderline(True)
        self.failure = QTextCharFormat()
        self.failure.setForeground(QColor(theme.BAD))

    def highlightBlock(self, text: str) -> None:
        if PLACE.match(text):
            self.setFormat(0, len(text), self.place)
        elif FAILURE.match(text):
            self.setFormat(0, len(text), self.failure)


class ScriptOutput(QPlainTextEdit):
    """What a script printed; a double click on a place of a traceback opens
    it (open_place(file, line))."""

    def __init__(self, open_place: OpenPlace, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.open_place = open_place
        self.setReadOnly(True)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setPlaceholderText(placeholder)
        self.highlighter = Traceback(self.document())

    def add(self, text: str) -> None:
        """More of the output, at its end (followed when it was shown)."""
        bar = self.verticalScrollBar()
        following = bar.value() == bar.maximum()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        if following:
            bar.setValue(bar.maximum())

    def show_whole(self, text: str) -> None:
        self.setPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def mouseDoubleClickEvent(self, event) -> None:
        line = self.cursorForPosition(event.position().toPoint()).block().text()
        place = traceback_place(line)
        if place is None:
            super().mouseDoubleClickEvent(event)
        else:
            self.open_place(*place)
