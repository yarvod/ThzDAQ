"""What a console ran and what came of it, as a view: each block run with its
prompt (>>>, ... for its later lines), then what it printed (stderr in red),
its result, a traceback in the colours IPython gives it (ANSI codes) whose
places are links: a click opens the file at that line. A carriage return
writes its line again (progress told in place)."""

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from PySide6.QtGui import QColor, QFont, QFontDatabase, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextBrowser

from thzdaq_gui import theme
from thzdaq_gui.models.console import plain
from thzdaq_gui.script_output import OpenPlace, traceback_place

PROMPT, MORE = ">>> ", "... "
LINES_KEPT = 20_000  # lines of output kept; older ones go
SGR = re.compile(r"\x1b\[([0-9;]*)m")  # a change of colour
# The 16 colours of a terminal (normal, then bright), as the dark theme shows them
PALETTE = (
    "#1f1f1f", theme.BAD, "#a5d6a7", "#ffe082", "#90caf9", "#ce93d8", "#80deea",
    theme.TEXT, theme.MUTED, "#ef9a9a", "#c5e1a5", "#fff59d", "#bbdefb",
    "#e1bee7", "#b2ebf2", "#ffffff",
)  # fmt: skip
CUBE = (0, 95, 135, 175, 215, 255)  # the levels of xterm's 6×6×6 colours
FOREGROUND = {**{30 + i: i for i in range(8)}, **{90 + i: 8 + i for i in range(8)}}
BACKGROUND = {**{40 + i: i for i in range(8)}, **{100 + i: 8 + i for i in range(8)}}
EXTENDED_FOREGROUND, EXTENDED_BACKGROUND, INDEXED = 38, 48, 5


@dataclass(frozen=True)
class Style:
    colour: Optional[str] = None  # None: the text's own
    background: Optional[str] = None
    bold: bool = False


def xterm(index: int) -> str:
    """One of xterm's 256 colours."""
    if index < len(PALETTE):
        return PALETTE[index]
    if index < 232:
        index -= 16
        red, green, blue = index // 36, index // 6 % 6, index % 6
        return f"#{CUBE[red]:02x}{CUBE[green]:02x}{CUBE[blue]:02x}"
    grey = 8 + 10 * (index - 232)
    return f"#{grey:02x}{grey:02x}{grey:02x}"


def styled(style: Style, codes: str) -> Style:
    """The style after an SGR sequence's codes (\x1b[1;31m: 1;31)."""
    numbers = [int(code) for code in codes.split(";") if code] or [0]
    at = 0
    while at < len(numbers):
        code = numbers[at]
        if code in (EXTENDED_FOREGROUND, EXTENDED_BACKGROUND):
            indexed = numbers[at + 1 : at + 3]
            if len(indexed) == 2 and indexed[0] == INDEXED:
                colour = xterm(indexed[1])
                if code == EXTENDED_FOREGROUND:
                    style = replace(style, colour=colour)
                else:
                    style = replace(style, background=colour)
            at += 3
            continue
        if code == 0:
            style = Style()
        elif code == 1:
            style = replace(style, bold=True)
        elif code == 22:
            style = replace(style, bold=False)
        elif code == 39:
            style = replace(style, colour=None)
        elif code == 49:
            style = replace(style, background=None)
        elif code in FOREGROUND:
            style = replace(style, colour=PALETTE[FOREGROUND[code]])
        elif code in BACKGROUND:
            style = replace(style, background=PALETTE[BACKGROUND[code]])
        at += 1
    return style


def spans(text: str) -> Iterator[Tuple[str, Style]]:
    """Pieces of text coloured as its ANSI codes say, the codes left out."""
    style, at = Style(), 0
    for found in SGR.finditer(text):
        if found.start() > at:
            yield text[at : found.start()], style
        style = styled(style, found[1])
        at = found.end()
    if at < len(text):
        yield text[at:], style


class ConsoleOutput(QTextBrowser):
    def __init__(self, open_place: OpenPlace, parent=None):
        """open_place(file, line): a place of a traceback, clicked."""
        super().__init__(parent)
        self.open_place = open_place
        self.places: Dict[str, Tuple[Path, int]] = {}  # by the href of its link
        self.setOpenLinks(False)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.document().setMaximumBlockCount(LINES_KEPT)
        self.anchorClicked.connect(self._clicked)

    def _end(self) -> QTextCursor:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        return cursor

    def _format(self, style: Style, base: Optional[str] = None) -> QTextCharFormat:
        found = QTextCharFormat()
        found.setForeground(QColor(style.colour or base or theme.TEXT))
        if style.background:
            found.setBackground(QColor(style.background))
        if style.bold:
            found.setFontWeight(QFont.Bold)
        return found

    def _write(self, write) -> None:
        """Written at the end; followed when the end was shown."""
        bar = self.verticalScrollBar()
        following = bar.value() == bar.maximum()
        write(self._end())
        if following:
            bar.setValue(bar.maximum())

    # What is shown
    def add_input(self, code: str) -> None:
        def write(cursor: QTextCursor) -> None:
            self._new_line(cursor)
            for number, line in enumerate(code.rstrip("\n").split("\n")):
                prompt = self._format(Style(theme.ACCENT, bold=True))
                cursor.insertText(MORE if number else PROMPT, prompt)
                cursor.insertText(line + "\n", self._format(Style()))

        self._write(write)

    def add_text(self, text: str, base: Optional[str] = None) -> None:
        """Text with ANSI colours (base: the colour of the rest); a place of
        a traceback is a link, a carriage return writes its line again."""
        self._write(lambda cursor: self._insert(cursor, text, base))

    def add_traceback(self, lines: List[str]) -> None:
        self.add_text("\n".join(lines) + "\n", theme.BAD)

    def add_note(self, text: str) -> None:
        """What the console says itself."""

        def write(cursor: QTextCursor) -> None:
            self._new_line(cursor)
            note = self._format(Style(theme.MUTED))
            note.setFontItalic(True)
            cursor.insertText(text + "\n", note)

        self._write(write)

    def clear_output(self) -> None:
        self.clear()
        self.places.clear()

    @staticmethod
    def _new_line(cursor: QTextCursor) -> None:
        """What follows starts a line of its own."""
        if cursor.positionInBlock() > 0:
            cursor.insertText("\n")

    def _insert(self, cursor: QTextCursor, text: str, base: Optional[str]) -> None:
        text = text.replace("\r\n", "\n")
        for number, again in enumerate(text.split("\r")):
            if number:  # back to the start of its line: written over
                cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
            for line in again.splitlines(keepends=True):
                self._insert_line(cursor, line, base)

    def _insert_line(self, cursor: QTextCursor, line: str, base: Optional[str]):
        start = cursor.position()
        for piece, style in spans(line):
            cursor.insertText(piece, self._format(style, base))
        place = traceback_place(plain(line))
        if place is None:
            return
        href = f"place:{len(self.places)}"
        self.places[href] = place
        link = QTextCharFormat()
        link.setAnchor(True)
        link.setAnchorHref(href)
        link.setFontUnderline(True)
        end = cursor.position() - (1 if line.endswith("\n") else 0)
        marked = QTextCursor(cursor)
        marked.setPosition(start)
        marked.setPosition(end, QTextCursor.KeepAnchor)
        marked.mergeCharFormat(link)

    def _clicked(self, url) -> None:
        place = self.places.get(url.toString())
        if place is not None:
            self.open_place(*place)
