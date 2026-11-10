"""A Python editor for scripts: line numbers, colours by pygments, indents kept
as Python wants them, a popup of completions, the lines a check finds wrong
marked. What completes a word is given (the dock of a script asks jedi and
the bench); the editor only shows it.

Keys: Tab indents (four spaces, the lines of a selection too), Shift+Tab
dedents, Enter keeps the indent (one more after a colon), Ctrl+Space or a
dot asks for completions, Ctrl+/ comments lines in and out.
"""

from typing import Callable, Dict, Iterable, List, Optional

from PySide6.QtCore import QRect, QSize, QStringListModel, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QKeySequence,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QCompleter,
    QPlainTextEdit,
    QTextEdit,
    QToolTip,
    QWidget,
)
from pygments.lexers import PythonLexer
from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token

from thzdaq_gui import theme

INDENT = "    "
COMMENT = "# "
# Words that complete a word, at the cursor: (text, line from 1, column from 0)
Complete = Callable[[str, int, int], List[str]]

# Colours of tokens: the theme's, in the order pygments' types nest
COLOURS = (
    (Comment, theme.MUTED),
    (String, "#a5d6a7"),
    (Number, "#90caf9"),
    (Keyword, theme.ACCENT),
    (Name.Builtin, "#ce93d8"),
    (Name.Function, "#ffe082"),
    (Name.Class, "#ffe082"),
    (Name.Decorator, "#ce93d8"),
    (Operator.Word, theme.ACCENT),
)
CURRENT_LINE = "#2f2f2f"
PROBLEM_LINE = "#4a2424"


def text_format(colour: str) -> QTextCharFormat:
    found = QTextCharFormat()
    found.setForeground(QColor(colour))
    return found


class PythonHighlighter(QSyntaxHighlighter):
    """Tokens of each line by pygments: a string over lines shows as code past
    its first line, which the editor of a short script can bear."""

    def __init__(self, document):
        super().__init__(document)
        self.lexer = PythonLexer(stripnl=False, ensurenl=False)
        self.formats = [(kind, text_format(colour)) for kind, colour in COLOURS]

    def format_of(self, kind) -> Optional[QTextCharFormat]:
        return next((found for k, found in self.formats if kind in k), None)

    def highlightBlock(self, text: str) -> None:
        at = 0
        for kind, value in self.lexer.get_tokens(text):
            found = None if kind is Token.Text else self.format_of(kind)
            if found is not None:
                self.setFormat(at, len(value), found)
            at += len(value)


class LineNumbers(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.numbers_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_numbers(self, event)


class CodeEditor(QPlainTextEdit):
    saved = Signal()  # Ctrl+S

    def __init__(self, complete: Optional[Complete] = None, parent=None):
        super().__init__(parent)
        self.complete = complete
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter = PythonHighlighter(self.document())
        self.numbers = LineNumbers(self)
        self.problems: Dict[int, str] = {}  # line from 1 -> what is wrong there
        self.blockCountChanged.connect(self._fit_numbers)
        self.updateRequest.connect(self._scroll_numbers)
        self.cursorPositionChanged.connect(self.mark_lines)
        self._fit_numbers()
        self.mark_lines()
        self.completer = QCompleter(self)
        self.completer.setModel(QStringListModel(self.completer))
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.activated.connect(self.insert_completion)

    # Line numbers
    def numbers_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * max(3, digits)

    def _fit_numbers(self, *_) -> None:
        self.setViewportMargins(self.numbers_width(), 0, 0, 0)

    def _scroll_numbers(self, rect: QRect, dy: int) -> None:
        if dy:
            self.numbers.scroll(0, dy)
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        area = self.contentsRect()
        self.numbers.setGeometry(
            QRect(area.left(), area.top(), self.numbers_width(), area.height())
        )

    def paint_numbers(self, widget: QWidget, event) -> None:
        painter = QPainter(widget)
        painter.fillRect(event.rect(), QColor(theme.BASE))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                line = number + 1
                colour = theme.BAD if line in self.problems else theme.MUTED
                painter.setPen(QColor(colour))
                painter.drawText(
                    0, top, widget.width() - 6, height, Qt.AlignRight, str(line)
                )
            block = block.next()
            top += round(self.blockBoundingRect(block).height())
            number += 1

    # Lines marked: the one with the cursor, those a check found wrong
    def mark_lines(self) -> None:
        marks: List[QTextEdit.ExtraSelection] = []
        for line in self.problems:
            block = self.document().findBlockByNumber(line - 1)
            if block.isValid():
                marks.append(self._mark(QTextCursor(block), PROBLEM_LINE))
        marks.append(self._mark(self.textCursor(), CURRENT_LINE))
        self.setExtraSelections(marks)

    @staticmethod
    def _mark(cursor: QTextCursor, colour: str) -> QTextEdit.ExtraSelection:
        mark = QTextEdit.ExtraSelection()
        mark.format.setBackground(QColor(colour))
        mark.format.setProperty(QTextFormat.FullWidthSelection, True)
        mark.cursor = cursor
        mark.cursor.clearSelection()
        return mark

    def set_problems(self, problems: Dict[int, str]) -> None:
        self.problems = dict(problems)
        self.mark_lines()
        self.numbers.update()

    def go_to(self, line: int) -> None:
        """The cursor at the start of a line (from 1), shown."""
        block = self.document().findBlockByNumber(max(0, line - 1))
        self.setTextCursor(QTextCursor(block))
        self.centerCursor()
        self.setFocus()

    def event(self, event) -> bool:
        if event.type() == event.Type.ToolTip:
            line = self.cursorForPosition(event.pos()).blockNumber() + 1
            if line in self.problems:
                QToolTip.showText(event.globalPos(), self.problems[line], self)
                return True
        return super().event(event)

    # Keys
    def keyPressEvent(self, event) -> None:
        if self.completer.popup().isVisible() and event.key() in (
            Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Escape,
        ):  # fmt: skip
            event.ignore()  # the popup takes them
            return
        if event.matches(QKeySequence.Save):
            self.saved.emit()
            return
        key, modifiers = event.key(), event.modifiers()
        if key == Qt.Key_Space and modifiers & Qt.ControlModifier:
            self.ask_completions()
            return
        if key == Qt.Key_Slash and modifiers & Qt.ControlModifier:
            self.toggle_comments()
            return
        if key == Qt.Key_Tab:
            self.indent()
            return
        if key == Qt.Key_Backtab:
            self.dedent()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.new_line()
            return
        super().keyPressEvent(event)
        if event.text() == ".":
            self.ask_completions()
        elif self.completer.popup().isVisible():
            self._filter()

    def _lines(self) -> Iterable[QTextCursor]:
        """A cursor at the start of each line of the selection (or the line)."""
        cursor = self.textCursor()
        document = self.document()
        first = document.findBlock(cursor.selectionStart())
        last = document.findBlock(
            max(cursor.selectionStart(), cursor.selectionEnd() - 1)
        )
        block = first
        while block.isValid():
            yield QTextCursor(block)
            if block == last:
                break
            block = block.next()

    def indent(self) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            column = cursor.positionInBlock()
            cursor.insertText(" " * (len(INDENT) - column % len(INDENT)))
            return
        cursor.beginEditBlock()
        for line in self._lines():
            line.insertText(INDENT)
        cursor.endEditBlock()

    def dedent(self) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for line in self._lines():
            text = line.block().text()
            spaces = len(text) - len(text.lstrip(" "))
            for _ in range(min(spaces, len(INDENT))):
                line.deleteChar()
        cursor.endEditBlock()

    def new_line(self) -> None:
        cursor = self.textCursor()
        before = cursor.block().text()[: cursor.positionInBlock()]
        indent = before[: len(before) - len(before.lstrip(" "))]
        if before.rstrip().endswith(":"):
            indent += INDENT
        cursor.insertText("\n" + indent)
        self.ensureCursorVisible()

    def toggle_comments(self) -> None:
        lines = list(self._lines())
        commented = all(
            line.block().text().lstrip().startswith(COMMENT.strip())
            for line in lines
            if line.block().text().strip()
        )
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for line in lines:
            text = line.block().text()
            if not text.strip():
                continue
            at = len(text) - len(text.lstrip())
            line.movePosition(QTextCursor.Right, n=at)
            if commented:
                mark = COMMENT if text[at:].startswith(COMMENT) else COMMENT.strip()
                for _ in mark:
                    line.deleteChar()
            else:
                line.insertText(COMMENT)
        cursor.endEditBlock()

    # Completions
    def word(self) -> str:
        """The part of a name before the cursor."""
        cursor = self.textCursor()
        before = cursor.block().text()[: cursor.positionInBlock()]
        start = len(before)
        while start and (before[start - 1].isalnum() or before[start - 1] == "_"):
            start -= 1
        return before[start:]

    def ask_completions(self) -> None:
        if self.complete is None:
            return
        cursor = self.textCursor()
        found = self.complete(
            self.toPlainText(), cursor.blockNumber() + 1, cursor.positionInBlock()
        )
        if not found:
            self.completer.popup().hide()
            return
        self.completer.model().setStringList(found)
        self._filter()

    def _filter(self) -> None:
        self.completer.setCompletionPrefix(self.word())
        if self.completer.completionCount() == 0:
            self.completer.popup().hide()
            return
        rect = self.cursorRect()
        rect.setWidth(
            self.completer.popup().sizeHintForColumn(0)
            + self.completer.popup().verticalScrollBar().sizeHint().width()
        )
        self.completer.popup().setCurrentIndex(
            self.completer.completionModel().index(0, 0)
        )
        self.completer.complete(rect)

    def insert_completion(self, text: str) -> None:
        cursor = self.textCursor()
        typed = self.word()
        cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, len(typed))
        cursor.insertText(text)
        self.setTextCursor(cursor)
